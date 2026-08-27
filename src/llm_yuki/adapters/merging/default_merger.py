"""Deterministic ``Merger``: dedupe candidates by slug, decide final content (proposal ARCHITECTURE.md §2.2.2).

Does not persist — that is the ``Writer``'s job (2.2.2, "不負責實際持久化"). Dedup is slug-exact: two
candidates (or a candidate and an already-persisted page) merge only when they share a ``slug``. Semantic
dedup — two candidates describing the same thing under different slugs — needs fuzzy/embedding matching or
an LLM judgment call and is out of scope for this deterministic baseline (see ``TODO.md`` §B).

``Concept.summary`` merging follows D22's three-layer protection:
  1. Deterministic (always): array fields are a set union; ``summary`` falls back to ``new or old``.
  2. LLM merge + rejection (only on a real conflict, and only when ``llm_client`` is configured — otherwise
     this layer is a no-op and layer 1's result stands, same as before D22 shipped): merge ``old``/``new``
     summaries with the LLM; if the merged result is shorter than 70% of ``max(len(old), len(new))``, reject
     it as suspected content loss and keep the *old* summary instead (the 70% threshold is borrowed verbatim
     from ``llm_wiki``'s ``BODY_SHRINK_THRESHOLD``, ASSUMPTIONS.md A-13 — not recalibrated for our data).
  3. Locked fields (always): ``concept_title`` never changes on merge, regardless of what layers 1-2 produce —
     same "deterministic overrides LLM" principle as D17/D18.

``Document.summary`` generation (D21 §1.5) is this class's other LLM-backed responsibility ("延伸職責,不是新
模組" — an extension of Merger's job, not a new module): a recursive batch-reduce over a document's
``Claim.claim_text``s, budgeted by a fixed character quota borrowed in spirit from ``llm_wiki``'s
``context-budget.ts``. Fits in one call: summarize directly. Doesn't fit: split into budget-sized batches,
summarize each, then recurse on the batch summaries until they fit — deliberately no round cap (ASSUMPTIONS.md
B-5).
"""

from __future__ import annotations

import time

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import OpenAICompatibleClient
from llm_yuki.domain.entities import Claim, Concept, ContradictionRef
from llm_yuki.domain.pipeline import CompiledUpdate, Merger
from llm_yuki.ports.writer import Writer

_SUMMARY_REJECTION_RATIO = 0.7

_MERGE_SUMMARY_SYSTEM_PROMPT = """\
You are the summary-merge step of a wiki-compilation pipeline. You are given the existing summary of a \
Concept page and a new candidate summary describing the same Concept, drawn from a different source passage. \
Merge them into a single, coherent one-paragraph summary that preserves every distinct fact from both — do \
not drop information from either side. Respond with the merged summary text only, no extra commentary."""

_DOCUMENT_BUDGET_CHARS = 6000
"""Fixed-ratio quota per batch-reduce call — spirit borrowed from ``llm_wiki``'s ``context-budget.ts`` (D21),
not a token-accurate count. Not recalibrated against real corpus data (ASSUMPTIONS.md B-5)."""

_SUMMARIZE_DOCUMENT_SYSTEM_PROMPT = """\
You are the Document.summary generation step of a wiki-compilation pipeline (recursive batch-reduce). You are \
given a list of facts about one source document — either its extracted Claims, or summaries produced by an \
earlier reduction round over batches of those Claims. Write a single coherent one-paragraph summary that \
captures every distinct fact from the list. Respond with the summary text only, no extra commentary."""


