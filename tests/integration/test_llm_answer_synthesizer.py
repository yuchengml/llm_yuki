"""Integration tests for LLMAnswerSynthesizer — fake LLM client (no network), real cost ledger filesystem writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.answer_synthesizer import LLMAnswerSynthesizer
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.domain.query import PageRecord

pytestmark = pytest.mark.integration


class _FakeLLMClient:
    def __init__(self, content: str, tokens_in: int = 5, tokens_out: int = 7) -> None:
        self._content = content
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, response_format_json: bool = False) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(content=self._content, tokens_in=self._tokens_in, tokens_out=self._tokens_out)


def _ledger(tmp_path: Path) -> JsonlCostLedger:
    return JsonlCostLedger(tmp_path)


def test_synthesize_returns_default_message_without_calling_llm_when_no_pages(tmp_path: Path) -> None:
    client = _FakeLLMClient(content="{}")
    synthesizer = LLMAnswerSynthesizer(client, _ledger(tmp_path))  # type: ignore[arg-type]

    result = synthesizer.synthesize("What is water?", [], batch_id=1)

    assert result.cited_slugs == []
    assert client.calls == []


def test_synthesize_parses_answer_and_filters_hallucinated_citations(tmp_path: Path) -> None:
    pages = [PageRecord(slug="water", page_type="concept", title="Water", content="Water is H2O.")]
    payload = {"answer": "Water is H2O.", "cited_slugs": ["water", "hallucinated-slug"]}
    client = _FakeLLMClient(content=json.dumps(payload))
    ledger = _ledger(tmp_path)
    synthesizer = LLMAnswerSynthesizer(client, ledger)  # type: ignore[arg-type]

    result = synthesizer.synthesize("What is water?", pages, batch_id=3)

    assert result.answer == "Water is H2O."
    assert result.cited_slugs == ["water"]  # hallucinated slug filtered out, same precedent as SelectPages
    events = ledger.read_events()
    assert len(events) == 1
    assert events[0].stage == "AnswerSynthesizer.Synthesize"
    assert events[0].batch_id == 3


def test_synthesize_raises_on_non_string_answer(tmp_path: Path) -> None:
    pages = [PageRecord(slug="water", page_type="concept", title="Water")]
    client = _FakeLLMClient(content=json.dumps({"answer": 123, "cited_slugs": []}))
    synthesizer = LLMAnswerSynthesizer(client, _ledger(tmp_path))  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        synthesizer.synthesize("q", pages, batch_id=1)


def test_synthesize_raises_on_non_list_cited_slugs(tmp_path: Path) -> None:
    pages = [PageRecord(slug="water", page_type="concept", title="Water")]
    client = _FakeLLMClient(content=json.dumps({"answer": "x", "cited_slugs": "not-a-list"}))
    synthesizer = LLMAnswerSynthesizer(client, _ledger(tmp_path))  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        synthesizer.synthesize("q", pages, batch_id=1)


def test_synthesize_raises_on_malformed_json(tmp_path: Path) -> None:
    pages = [PageRecord(slug="water", page_type="concept", title="Water")]
    client = _FakeLLMClient(content="not json at all")
    synthesizer = LLMAnswerSynthesizer(client, _ledger(tmp_path))  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        synthesizer.synthesize("q", pages, batch_id=1)


def test_synthesize_prompt_includes_question_and_page_content(tmp_path: Path) -> None:
    pages = [PageRecord(slug="water", page_type="concept", title="Water", content="Water is H2O.")]
    client = _FakeLLMClient(content=json.dumps({"answer": "x", "cited_slugs": []}))
    synthesizer = LLMAnswerSynthesizer(client, _ledger(tmp_path))  # type: ignore[arg-type]

    synthesizer.synthesize("What is water?", pages, batch_id=1)

    user_message = client.calls[0][1]["content"]
    assert "What is water?" in user_message
    assert "Water is H2O." in user_message
    assert "water" in user_message
