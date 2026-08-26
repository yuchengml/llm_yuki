"""Unit tests for DefaultValidator.structural_validate — in-memory fake Writer, no filesystem access."""

from __future__ import annotations

import pytest

from llm_yuki.adapters.validation.default_validator import DefaultValidator
from llm_yuki.domain.entities import Claim, Concept, ContradictionRef
from llm_yuki.domain.pipeline import CompiledUpdate
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.unit


class _FakeWriter(Writer):
    def __init__(self) -> None:
        self.claims: dict[str, Claim] = {}
        self.concepts: dict[str, Concept] = {}

    def write_claim(self, claim: Claim) -> None:
        self.claims[claim.slug] = claim

    def write_concept(self, concept: Concept) -> None:
        self.concepts[concept.slug] = concept

    def read_claim(self, slug: str) -> Claim | None:
        return self.claims.get(slug)

    def read_concept(self, slug: str) -> Concept | None:
        return self.concepts.get(slug)

    def list_pages(self) -> list[str]:
        return [*self.claims, *self.concepts]


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


def test_clean_update_has_no_issues() -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A compound."))
    update = CompiledUpdate(claims=[_claim(related_concepts=["water"])], concepts=[])

    issues = DefaultValidator().structural_validate(update, selected=["water"], writer=writer)

    assert issues == []


def test_dangling_related_concept_is_flagged() -> None:
    update = CompiledUpdate(claims=[_claim(related_concepts=["missing"])])

    issues = DefaultValidator().structural_validate(update, selected=[], writer=_FakeWriter())

    assert len(issues) == 1
    assert issues[0].error_type == "dangling_links"
    assert issues[0].affected_refs == ["missing"]


def test_related_concept_resolved_within_same_update_is_not_dangling() -> None:
    update = CompiledUpdate(
        claims=[_claim(related_concepts=["water"])],
        concepts=[Concept(slug="water", concept_title="Water", summary="A compound.")],
    )

    issues = DefaultValidator().structural_validate(update, selected=[], writer=_FakeWriter())

    assert issues == []


def test_dangling_contradicted_by_is_flagged() -> None:
    update = CompiledUpdate(claims=[_claim(contradicted_by=[ContradictionRef(slug="ghost", reason="x")])])

    issues = DefaultValidator().structural_validate(update, selected=[], writer=_FakeWriter())

    assert any(i.error_type == "dangling_links" and i.affected_refs == ["ghost"] for i in issues)


def test_incomplete_claim_missing_text_is_flagged() -> None:
    update = CompiledUpdate(claims=[_claim(claim_text="  ")])

    issues = DefaultValidator().structural_validate(update, selected=[], writer=_FakeWriter())

    assert any(i.error_type == "incomplete_pages" for i in issues)


def test_incomplete_concept_missing_summary_is_flagged() -> None:
    update = CompiledUpdate(concepts=[Concept(slug="water", concept_title="Water", summary="")])

    issues = DefaultValidator().structural_validate(update, selected=[], writer=_FakeWriter())

    assert any(i.error_type == "incomplete_pages" for i in issues)


def test_malformed_source_ref_is_flagged() -> None:
    update = CompiledUpdate(claims=[_claim(source_ref="not a valid ref!!")])

    issues = DefaultValidator().structural_validate(update, selected=[], writer=_FakeWriter())

    assert any(i.error_type == "malformed_refs" for i in issues)


def test_unseen_overwrite_flags_existing_page_outside_selection() -> None:
    writer = _FakeWriter()
    writer.write_claim(_claim())
    update = CompiledUpdate(claims=[_claim(confidence=0.9)])

    issues = DefaultValidator().structural_validate(update, selected=["other-slug"], writer=writer)

    assert any(i.error_type == "unseen_overwrite" and i.affected_refs == ["claim-1"] for i in issues)


def test_new_page_not_flagged_as_unseen_overwrite() -> None:
    update = CompiledUpdate(claims=[_claim()])

    issues = DefaultValidator().structural_validate(update, selected=[], writer=_FakeWriter())

    assert not any(i.error_type == "unseen_overwrite" for i in issues)


def test_selected_existing_page_not_flagged_as_unseen_overwrite() -> None:
    writer = _FakeWriter()
    writer.write_claim(_claim())
    update = CompiledUpdate(claims=[_claim(confidence=0.9)])

    issues = DefaultValidator().structural_validate(update, selected=["claim-1"], writer=writer)

    assert not any(i.error_type == "unseen_overwrite" for i in issues)


def test_same_slug_as_claim_and_concept_in_one_update_is_index_inconsistency() -> None:
    update = CompiledUpdate(
        claims=[_claim(slug="dupe")], concepts=[Concept(slug="dupe", concept_title="Dupe", summary="x")]
    )

    issues = DefaultValidator().structural_validate(update, selected=[], writer=_FakeWriter())

    assert any(i.error_type == "index_inconsistency" and i.affected_refs == ["dupe"] for i in issues)


def test_claim_slug_colliding_with_existing_concept_is_index_inconsistency() -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="dupe", concept_title="Dupe", summary="x"))
    update = CompiledUpdate(claims=[_claim(slug="dupe")])

    issues = DefaultValidator().structural_validate(update, selected=[], writer=writer)

    assert any(i.error_type == "index_inconsistency" for i in issues)


def test_content_validate_without_llm_client_raises_runtime_error() -> None:
    update = CompiledUpdate()

    with pytest.raises(RuntimeError):
        DefaultValidator().content_validate(update, _FakeWriter(), batch_id=1)
