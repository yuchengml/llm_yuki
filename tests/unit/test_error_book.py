"""Unit tests for domain.error_book.ErrorBook lifecycle — in-memory fakes, no filesystem access."""

from __future__ import annotations

import pytest

from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
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


def _issue(
    error_type: str = "dangling_links",
    phenomenon: str = "link to missing page",
    refs: list[str] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        error_type=error_type,  # type: ignore[arg-type]
        phenomenon=phenomenon,
        affected_refs=refs or ["missing-slug"],
    )


def test_update_error_book_creates_open_entry_with_root_cause_and_constraint() -> None:
    book = ErrorBook()

    entries = book.update_error_book([_issue()], batch_id=1)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.status == "open"
    assert entry.discovered_at_batch == 1
    assert entry.root_cause
    assert entry.constraint_rule
    assert entry.affected_refs == ["missing-slug"]


def test_update_error_book_merges_repeat_occurrence_into_existing_entry() -> None:
    book = ErrorBook()
    book.update_error_book([_issue(refs=["a"])], batch_id=1)

    book.update_error_book([_issue(refs=["b"])], batch_id=2)

    assert len(book.entries) == 1
    assert book.entries[0].affected_refs == ["a", "b"]
    assert book.entries[0].discovered_at_batch == 1  # unchanged: still the original discovery batch


def test_active_constraints_returns_only_open_entries() -> None:
    book = ErrorBook()
    book.update_error_book([_issue()], batch_id=1)
    book.entries[0].status = "closed"

    assert book.active_constraints() == []


def test_active_constraints_returns_open_entry_constraint_text() -> None:
    book = ErrorBook()
    book.update_error_book([_issue()], batch_id=1)

    constraints = book.active_constraints()

    assert len(constraints) == 1
    assert constraints[0] == book.entries[0].constraint_rule


def test_periodic_fix_due_fires_on_cadence() -> None:
    book = ErrorBook(periodic_fix_interval=5)

    assert book.periodic_fix_due(1) is False
    assert book.periodic_fix_due(5) is True


def test_periodic_fix_due_does_not_refire_for_the_same_batch() -> None:
    book = ErrorBook(periodic_fix_interval=5)
    assert book.periodic_fix_due(5) is True

    book.verify_and_close(_FakeWriter(), batch_id=5)  # marks batch 5 as having run periodic fix

    assert book.periodic_fix_due(5) is False


def test_periodic_fix_due_false_when_interval_non_positive() -> None:
    book = ErrorBook(periodic_fix_interval=0)

    assert book.periodic_fix_due(5) is False


def test_verify_and_close_closes_dangling_link_once_target_exists() -> None:
    book = ErrorBook()
    book.update_error_book([_issue(refs=["water"])], batch_id=1)
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A compound."))

    closed = book.verify_and_close(writer, batch_id=2)

    assert len(closed) == 1
    assert closed[0].status == "closed"
    assert closed[0].closed_at_batch == 2


def test_verify_and_close_leaves_entry_open_when_still_unresolved() -> None:
    book = ErrorBook()
    book.update_error_book([_issue(refs=["water"])], batch_id=1)

    closed = book.verify_and_close(_FakeWriter(), batch_id=2)

    assert closed == []
    assert book.entries[0].status == "open"


def test_verify_and_close_leaves_content_type_entries_open() -> None:
    book = ErrorBook()
    book.update_error_book(
        [_issue(error_type="unsupported_facts", phenomenon="no source", refs=["claim-1"])], batch_id=1
    )

    closed = book.verify_and_close(_FakeWriter(), batch_id=2)

    assert closed == []
    assert book.entries[0].status == "open"


def test_verify_and_close_closes_incomplete_page_once_complete() -> None:
    book = ErrorBook()
    book.update_error_book(
        [_issue(error_type="incomplete_pages", phenomenon="missing summary", refs=["water"])], batch_id=1
    )
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A compound."))

    closed = book.verify_and_close(writer, batch_id=2)

    assert len(closed) == 1


def test_verify_and_close_closes_malformed_ref_once_well_formed() -> None:
    book = ErrorBook()
    book.update_error_book([_issue(error_type="malformed_refs", phenomenon="bad ref", refs=["claim-1"])], batch_id=1)
    writer = _FakeWriter()
    writer.write_claim(
        Claim(slug="claim-1", claim_text="x", source_ref="doc-1#p1", confidence=0.5, provenance_state="extracted")
    )

    closed = book.verify_and_close(writer, batch_id=2)

    assert len(closed) == 1
