"""Integration tests for YamlErrorBookStore — exercises the real filesystem."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_yuki.adapters.state.error_book_store import YamlErrorBookStore
from llm_yuki.domain.entities import Claim, Concept, Document
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.integration


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


def test_load_returns_empty_error_book_when_no_file_yet(tmp_path: Path) -> None:
    store = YamlErrorBookStore(tmp_path)

    book = store.load()

    assert book.entries == []


def test_save_then_load_round_trips_entries(tmp_path: Path) -> None:
    store = YamlErrorBookStore(tmp_path)
    book = ErrorBook()
    book.update_error_book(
        [ValidationIssue(error_type="dangling_links", phenomenon="missing page", affected_refs=["water"])],
        batch_id=1,
        writer=_FakeWriter(),
    )

    store.save(book)
    reloaded = store.load()

    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].error_type == "dangling_links"
    assert reloaded.entries[0].affected_refs == ["water"]
    assert reloaded.entries[0].discovered_at_batch == 1


def test_save_writes_under_pipeline_state_root(tmp_path: Path) -> None:
    store = YamlErrorBookStore(tmp_path / "pipeline-state")
    store.save(ErrorBook())

    assert (tmp_path / "pipeline-state" / "error_book.yaml").exists()
