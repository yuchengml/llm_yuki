"""Unit tests for DefaultMerger — in-memory fake Writer, no filesystem access."""

from __future__ import annotations

import pytest

from llm_yuki.adapters.merging.default_merger import DefaultMerger
from llm_yuki.domain.entities import Claim, Concept, ContradictionRef, Document
from llm_yuki.domain.pipeline import CompiledUpdate
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.unit


class _FakeWriter(Writer):
    def __init__(self) -> None:
        self.claims: dict[str, Claim] = {}
        self.concepts: dict[str, Concept] = {}
        self.documents: dict[str, Document] = {}
        self.log_events: list[str] = []

    def write_claim(self, claim: Claim) -> None:
        self.claims[claim.slug] = claim

    def write_concept(self, concept: Concept) -> None:
        self.concepts[concept.slug] = concept

    def write_document(self, document: Document) -> None:
        self.documents[document.slug] = document

    def read_claim(self, slug: str) -> Claim | None:
        return self.claims.get(slug)

    def read_concept(self, slug: str) -> Concept | None:
        return self.concepts.get(slug)

    def read_document(self, slug: str) -> Document | None:
        return self.documents.get(slug)

    def list_pages(self) -> list[str]:
        return [*self.claims, *self.concepts, *self.documents]

    def append_log(self, event: str) -> None:
        self.log_events.append(event)


def _claim(**overrides: object) -> Claim:
    defaults: dict[str, object] = {
        "slug": "claim-1",
        "claim_text": "Water boils at 100C.",
        "source_ref": "doc-1#p1",
        "confidence": 0.7,
        "provenance_state": "extracted",
    }
    defaults.update(overrides)
    return Claim.model_validate(defaults)


def test_merge_passes_through_brand_new_candidates_unchanged() -> None:
    update = CompiledUpdate(
        claims=[_claim()], concepts=[Concept(slug="water", concept_title="Water", summary="A compound.")]
    )

    merged = DefaultMerger().merge(update, _FakeWriter(), batch_id=1)

    assert merged.claims == update.claims
    assert merged.concepts == update.concepts


def test_merge_dedupes_two_candidates_with_the_same_slug_in_one_batch() -> None:
    update = CompiledUpdate(
        claims=[
            _claim(confidence=0.5, related_concepts=["water"]),
            _claim(confidence=0.9, related_concepts=["ice"]),
        ]
    )

    merged = DefaultMerger().merge(update, _FakeWriter(), batch_id=1)

    assert len(merged.claims) == 1
    assert merged.claims[0].confidence == 0.9  # higher confidence wins
    assert merged.claims[0].related_concepts == ["water", "ice"]  # union
    assert merged.claims[0].provenance_state == "merged"


def test_merge_claim_against_existing_page_unions_related_concepts() -> None:
    writer = _FakeWriter()
    writer.write_claim(_claim(related_concepts=["water"]))
    update = CompiledUpdate(claims=[_claim(related_concepts=["ice"], confidence=0.9)])

    merged = DefaultMerger().merge(update, writer, batch_id=1)

    assert merged.claims[0].related_concepts == ["water", "ice"]


def test_merge_claim_unions_contradicted_by_deduped_by_slug() -> None:
    writer = _FakeWriter()
    writer.write_claim(_claim(contradicted_by=[ContradictionRef(slug="claim-x", reason="first reason")]))
    update = CompiledUpdate(
        claims=[
            _claim(
                contradicted_by=[
                    ContradictionRef(slug="claim-x", reason="ignored, duplicate slug"),
                    ContradictionRef(slug="claim-y", reason="new conflict"),
                ]
            )
        ]
    )

    merged = DefaultMerger().merge(update, writer, batch_id=1)

    assert [ref.slug for ref in merged.claims[0].contradicted_by] == ["claim-x", "claim-y"]
    assert merged.claims[0].contradicted_by[0].reason == "first reason"


def test_merge_concept_against_existing_page_unions_tags_and_keeps_new_summary() -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="old summary", tags=["chem"]))
    update = CompiledUpdate(
        concepts=[Concept(slug="water", concept_title="Water", summary="new summary", tags=["liquid"])]
    )

    merged = DefaultMerger().merge(update, writer, batch_id=1)

    assert merged.concepts[0].summary == "new summary"
    assert merged.concepts[0].tags == ["chem", "liquid"]


def test_merge_concept_keeps_existing_summary_when_new_summary_is_empty() -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="old summary"))
    update = CompiledUpdate(concepts=[Concept(slug="water", concept_title="Water", summary="")])

    merged = DefaultMerger().merge(update, writer, batch_id=1)

    assert merged.concepts[0].summary == "old summary"


def test_merge_concept_locks_concept_title_against_existing_page() -> None:
    """D22 layer 3: concept_title always keeps the existing value, regardless of what the new candidate says."""
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="old summary"))
    update = CompiledUpdate(concepts=[Concept(slug="water", concept_title="H2O", summary="old summary")])

    merged = DefaultMerger().merge(update, writer, batch_id=1)

    assert merged.concepts[0].concept_title == "Water"


def test_merge_concept_without_llm_client_skips_layer_2_even_on_real_conflict() -> None:
    """Without an llm_client, D22 layer 2 is a no-op — behaves exactly as before D22 (layer 1's new-or-old)."""
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="Water is a liquid compound."))
    update = CompiledUpdate(
        concepts=[Concept(slug="water", concept_title="Water", summary="Water freezes at 0 degrees Celsius.")]
    )

    merged = DefaultMerger().merge(update, writer, batch_id=1)

    assert merged.concepts[0].summary == "Water freezes at 0 degrees Celsius."


def test_summarize_document_with_no_claims_returns_empty_string_even_without_llm_client() -> None:
    """No claims means nothing was extracted for this source — never worth an LLM call either way."""
    summary = DefaultMerger().summarize_document("doc-1", [], _FakeWriter(), batch_id=1)

    assert summary == ""


def test_summarize_document_without_llm_client_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError):
        DefaultMerger().summarize_document("doc-1", ["Water boils at 100C."], _FakeWriter(), batch_id=1)
