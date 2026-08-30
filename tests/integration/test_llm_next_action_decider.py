"""Integration tests for LLMActionDecider — fake LLM client (no network), real cost ledger filesystem writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.adapters.llm.next_action_decider import LLMActionDecider
from llm_yuki.domain.query import EvidenceItem, PageRecord, SearchHit

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


def test_decide_returns_wiki_search_action(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"tool": "wiki_search", "query": "water boiling point"}))
    ledger = _ledger(tmp_path)
    decider = LLMActionDecider(client, ledger, batch_id=2)  # type: ignore[arg-type]

    action = decider.decide("What temperature does water boil at?", [])

    assert action.tool == "wiki_search"
    assert action.query == "water boiling point"
    events = ledger.read_events()
    assert events[0].stage == "NextActionDecider.Decide"
    assert events[0].batch_id == 2


def test_decide_returns_wiki_read_action(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"tool": "wiki_read", "slugs": ["water", "water-boils"]}))
    decider = LLMActionDecider(client, _ledger(tmp_path), batch_id=1)  # type: ignore[arg-type]

    action = decider.decide("q", [])

    assert action.tool == "wiki_read"
    assert action.slugs == ["water", "water-boils"]


def test_decide_returns_stop_action(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"tool": "stop"}))
    decider = LLMActionDecider(client, _ledger(tmp_path), batch_id=1)  # type: ignore[arg-type]

    assert decider.decide("q", []).tool == "stop"


def test_decide_raises_on_unknown_tool(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"tool": "delete_everything"}))
    decider = LLMActionDecider(client, _ledger(tmp_path), batch_id=1)  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        decider.decide("q", [])


def test_decide_raises_on_empty_search_query(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"tool": "wiki_search", "query": "  "}))
    decider = LLMActionDecider(client, _ledger(tmp_path), batch_id=1)  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        decider.decide("q", [])


def test_decide_raises_on_malformed_json(tmp_path: Path) -> None:
    client = _FakeLLMClient(content="not json")
    decider = LLMActionDecider(client, _ledger(tmp_path), batch_id=1)  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        decider.decide("q", [])


def test_decide_prompt_includes_prior_evidence(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"tool": "stop"}))
    decider = LLMActionDecider(client, _ledger(tmp_path), batch_id=1)  # type: ignore[arg-type]
    evidence = [
        EvidenceItem(kind="search", hits=[SearchHit(slug="water", score=0.5, matched_field="structured")]),
        EvidenceItem(kind="read", pages=[PageRecord(slug="water", page_type="concept", title="Water", content="H2O")]),
    ]

    decider.decide("What is water?", evidence)

    user_message = client.calls[0][1]["content"]
    assert "What is water?" in user_message
    assert "water" in user_message
    assert "wiki_search" in user_message
    assert "wiki_read" in user_message
