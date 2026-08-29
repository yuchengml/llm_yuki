"""Orchestrator and its sub-steps — Algorithm 1 from the LLM-Wiki paper (proposal ARCHITECTURE.md §3).

``Extractor``/``Merger``/``Validator``/``Fixer`` are interface stubs: their real implementations call an LLM
and are out of scope for repository scaffolding (see root README.md, "POC Status"). ``Orchestrator`` encodes
the control flow so the pipeline's shape is reviewable/testable before any LLM-backed logic exists, and so
that swapping in real implementations later requires no change to this file.
"""

from __future__ import annotations

import abc
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.entities import Document as WikiDocument
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
from llm_yuki.domain.passage_splitter import split_into_natural_paragraphs
from llm_yuki.ports.connector import Connector
from llm_yuki.ports.writer import Writer

_DEFAULT_MAX_WORKERS = 4


@dataclass
class CompiledUpdate:
    """Candidate ``Claim``/``Concept`` pages for one passage — Algorithm 1 line 3's ``U``."""

    claims: list[Claim] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)


class Extractor(abc.ABC):
    """Algorithm 1 lines 1-3: ``SelectPages`` + ``CompileWikiPages`` for one passage (proposal §2.2.1)."""

    @abc.abstractmethod
    def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]:
        """``S ← SelectPages(x, I)``: existing page slugs relevant to this passage.

        ``batch_id`` identifies this call for cost-ledger recording (D19) — it plays no role in the
        selection logic itself.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def compile_wiki_pages(
        self, passage: str, selected: list[str], constraints: list[str], batch_id: int
    ) -> CompiledUpdate:
        """``U ← CompileWikiPages(x, S, C)``: candidate Claim/Concept pages for this passage.

        ``batch_id``: see :meth:`select_pages`.
        """
        raise NotImplementedError


class Merger(abc.ABC):
    """Dedupe/decide final content; does not persist — persistence is the Writer's job (proposal §2.2.2)."""

    @abc.abstractmethod
    def merge(self, update: CompiledUpdate, writer: Writer, batch_id: int) -> CompiledUpdate:
        """Resolve ``is_new`` / merge against existing pages before ``ApplyUpdates``.

        ``batch_id``: see :meth:`Extractor.select_pages` — identifies any LLM-backed merge call (D22 layer 2)
        for cost-ledger recording.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def summarize_document(self, document_slug: str, claim_texts: list[str], writer: Writer, batch_id: int) -> str:
        """Generate ``Document.summary`` via recursive batch-reduce over one document's Claim texts (D21 §1.5).

        The ``Orchestrator`` calls this once per newly-ingested source, after that passage's final Claims are
        known, using their ``claim_text``s. Returns ``""`` when ``claim_texts`` is empty (nothing was
        extracted for this source). ``batch_id``: see :meth:`Extractor.select_pages`.
        """
        raise NotImplementedError


class Validator(abc.ABC):
    """Algorithm 1 lines 4-6: ``StructuralValidate`` + ``ContentValidate`` (proposal §2.2.3, §4.1)."""

    @abc.abstractmethod
    def structural_validate(self, update: CompiledUpdate, selected: list[str], writer: Writer) -> list[ValidationIssue]:
        """``E_s ← StructuralValidate(U, W)``: deterministic checks (dangling links, OKF conformance, ...).

        ``selected`` is this passage's ``SelectPages`` output (Algorithm 1 line 2) — needed to detect
        Unseen Overwrite (proposal §4.1 #4): a candidate touching a page outside that selection.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def content_validate(
        self, update: CompiledUpdate, passage: str, writer: Writer, batch_id: int
    ) -> list[ValidationIssue]:
        """``E_c ← ContentValidate(U, W, A)``: LLM-based checks (unsupported facts, cross-page contradictions).

        ``passage`` is this call's source text (Algorithm 1's source archive ``A``, scoped to the one
        passage this ``update`` was compiled from) — needed for source-grounded verification of Unsupported
        Facts (proposal §4.1 #6). ``batch_id``: see :meth:`Extractor.select_pages`.
        """
        raise NotImplementedError


