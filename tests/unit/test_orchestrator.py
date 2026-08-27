"""Unit test for Orchestrator's control flow, using in-memory fakes — no filesystem access.

Demonstrates the point of the Ports & Adapters split (root ARCHITECTURE.md §3): the compile loop is fully
testable without a real Connector/Writer.
"""

from __future__ import annotations

import pytest

from llm_yuki.domain.entities import Claim, Concept, Document
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
from llm_yuki.domain.pipeline import CompiledUpdate, Extractor, Fixer, Merger, Orchestrator, Validator
from llm_yuki.ports.connector import Connector, SourceRef
from llm_yuki.ports.connector import Document as SourceDocument
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.unit


class _FakeConnector(Connector):
    def __init__(self, documents: dict[str, str]) -> None:
        self._documents = documents

    def list_sources(self) -> list[SourceRef]:
        return [SourceRef(id=doc_id) for doc_id in self._documents]

    def read_source(self, ref: SourceRef) -> SourceDocument:
        return SourceDocument(ref=ref, text=self._documents[ref.id])


class _FakeWriter(Writer):
    def __init__(self) -> None:
        self.written_claims: list[Claim] = []
        self.written_concepts: list[Concept] = []
        self.written_documents: list[Document] = []

    def write_claim(self, claim: Claim) -> None:
        self.written_claims.append(claim)

    def write_concept(self, concept: Concept) -> None:
        self.written_concepts.append(concept)

    def write_document(self, document: Document) -> None:
        self.written_documents.append(document)

    def read_claim(self, slug: str) -> Claim | None:
        return next((c for c in self.written_claims if c.slug == slug), None)

    def read_concept(self, slug: str) -> Concept | None:
        return next((c for c in self.written_concepts if c.slug == slug), None)

    def read_document(self, slug: str) -> Document | None:
        return next((d for d in self.written_documents if d.slug == slug), None)

    def list_pages(self) -> list[str]:
        return (
            [c.slug for c in self.written_claims]
            + [c.slug for c in self.written_concepts]
            + [d.slug for d in self.written_documents]
        )


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

    def summarize_document(self, document_slug: str, claim_texts: list[str], writer: Writer, batch_id: int) -> str:
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
    assert {d.slug for d in writer.written_documents} == {"doc-a", "doc-b"}
    # source_ref is anchored to the real source id, overriding _FakeExtractor's hardcoded "doc-1" (D17/D18/D22
    # "deterministic overrides LLM" — see Orchestrator._anchor_source_refs).
    assert {c.source_ref for c in writer.written_claims} == {"doc-a", "doc-b"}
