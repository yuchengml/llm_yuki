"""Concrete ``Fixer``: deterministic ``code_auto_fix`` + LLM-backed ``llm_periodic_fix``.

``code_auto_fix`` only ever takes safe, conservative actions on structural issues (Algorithm 1 line 10,
proposal ARCHITECTURE.md §4.1): strip a dangling reference rather than invent a target; sanitize an obviously
fixable ``source_ref`` (stray whitespace) rather than guess the right value; drop a candidate that would
overwrite a page outside this passage's selection, or collide slugs across types, rather than corrupt the
namespace. Anything it can't safely resolve is left for ``ErrorBook``/``ActiveConstraints`` to carry forward
as a constraint for the next round — ``code_auto_fix`` never invents content.
"""

from __future__ import annotations

import re
import time

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import OpenAICompatibleClient
from llm_yuki.adapters.llm.compiled_update_parsing import parse_compiled_update
from llm_yuki.adapters.llm.json_utils import parse_json_object
from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.error_book import ErrorBook, ErrorBookEntry, ValidationIssue
from llm_yuki.domain.pipeline import CompiledUpdate, Fixer
from llm_yuki.domain.structural_checks import source_ref_well_formed
from llm_yuki.ports.writer import Writer

_DROP_TYPES = frozenset({"unseen_overwrite", "index_inconsistency"})
_WHITESPACE = re.compile(r"\s+")
_CONTENT_ERROR_TYPES = frozenset({"unsupported_facts", "cross_page_contradictions"})

_LLM_PERIODIC_FIX_SYSTEM_PROMPT = """\
You are the LLMPeriodicFix step of a wiki-compilation pipeline. You are given a list of open content-quality \
issues (unsupported facts, cross-page contradictions) found by earlier lint passes, each with its root cause \
and the current content of the pages it affects. Propose corrected versions of just the affected pages that \
resolve each issue, using this exact JSON schema:

{
  "claims": [{"slug": "...", "claim_text": "...", "description": "...", "source_ref": "...",
    "confidence": 0.0-1.0, "provenance_state": "extracted"|"merged"|"inferred"|"ambiguous",
    "related_concepts": ["slug", ...], "contradicted_by": [{"slug": "...", "reason": "..."}]}],
  "concepts": [{"slug": "...", "concept_title": "...", "aliases": [...], "tags": [...], "summary": "...",
    "description": "...", "related_pages": [...], "related_sources": [...]}]
}

Include a page only if you are changing it to fix a listed issue, and repeat every field of that page, not \
just the changed ones — your output fully replaces the current version. If a concept's summary already uses \
markdown "## " subsections, preserve that structure while fixing the unrelated issue — don't flatten it into \
a single paragraph. Do not include a "key_facts" field on concepts. If you cannot confidently fix an issue, \
omit that page rather than guessing.
Return {"claims": [], "concepts": []} if none of the issues can be confidently fixed."""


