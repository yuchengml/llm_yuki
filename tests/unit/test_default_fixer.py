"""Unit tests for DefaultFixer.code_auto_fix — pure, no I/O."""

from __future__ import annotations

import pytest

from llm_yuki.adapters.fixing.default_fixer import DefaultFixer
from llm_yuki.domain.entities import Claim, Concept, ContradictionRef, Document
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
from llm_yuki.domain.pipeline import CompiledUpdate
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.unit


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


def test_no_issues_leaves_update_unchanged() -> None:
    update = CompiledUpdate(claims=[_claim()])

    fixed = DefaultFixer().code_auto_fix(update, [])

    assert fixed.claims == update.claims


def test_dangling_related_concept_is_stripped() -> None:
    update = CompiledUpdate(claims=[_claim(related_concepts=["water", "missing"])])
    issue = ValidationIssue(error_type="dangling_links", phenomenon="x", affected_refs=["missing"])

    fixed = DefaultFixer().code_auto_fix(update, [issue])

    assert fixed.claims[0].related_concepts == ["water"]


def test_dangling_contradicted_by_is_stripped() -> None:
    update = CompiledUpdate(
        claims=[
            _claim(
                contradicted_by=[ContradictionRef(slug="ghost", reason="x"), ContradictionRef(slug="ok", reason="y")]
            )
        ]
    )
    issue = ValidationIssue(error_type="dangling_links", phenomenon="x", affected_refs=["ghost"])

    fixed = DefaultFixer().code_auto_fix(update, [issue])

    assert [ref.slug for ref in fixed.claims[0].contradicted_by] == ["ok"]


def test_dangling_related_page_on_concept_is_stripped() -> None:
    update = CompiledUpdate(concepts=[Concept(slug="c1", concept_title="C1", summary="x", related_pages=["missing"])])
    issue = ValidationIssue(error_type="dangling_links", phenomenon="x", affected_refs=["missing"])

    fixed = DefaultFixer().code_auto_fix(update, [issue])

    assert fixed.concepts[0].related_pages == []


def test_malformed_ref_with_stray_whitespace_is_sanitized() -> None:
    update = CompiledUpdate(claims=[_claim(source_ref="  doc-1#p1  ")])
    issue = ValidationIssue(error_type="malformed_refs", phenomenon="x", affected_refs=["claim-1"])

    fixed = DefaultFixer().code_auto_fix(update, [issue])

    assert fixed.claims[0].source_ref == "doc-1#p1"


def test_malformed_ref_still_invalid_after_sanitize_is_left_unchanged() -> None:
    update = CompiledUpdate(claims=[_claim(source_ref="doc@1!!")])
    issue = ValidationIssue(error_type="malformed_refs", phenomenon="x", affected_refs=["claim-1"])

    fixed = DefaultFixer().code_auto_fix(update, [issue])

    assert fixed.claims[0].source_ref == "doc@1!!"


def test_unseen_overwrite_drops_the_offending_claim() -> None:
    update = CompiledUpdate(claims=[_claim(), _claim(slug="claim-2")])
    issue = ValidationIssue(error_type="unseen_overwrite", phenomenon="x", affected_refs=["claim-1"])

    fixed = DefaultFixer().code_auto_fix(update, [issue])

    assert [c.slug for c in fixed.claims] == ["claim-2"]


def test_index_inconsistency_drops_the_colliding_slug() -> None:
    update = CompiledUpdate(
        claims=[_claim(slug="dupe")], concepts=[Concept(slug="dupe", concept_title="Dupe", summary="x")]
    )
    issue = ValidationIssue(error_type="index_inconsistency", phenomenon="x", affected_refs=["dupe"])

    fixed = DefaultFixer().code_auto_fix(update, [issue])

    assert fixed.claims == []
    assert fixed.concepts == []


class _FakeWriter(Writer):
    def write_claim(self, claim: Claim) -> None: ...
    def write_concept(self, concept: Concept) -> None: ...
    def write_document(self, document: Document) -> None: ...
    def read_claim(self, slug: str) -> Claim | None:
        return None

    def read_concept(self, slug: str) -> Concept | None:
        return None

    def read_document(self, slug: str) -> Document | None:
        return None

    def list_pages(self) -> list[str]:
        return []

    def append_log(self, event: str) -> None: ...


def test_llm_periodic_fix_without_llm_client_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError):
        DefaultFixer().llm_periodic_fix(ErrorBook(), _FakeWriter(), batch_id=1)
