"""Orchestrator and its sub-steps — Algorithm 1 from the LLM-Wiki paper (proposal ARCHITECTURE.md §3).

``Extractor``/``Merger``/``Validator``/``Fixer`` are interface stubs: their real implementations call an LLM
and are out of scope for repository scaffolding (see root README.md, "POC Status"). ``Orchestrator`` encodes
the control flow so the pipeline's shape is reviewable/testable before any LLM-backed logic exists, and so
that swapping in real implementations later requires no change to this file.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import UTC, datetime

from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.entities import Document as WikiDocument
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
from llm_yuki.ports.connector import Connector, Document
from llm_yuki.ports.writer import Writer


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


class Orchestrator:
    """Runs Algorithm 1 (proposal ARCHITECTURE.md §3) over one batch of Raw Sources.

    Domain-agnostic by construction: it only calls the interfaces above plus the ``Connector``/``Writer``
    ports — never anything corpus-specific (AGENTS.md §4, proposal README.md D3).
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
    ) -> None:
        self._connector = connector
        self._writer = writer
        self._extractor = extractor
        self._merger = merger
        self._validator = validator
        self._fixer = fixer
        self._error_book = error_book

    def run_batch(self, batch_id: int) -> None:
        """Algorithm 1, lines 1-17, for every source in the Connector's current batch."""
        constraints = self._error_book.active_constraints()

        for ref in self._connector.list_sources():
            document = self._connector.read_source(ref)
            self._compile_passage(document, constraints, batch_id)

        if self._error_book.periodic_fix_due(batch_id):
            self._fixer.llm_periodic_fix(self._error_book, self._writer, batch_id)
            self._error_book.verify_and_close(self._writer, batch_id)

    def _compile_passage(self, document: Document, constraints: list[str], batch_id: int) -> None:
        """Algorithm 1 lines 1-12 for a single source passage."""
        selected = self._extractor.select_pages(document.text, self._writer, batch_id)
        update = self._extractor.compile_wiki_pages(document.text, selected, constraints, batch_id)
        update = self._merger.merge(update, self._writer, batch_id)

        structural_issues = self._validator.structural_validate(update, selected, self._writer)
        content_issues = self._validator.content_validate(update, document.text, self._writer, batch_id)
        issues = structural_issues + content_issues

        if issues:
            self._error_book.update_error_book(issues, batch_id, self._writer)
            if structural_issues:
                update = self._fixer.code_auto_fix(update, structural_issues)

        update = CompiledUpdate(claims=_anchor_source_refs(update.claims, document.ref.id), concepts=update.concepts)
        self._ensure_document_page(document.ref.id, update.claims, batch_id)
        self._apply_updates(update)

    def _ensure_document_page(self, document_slug: str, claims: list[Claim], batch_id: int) -> None:
        """D21: create this source's ``Document`` navigation page, if it doesn't exist yet.

        Written *before* ``_apply_updates`` so ``Writer.write_claim``'s backlink maintenance (D21, same
        mechanism as D18's ``Concept.key_facts``) can attach ``produced_claims``/``produced_concepts`` to it
        immediately. This POC assumes each Raw Source is only ever ingested once (D21's explicit exclusion —
        no re-ingest/incremental-update scenario), so an existing Document page is left untouched.
        """
        if self._writer.read_document(document_slug) is not None:
            return

        claim_texts = [claim.claim_text for claim in claims]
        summary = self._merger.summarize_document(document_slug, claim_texts, self._writer, batch_id)
        self._writer.write_document(
            WikiDocument(
                slug=document_slug,
                document_title=document_slug,
                source_path=document_slug,
                ingested_at=datetime.now(UTC).date().isoformat(),
                summary=summary,
            )
        )

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


def _anchor_source_refs(claims: list[Claim], document_slug: str) -> list[Claim]:
    """Force every Claim's ``source_ref`` document-id segment to the real source id (D17/D18/D22 "deterministic
    overrides LLM"): the Extractor's LLM call may invent/misformat this id, but the Orchestrator already knows
    the ground truth, and ``Document`` backlink maintenance (``Writer``) depends on the two matching exactly.
    Runs after structural validation/``CodeAutoFix``, so malformed-ref lint signals are computed on the LLM's
    original value first — this only touches the leading id, never the ``#locator`` suffix.
    """
    anchored = []
    for claim in claims:
        _, _, locator = claim.source_ref.partition("#")
        new_ref = f"{document_slug}#{locator}" if locator else document_slug
        anchored.append(claim if new_ref == claim.source_ref else claim.model_copy(update={"source_ref": new_ref}))
    return anchored
