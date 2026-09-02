"""Unit test for Orchestrator's control flow, using in-memory fakes — no filesystem access.

Demonstrates the point of the Ports & Adapters split (root ARCHITECTURE.md §3): the compile loop is fully
testable without a real Connector/Writer.
"""

from __future__ import annotations

import threading
import time

import pytest

from llm_yuki.domain.entities import Claim, Concept, Source
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
from llm_yuki.domain.pipeline import CompiledUpdate, Extractor, Fixer, Merger, Orchestrator, Validator
from llm_yuki.ports.connector import Connector, Document, SourceRef
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.unit


class _FakeConnector(Connector):
    def __init__(self, documents: dict[str, str]) -> None:
        self._documents = documents

    def list_sources(self) -> list[SourceRef]:
        return [SourceRef(id=doc_id) for doc_id in self._documents]

    def read_source(self, ref: SourceRef) -> Document:
        return Document(ref=ref, text=self._documents[ref.id])


class _FakeWriter(Writer):
    def __init__(self) -> None:
        self.written_claims: list[Claim] = []
        self.written_concepts: list[Concept] = []
        self.written_sources: list[Source] = []
        self.log_events: list[str] = []

    def write_claim(self, claim: Claim) -> None:
        self.written_claims.append(claim)

    def write_concept(self, concept: Concept) -> None:
        self.written_concepts.append(concept)

    def write_source(self, source: Source) -> None:
        self.written_sources.append(source)

    def read_claim(self, slug: str) -> Claim | None:
        return next((c for c in self.written_claims if c.slug == slug), None)

    def read_concept(self, slug: str) -> Concept | None:
        return next((c for c in self.written_concepts if c.slug == slug), None)

    def read_source(self, slug: str) -> Source | None:
        return next((s for s in self.written_sources if s.slug == slug), None)

    def list_pages(self) -> list[str]:
        return (
            [c.slug for c in self.written_claims]
            + [c.slug for c in self.written_concepts]
            + [s.slug for s in self.written_sources]
        )

    def append_log(self, event: str) -> None:
        self.log_events.append(event)


class _FakeExtractor(Extractor):
    def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]:
        return []

    def compile_wiki_pages(
        self, passage: str, selected: list[str], constraints: list[str], batch_id: int
    ) -> CompiledUpdate:
        return CompiledUpdate(
            claims=[
                Claim(
                    slug="claim-1",
                    claim_text=passage,
                    source_ref="doc-1",
                    confidence=0.8,
                    provenance_state="extracted",
                )
            ],
            concepts=[Concept(slug="concept-1", concept_title="Concept 1", summary=passage)],
        )


class _PassthroughMerger(Merger):
    def merge(self, update: CompiledUpdate, writer: Writer, batch_id: int) -> CompiledUpdate:
        return update

    def summarize_source(self, source_slug: str, claim_texts: list[str], writer: Writer, batch_id: int) -> str:
        return " ".join(claim_texts)


class _NoopValidator(Validator):
    def structural_validate(self, update: CompiledUpdate, selected: list[str], writer: Writer) -> list[ValidationIssue]:
        return []

    def content_validate(
        self, update: CompiledUpdate, passage: str, writer: Writer, batch_id: int
    ) -> list[ValidationIssue]:
        return []


class _NoopFixer(Fixer):
    def code_auto_fix(self, update: CompiledUpdate, structural_issues: list[ValidationIssue]) -> CompiledUpdate:
        return update

    def llm_periodic_fix(self, error_book: ErrorBook, writer: Writer, batch_id: int) -> None:
        raise AssertionError("should not be called when periodic_fix_due is False")


class _NeverDueErrorBook(ErrorBook):
    def active_constraints(self) -> list[str]:
        return []

    def periodic_fix_due(self, batch_id: int) -> bool:
        return False


def test_run_batch_applies_updates_for_every_source() -> None:
    writer = _FakeWriter()
    orchestrator = Orchestrator(
        connector=_FakeConnector({"doc-a": "hello", "doc-b": "world"}),
        writer=writer,
        extractor=_FakeExtractor(),
        merger=_PassthroughMerger(),
        validator=_NoopValidator(),
        fixer=_NoopFixer(),
        error_book=_NeverDueErrorBook(),
    )

    orchestrator.run_batch(batch_id=1)

    assert len(writer.written_claims) == 2
    assert len(writer.written_concepts) == 2
    assert {c.claim_text for c in writer.written_claims} == {"hello", "world"}
    assert {s.slug for s in writer.written_sources} == {"doc-a", "doc-b"}
    # source_ref is anchored to <source_slug>#p<passage_index>, overriding _FakeExtractor's hardcoded
    # "doc-1" (D17/D18/D22 "deterministic overrides LLM" — see Orchestrator._anchor_source_refs). Each
    # source here is a single natural paragraph (no blank lines), so passage index is always 0.
    assert {c.source_ref for c in writer.written_claims} == {"doc-a#p0", "doc-b#p0"}