class DefaultMerger(Merger):
    """Slug-exact dedup. ``llm_client=None`` disables D22 layer 2 (``code_auto_fix``-style optional LLM step)."""

    def __init__(
        self, llm_client: OpenAICompatibleClient | None = None, cost_ledger: JsonlCostLedger | None = None
    ) -> None:
        self._llm_client = llm_client
        self._cost_ledger = cost_ledger

    def merge(self, update: CompiledUpdate, writer: Writer, batch_id: int) -> CompiledUpdate:
        """Resolve ``is_new`` / merge against existing pages before ``ApplyUpdates``."""
        return CompiledUpdate(
            claims=self._merge_claims(update.claims, writer),
            concepts=self._merge_concepts(update.concepts, writer, batch_id),
        )

    def _merge_claims(self, claims: list[Claim], writer: Writer) -> list[Claim]:
        by_slug: dict[str, Claim] = {}
        for claim in claims:
            by_slug[claim.slug] = self._merge_claim_pair(by_slug[claim.slug], claim) if claim.slug in by_slug else claim

        merged: list[Claim] = []
        for slug, claim in by_slug.items():
            existing = writer.read_claim(slug)
            merged.append(self._merge_claim_pair(existing, claim) if existing is not None else claim)
        return merged

    def _merge_concepts(self, concepts: list[Concept], writer: Writer, batch_id: int) -> list[Concept]:
        by_slug: dict[str, Concept] = {}
        for concept in concepts:
            by_slug[concept.slug] = (
                self._merge_concept_pair(by_slug[concept.slug], concept, batch_id)
                if concept.slug in by_slug
                else concept
            )

        merged: list[Concept] = []
        for slug, concept in by_slug.items():
            existing = writer.read_concept(slug)
            merged.append(self._merge_concept_pair(existing, concept, batch_id) if existing is not None else concept)
        return merged

    @staticmethod
    def _merge_claim_pair(base: Claim, new: Claim) -> Claim:
        return base.model_copy(
            update={
                "claim_text": new.claim_text or base.claim_text,
                "source_ref": new.source_ref or base.source_ref,
                "confidence": max(base.confidence, new.confidence),
                "provenance_state": "merged",
                "related_concepts": _union(base.related_concepts, new.related_concepts),
                "contradicted_by": _union_contradictions(base.contradicted_by, new.contradicted_by),
            }
        )

    def _merge_concept_pair(self, base: Concept, new: Concept, batch_id: int) -> Concept:
        return base.model_copy(
            update={
                "concept_title": base.concept_title,  # layer 3: locked, never changed by a merge
                "aliases": _union(base.aliases, new.aliases),
                "tags": _union(base.tags, new.tags),
                "summary": self._merge_summary(base.summary, new.summary, batch_id),
                "key_facts": _union(base.key_facts, new.key_facts),
                "related_pages": _union(base.related_pages, new.related_pages),
                "related_sources": _union(base.related_sources, new.related_sources),
            }
        )

    def _merge_summary(self, old: str, new: str, batch_id: int) -> str:
        """D22 layers 1-2, see module docstring."""
        layer_1_result = new or old
        if not _has_real_conflict(old, new) or self._llm_client is None or self._cost_ledger is None:
            return layer_1_result

        merged = self._call_llm_merge(old, new, batch_id, self._llm_client, self._cost_ledger)
        threshold = _SUMMARY_REJECTION_RATIO * max(len(old), len(new))
        if len(merged) < threshold:
            return old  # suspected content loss: reject the merge, keep the previously validated old summary
        return merged

    @staticmethod
    def _call_llm_merge(
        old: str, new: str, batch_id: int, llm_client: OpenAICompatibleClient, cost_ledger: JsonlCostLedger
    ) -> str:
        user_prompt = f"Existing summary:\n{old}\n\nNew candidate summary:\n{new}"
        start = time.monotonic()
        response = llm_client.complete(
            [
                {"role": "system", "content": _MERGE_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
        wall_clock_ms = (time.monotonic() - start) * 1000
        cost_ledger.record(
            "Merger.summary_merge",
            batch_id,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            wall_clock_ms=wall_clock_ms,
        )
        return response.content.strip()

    def summarize_document(self, document_slug: str, claim_texts: list[str], writer: Writer, batch_id: int) -> str:
        """D21 §1.5: recursive batch-reduce over ``claim_texts``, see module docstring."""
        if not claim_texts:
            return ""
        if self._llm_client is None or self._cost_ledger is None:
            raise RuntimeError(
                "DefaultMerger.summarize_document requires llm_client and cost_ledger "
                "(see ARCHITECTURE.md §1.5, TODO.md §B)"
            )
        return self._batch_reduce(claim_texts, batch_id, round_number=0)

    def _batch_reduce(self, texts: list[str], batch_id: int, round_number: int) -> str:
        assert self._llm_client is not None and self._cost_ledger is not None  # checked by summarize_document
        if len(texts) == 1 or _fits_budget(texts):
            return self._summarize_batch(texts, batch_id, round_number)

        batch_summaries = [self._summarize_batch(batch, batch_id, round_number) for batch in _split_into_batches(texts)]
        return self._batch_reduce(batch_summaries, batch_id, round_number + 1)

    def _summarize_batch(self, texts: list[str], batch_id: int, round_number: int) -> str:
        assert self._llm_client is not None and self._cost_ledger is not None  # checked by summarize_document
        user_prompt = "Facts:\n" + "\n".join(f"- {text}" for text in texts)
        start = time.monotonic()
        response = self._llm_client.complete(
            [
                {"role": "system", "content": _SUMMARIZE_DOCUMENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
        wall_clock_ms = (time.monotonic() - start) * 1000
        self._cost_ledger.record(
            "Merger.summarize_document",
            batch_id,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            wall_clock_ms=wall_clock_ms,
            round=round_number,
        )
        return response.content.strip()


def _fits_budget(texts: list[str]) -> bool:
    return sum(len(text) for text in texts) <= _DOCUMENT_BUDGET_CHARS


def _split_into_batches(texts: list[str]) -> list[list[str]]:
    """Greedily group ``texts`` into budget-sized batches, preserving order."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for text in texts:
        if current and current_len + len(text) > _DOCUMENT_BUDGET_CHARS:
            batches.append(current)
            current = []
            current_len = 0
        current.append(text)
        current_len += len(text)
    if current:
        batches.append(current)
    return batches


def _has_real_conflict(old: str, new: str) -> bool:
    """True when ``old``/``new`` genuinely disagree — not just one being empty, equal, or a substring of the other.

    A substring relationship is treated as simple concatenation/extension, not a conflict: layer 1's
    ``new or old`` already handles it without needing an LLM call.
    """
    old, new = old.strip(), new.strip()
    if not old or not new or old == new:
        return False
    return old not in new and new not in old


def _union(a: list[str], b: list[str]) -> list[str]:
    """Order-preserving union, first occurrence wins position."""
    result = list(a)
    result.extend(item for item in b if item not in result)
    return result


def _union_contradictions(a: list[ContradictionRef], b: list[ContradictionRef]) -> list[ContradictionRef]:
    """Order-preserving union of ContradictionRef, deduped by ``slug`` (first reason wins)."""
    result = list(a)
    known_slugs = {ref.slug for ref in result}
    for ref in b:
        if ref.slug not in known_slugs:
            result.append(ref)
            known_slugs.add(ref.slug)
    return result