class Fixer(abc.ABC):
    """Algorithm 1 lines 10 & 15: deterministic auto-fix (every batch) and LLM periodic fix (every N batches)."""

    @abc.abstractmethod
    def code_auto_fix(self, update: CompiledUpdate, structural_issues: list[ValidationIssue]) -> CompiledUpdate:
        """``U ← CodeAutoFix(U, E_s)``: deterministic repair of structural issues, applied immediately."""
        raise NotImplementedError

    @abc.abstractmethod
    def llm_periodic_fix(self, error_book: ErrorBook, writer: Writer, batch_id: int) -> None:
        """``W ← LLMPeriodicFix(W, ℬ)``: LLM-driven repair of content issues, run every N batches (§4.3).

        ``batch_id``: see :meth:`Extractor.select_pages`.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class _Passage:
    """One D11 extraction unit — a natural paragraph — plus enough provenance to route it through D12's
    two phases and anchor its Claims' ``source_ref`` back to a real position in the source (§1.2).
    """

    document_slug: str
    index: int
    text: str


@dataclass(frozen=True)
class _Phase1Result:
    """Phase 1's parallel output for one passage — everything Phase 2 needs, nothing it has to recompute."""

    passage: _Passage
    selected: list[str]
    update: CompiledUpdate


class Orchestrator:
    """Runs Algorithm 1 (proposal ARCHITECTURE.md §3) over one batch of Raw Sources.

    Domain-agnostic by construction: it only calls the interfaces above plus the ``Connector``/``Writer``
    ports — never anything corpus-specific (AGENTS.md §4, proposal README.md D3). Execution follows D12's
    two-phase strategy: Phase 1 (``SelectPages``/``CompileWikiPages``) runs in parallel across every passage
    in the batch, each comparing against the same read-only ``Writer`` snapshot (nothing is written until
    Phase 2 starts, so "current Writer state" and "the Phase 1 snapshot" are the same thing here); Phase 2
    (``Merger``/``Validator``/``ErrorBook``/``Fixer``/``ApplyUpdates``) then runs sequentially, one passage
    at a time, to avoid concurrent write conflicts (D12).
    """

    def __init__(
        self,
        connector: Connector,
        writer: Writer,
        extractor: Extractor,
        merger: Merger,
        validator: Validator,
        fixer: Fixer,
        error_book: ErrorBook,
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        self._connector = connector
        self._writer = writer
        self._extractor = extractor
        self._merger = merger
        self._validator = validator
        self._fixer = fixer
        self._error_book = error_book
        self._max_workers = max_workers

    def run_batch(self, batch_id: int) -> None:
        """Algorithm 1, lines 1-17, over every passage of every source in the Connector's current batch."""
        constraints = self._error_book.active_constraints()
        passages = self._collect_passages()
        document_slugs = _unique_in_order(passage.document_slug for passage in passages)

        phase1_results = self._run_phase1(passages, constraints, batch_id)

        # Documents are created only now — right before Phase 2's first write — not any earlier: they don't
        # yet have a summary or any backlinks, so surfacing them to Phase 1's SelectPages as an "existing
        # page" would just spend an LLM call for a page with nothing useful to say (see _describe_page).
        self._ensure_document_pages(document_slugs)

        for result in phase1_results:
            self._run_phase2(result, batch_id)

        self._finalize_document_summaries(document_slugs, batch_id)

        if self._error_book.periodic_fix_due(batch_id):
            self._fixer.llm_periodic_fix(self._error_book, self._writer, batch_id)
            self._error_book.verify_and_close(self._writer, batch_id)

    def _collect_passages(self) -> list[_Passage]:
        """D11: split every source's text into natural paragraphs — the actual extraction units."""
        passages: list[_Passage] = []
        for ref in self._connector.list_sources():
            document = self._connector.read_source(ref)
            for index, text in enumerate(split_into_natural_paragraphs(document.text)):
                passages.append(_Passage(document_slug=ref.id, index=index, text=text))
        return passages

    def _ensure_document_pages(self, document_slugs: list[str]) -> None:
        """D21: create every source's ``Document`` navigation page up front, before any Claim is written.

        Must happen before Phase 2 starts writing (not per-passage, since one document's passages are now
        interleaved with other documents' across the whole batch) so ``Writer.write_claim``'s backlink
        maintenance can attach ``produced_claims``/``produced_concepts`` regardless of processing order.
        ``summary`` starts empty and is filled in by :meth:`_finalize_document_summaries` once every passage
        of that document has gone through Phase 2. This POC assumes each Raw Source is only ever ingested
        once (D21's explicit exclusion), so an already-existing Document page is left untouched.
        """
        for slug in document_slugs:
            if self._writer.read_document(slug) is not None:
                continue
            self._writer.write_document(
                WikiDocument(
                    slug=slug,
                    document_title=slug,
                    source_path=slug,
                    ingested_at=datetime.now(UTC).date().isoformat(),
                    summary="",
                )
            )

    def _run_phase1(
        self, passages: list[_Passage], constraints: list[str], batch_id: int
    ) -> list[_Phase1Result]:
        """D12 Phase 1: ``SelectPages``/``CompileWikiPages`` in parallel across every passage in the batch."""
        if not passages:
            return []
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(passages))) as pool:
            futures = [pool.submit(self._extract_one, passage, constraints, batch_id) for passage in passages]
            return [future.result() for future in futures]

    def _extract_one(self, passage: _Passage, constraints: list[str], batch_id: int) -> _Phase1Result:
        """Algorithm 1 lines 1-3 for one passage — the unit of work Phase 1 parallelizes over."""
        selected = self._extractor.select_pages(passage.text, self._writer, batch_id)
        update = self._extractor.compile_wiki_pages(passage.text, selected, constraints, batch_id)
        return _Phase1Result(passage=passage, selected=selected, update=update)

    def _run_phase2(self, result: _Phase1Result, batch_id: int) -> None:
        """D12 Phase 2 for one passage: merge/validate/fix/write, sequential to avoid concurrent write races."""
        passage = result.passage
        update = self._merger.merge(result.update, self._writer, batch_id)

        structural_issues = self._validator.structural_validate(update, result.selected, self._writer)
        content_issues = self._validator.content_validate(update, passage.text, self._writer, batch_id)
        issues = structural_issues + content_issues

        if issues:
            self._error_book.update_error_book(issues, batch_id, self._writer)
            if structural_issues:
                update = self._fixer.code_auto_fix(update, structural_issues)

        claims = _anchor_source_refs(update.claims, passage.document_slug, passage.index)
        self._apply_updates(CompiledUpdate(claims=claims, concepts=update.concepts))

    def _finalize_document_summaries(self, document_slugs: list[str], batch_id: int) -> None:
        """D21 §1.5: once every passage of a document has gone through Phase 2, (re)generate its summary.

        Reads the now-complete ``produced_claims`` backlink (maintained incrementally by ``Writer`` across
        every passage of this document, regardless of how many there were) rather than tracking claims
        in-memory during Phase 2 — the persisted backlink is the same source of truth the rest of the
        pipeline already treats as authoritative.
        """
        for slug in document_slugs:
            document = self._writer.read_document(slug)
            if document is None:
                continue
            claim_texts = [
                claim.claim_text
                for claim_slug in document.produced_claims
                if (claim := self._writer.read_claim(claim_slug)) is not None
            ]
            summary = self._merger.summarize_document(slug, claim_texts, self._writer, batch_id)
            self._writer.write_document(document.model_copy(update={"summary": summary}))

    def _apply_updates(self, update: CompiledUpdate) -> None:
        """Algorithm 1 line 12: ``W ← ApplyUpdates(W, U)``.

        Concepts before claims: ``Writer.write_claim``'s backlink maintenance (proposal ARCHITECTURE.md
        §2.3.2) looks up each ``related_concepts`` target and skips it if that Concept isn't persisted yet
        — writing claims first would silently drop the backlink for any Concept created in this same batch.
        """
        for concept in update.concepts:
            self._writer.write_concept(concept)
        for claim in update.claims:
            self._writer.write_claim(claim)


def _unique_in_order(values: Iterable[str]) -> list[str]:
    """De-duplicate while preserving first-seen order (``dict.fromkeys`` trick, no external dependency)."""
    return list(dict.fromkeys(values))


def _anchor_source_refs(claims: list[Claim], document_slug: str, passage_index: int) -> list[Claim]:
    """Force every Claim's ``source_ref`` to ``<document_slug>#p<passage_index>`` (D17/D18/D22 "deterministic
    overrides LLM"): the Extractor's LLM call has no reliable way to know the real source id or this
    passage's actual position, but the Orchestrator does — and ``Document`` backlink maintenance (``Writer``)
    depends on the document-id segment matching exactly. Runs after structural validation/``CodeAutoFix``, so
    malformed-ref lint signals are still computed on the LLM's original value first.
    """
    new_ref = f"{document_slug}#p{passage_index}"
    return [
        claim if claim.source_ref == new_ref else claim.model_copy(update={"source_ref": new_ref})
        for claim in claims
    ]