class _BarrierExtractor(Extractor):
    """Proves D12 Phase 1 genuinely runs passages concurrently, not just structurally-separated-but-serial:
    ``compile_wiki_pages`` blocks on a 2-party barrier, so a call only returns once a *second* Phase 1 call
    is also in flight. A sequential Orchestrator would deadlock here (and time out) instead of proceeding —
    deterministic pass/fail, no timing assumptions, so this isn't a flaky test."""

    def __init__(self) -> None:
        self._barrier = threading.Barrier(2, timeout=5)

    def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]:
        return []

    def compile_wiki_pages(
        self, passage: str, selected: list[str], constraints: list[str], batch_id: int
    ) -> CompiledUpdate:
        self._barrier.wait()
        return CompiledUpdate()


def test_phase1_runs_passages_from_different_sources_concurrently() -> None:
    orchestrator = Orchestrator(
        connector=_FakeConnector({"doc-a": "hello", "doc-b": "world"}),
        writer=_FakeWriter(),
        extractor=_BarrierExtractor(),
        merger=_PassthroughMerger(),
        validator=_NoopValidator(),
        fixer=_NoopFixer(),
        error_book=_NeverDueErrorBook(),
        max_workers=2,
    )

    orchestrator.run_batch(batch_id=1)  # would raise BrokenBarrierError (timeout) if Phase 1 were sequential


class _PartyBarrierExtractor(Extractor):
    """Like ``_BarrierExtractor`` but for an arbitrary party count — proves exactly ``parties`` Phase 1 calls
    are genuinely in flight together (a timeout means fewer than ``parties`` were running concurrently)."""

    def __init__(self, parties: int) -> None:
        self._barrier = threading.Barrier(parties, timeout=5)

    def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]:
        return []

    def compile_wiki_pages(
        self, passage: str, selected: list[str], constraints: list[str], batch_id: int
    ) -> CompiledUpdate:
        self._barrier.wait()
        return CompiledUpdate()


def test_phase1_runs_one_documents_passages_concurrently_when_worker_pool_exceeds_document_window() -> None:
    """A single open document's passages can still saturate a worker pool larger than the document window:
    with ``max_concurrent_documents=1`` and ``max_workers=3``, this one document's 3 passages must all run
    concurrently (barrier requires all 3 parties) even though only one *document* is ever open at a time."""
    orchestrator = Orchestrator(
        connector=_FakeConnector({"doc-a": "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."}),
        writer=_FakeWriter(),
        extractor=_PartyBarrierExtractor(parties=3),
        merger=_PassthroughMerger(),
        validator=_NoopValidator(),
        fixer=_NoopFixer(),
        error_book=_NeverDueErrorBook(),
        max_workers=3,
        max_concurrent_documents=1,
    )

    orchestrator.run_batch(batch_id=1)  # would time out if the 3 passages of this one open document ran serially


class _ConcurrencyTrackingExtractor(Extractor):
    """Records the max number of Phase 1 calls ever observed in flight at once — used to prove
    ``max_concurrent_documents`` actually bounds how many *documents* are open, not just worker count."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current = 0
        self.max_observed = 0

    def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]:
        return []

    def compile_wiki_pages(
        self, passage: str, selected: list[str], constraints: list[str], batch_id: int
    ) -> CompiledUpdate:
        with self._lock:
            self._current += 1
            self.max_observed = max(self.max_observed, self._current)
        time.sleep(0.05)
        with self._lock:
            self._current -= 1
        return CompiledUpdate()


def test_phase1_never_opens_more_documents_than_max_concurrent_documents() -> None:
    """4 single-passage documents, plenty of workers (4), but only 2 documents allowed open at once: the
    observed concurrency must peak at 2, never reach 4 — proving the document window is enforced
    independently of the (larger) worker pool."""
    extractor = _ConcurrencyTrackingExtractor()
    orchestrator = Orchestrator(
        connector=_FakeConnector({"doc-a": "a", "doc-b": "b", "doc-c": "c", "doc-d": "d"}),
        writer=_FakeWriter(),
        extractor=extractor,
        merger=_PassthroughMerger(),
        validator=_NoopValidator(),
        fixer=_NoopFixer(),
        error_book=_NeverDueErrorBook(),
        max_workers=4,
        max_concurrent_documents=2,
    )

    orchestrator.run_batch(batch_id=1)

    assert extractor.max_observed == 2
