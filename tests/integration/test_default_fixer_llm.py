"""Integration tests for DefaultFixer.llm_periodic_fix — fake LLM client, real cost ledger filesystem writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.fixing.default_fixer import DefaultFixer
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.integration


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


class _FakeLLMClient:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, response_format_json: bool = False) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(content=self._content, tokens_in=8, tokens_out=12)


def _book_with_open_content_issue(slug: str = "claim-1") -> ErrorBook:
    book = ErrorBook()
    book.update_error_book(
        [ValidationIssue(error_type="unsupported_facts", phenomenon="not grounded", affected_refs=[slug])],
        batch_id=1,
    )
    return book


def test_no_open_content_entries_does_not_call_llm(tmp_path: Path) -> None:
    client = _FakeLLMClient(content="{}")
    fixer = DefaultFixer(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]

    fixer.llm_periodic_fix(ErrorBook(), _FakeWriter(), batch_id=1)

    assert client.calls == []


def test_structural_only_entries_are_ignored(tmp_path: Path) -> None:
    book = ErrorBook()
    book.update_error_book(
        [ValidationIssue(error_type="dangling_links", phenomenon="x", affected_refs=["a"])], batch_id=1
    )
    client = _FakeLLMClient(content="{}")
    fixer = DefaultFixer(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]

    fixer.llm_periodic_fix(book, _FakeWriter(), batch_id=1)

    assert client.calls == []


def test_applies_llm_proposed_claim_fix_and_records_cost(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_claim(
        Claim(
            slug="claim-1", claim_text="wrong text", source_ref="doc-1#p1", confidence=0.5, provenance_state="extracted"
        )
    )
    book = _book_with_open_content_issue("claim-1")
    fixed_payload = {
        "claims": [
            {
                "slug": "claim-1",
                "claim_text": "corrected text",
                "source_ref": "doc-1#p1",
                "confidence": 0.9,
                "provenance_state": "merged",
                "related_concepts": [],
                "contradicted_by": [],
            }
        ],
        "concepts": [],
    }
    client = _FakeLLMClient(content=json.dumps(fixed_payload))
    ledger = JsonlCostLedger(tmp_path)
    fixer = DefaultFixer(client, ledger)  # type: ignore[arg-type]

    fixer.llm_periodic_fix(book, writer, batch_id=7)

    assert writer.read_claim("claim-1").claim_text == "corrected text"  # type: ignore[union-attr]
    events = ledger.read_events()
    assert events[0].stage == "Fixer.LLMPeriodicFix"
    assert events[0].batch_id == 7


def test_does_not_close_entries_itself(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_claim(
        Claim(slug="claim-1", claim_text="x", source_ref="doc-1#p1", confidence=0.5, provenance_state="extracted")
    )
    book = _book_with_open_content_issue("claim-1")
    client = _FakeLLMClient(content=json.dumps({"claims": [], "concepts": []}))
    fixer = DefaultFixer(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]

    fixer.llm_periodic_fix(book, writer, batch_id=1)

    assert book.entries[0].status == "open"


def test_raises_on_malformed_json(tmp_path: Path) -> None:
    book = _book_with_open_content_issue()
    client = _FakeLLMClient(content="not json")
    fixer = DefaultFixer(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        fixer.llm_periodic_fix(book, _FakeWriter(), batch_id=1)


def test_prompt_includes_phenomenon_and_page_content(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="the affected text",
            source_ref="doc-1#p1",
            confidence=0.5,
            provenance_state="extracted",
        )
    )
    book = _book_with_open_content_issue("claim-1")
    client = _FakeLLMClient(content=json.dumps({"claims": [], "concepts": []}))
    fixer = DefaultFixer(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]

    fixer.llm_periodic_fix(book, writer, batch_id=1)

    user_message = client.calls[0][1]["content"]
    assert "not grounded" in user_message
    assert "the affected text" in user_message