class DefaultFixer(Fixer):
    """``llm_client=None`` disables ``llm_periodic_fix`` (raises) — ``code_auto_fix`` works standalone."""

    def __init__(
        self, llm_client: OpenAICompatibleClient | None = None, cost_ledger: JsonlCostLedger | None = None
    ) -> None:
        self._llm_client = llm_client
        self._cost_ledger = cost_ledger

    def code_auto_fix(self, update: CompiledUpdate, structural_issues: list[ValidationIssue]) -> CompiledUpdate:
        """``U ← CodeAutoFix(U, E_s)``: deterministic repair of structural issues, applied immediately."""
        dropped = _slugs_of_type(structural_issues, _DROP_TYPES)
        dangling_targets = _slugs_of_type(structural_issues, {"dangling_links"})
        malformed_slugs = _slugs_of_type(structural_issues, {"malformed_refs"})

        claims = [
            _sanitize_claim(claim, dangling_targets, malformed_slugs)
            for claim in update.claims
            if claim.slug not in dropped
        ]
        concepts = [
            _sanitize_concept(concept, dangling_targets) for concept in update.concepts if concept.slug not in dropped
        ]
        return CompiledUpdate(claims=claims, concepts=concepts)

    def llm_periodic_fix(self, error_book: ErrorBook, writer: Writer, batch_id: int) -> None:
        """``W ← LLMPeriodicFix(W, ℬ)``: LLM-driven repair of content issues, run every N batches (§4.3).

        Only acts on open entries of the two content error types (§4.1 #6-7) — structural issues are
        handled immediately by ``code_auto_fix``/constraint injection, never here. Does not close entries:
        that is ``ErrorBook.verify_and_close``'s job, called by ``Orchestrator`` right after this.
        """
        if self._llm_client is None or self._cost_ledger is None:
            raise RuntimeError(
                "DefaultFixer.llm_periodic_fix requires llm_client and cost_ledger "
                "(see ARCHITECTURE.md §2.1, TODO.md §B)"
            )
        entries = [e for e in error_book.entries if e.status == "open" and e.error_type in _CONTENT_ERROR_TYPES]
        if not entries:
            return

        user_prompt = "Open content issues:\n\n" + "\n\n".join(_describe_entry(entry, writer) for entry in entries)

        start = time.monotonic()
        response = self._llm_client.complete(
            [
                {"role": "system", "content": _LLM_PERIODIC_FIX_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format_json=True,
        )
        wall_clock_ms = (time.monotonic() - start) * 1000
        self._cost_ledger.record(
            "Fixer.LLMPeriodicFix",
            batch_id,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            wall_clock_ms=wall_clock_ms,
        )

        payload = parse_json_object(response.content, context="Fixer.LLMPeriodicFix")
        fixed = parse_compiled_update(payload, context="Fixer.LLMPeriodicFix")
        for claim in fixed.claims:
            writer.write_claim(claim)
        for concept in fixed.concepts:
            writer.write_concept(concept)


def _slugs_of_type(issues: list[ValidationIssue], error_types: frozenset[str] | set[str]) -> set[str]:
    return {ref for issue in issues if issue.error_type in error_types for ref in issue.affected_refs}


def _describe_entry(entry: ErrorBookEntry, writer: Writer) -> str:
    pages_text = "\n".join(_describe_page(slug, writer) for slug in entry.affected_refs) or "  (no pages found)"
    return (
        f"- error_type: {entry.error_type}\n"
        f"  phenomenon: {entry.phenomenon}\n"
        f"  root_cause: {entry.root_cause or '(unknown)'}\n"
        f"  affected pages:\n{pages_text}"
    )


def _describe_page(slug: str, writer: Writer) -> str:
    claim = writer.read_claim(slug)
    if claim is not None:
        return f"    - {slug} (Claim): claim_text={claim.claim_text!r}, source_ref={claim.source_ref!r}"
    concept = writer.read_concept(slug)
    if concept is not None:
        return f"    - {slug} (Concept): concept_title={concept.concept_title!r}, summary={concept.summary!r}"
    return f"    - {slug}: (page not found)"


def _normalize_source_ref(source_ref: str) -> str:
    """Best-effort sanitize: trim, collapse internal whitespace to ``-``. Not a full grammar fix."""
    return _WHITESPACE.sub("-", source_ref.strip())


def _sanitize_claim(claim: Claim, dangling_targets: set[str], malformed_slugs: set[str]) -> Claim:
    related_concepts = [slug for slug in claim.related_concepts if slug not in dangling_targets]
    contradicted_by = [ref for ref in claim.contradicted_by if ref.slug not in dangling_targets]

    source_ref = claim.source_ref
    if claim.slug in malformed_slugs:
        candidate = _normalize_source_ref(claim.source_ref)
        if source_ref_well_formed(candidate):
            source_ref = candidate

    if (
        related_concepts == claim.related_concepts
        and contradicted_by == claim.contradicted_by
        and source_ref == claim.source_ref
    ):
        return claim
    return claim.model_copy(
        update={"related_concepts": related_concepts, "contradicted_by": contradicted_by, "source_ref": source_ref}
    )


def _sanitize_concept(concept: Concept, dangling_targets: set[str]) -> Concept:
    related_pages = [slug for slug in concept.related_pages if slug not in dangling_targets]
    if related_pages == concept.related_pages:
        return concept
    return concept.model_copy(update={"related_pages": related_pages})
