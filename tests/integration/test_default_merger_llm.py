"""Integration tests for DefaultMerger's D22 layer 2 — fake LLM client (no network), real cost ledger writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.merging.default_merger import DefaultMerger
from llm_yuki.domain.entities import Claim, Concept, Source
from llm_yuki.domain.pipeline import CompiledUpdate
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.integration


class _FakeWriter(Writer):
    def __init__(self) -> None:
        self.claims: dict[str, Claim] = {}
        self.concepts: dict[str, Concept] = {}
        self.sources: dict[str, Source] = {}
        self.log_events: list[str] = []

    def write_claim(self, claim: Claim) -> None:
        self.claims[claim.slug] = claim

    def write_concept(self, concept: Concept) -> None:
        self.concepts[concept.slug] = concept

    def write_source(self, source: Source) -> None:
        self.sources[source.slug] = source

    def read_claim(self, slug: str) -> Claim | None:
        return self.claims.get(slug)

    def read_concept(self, slug: str) -> Concept | None:
        return self.concepts.get(slug)

    def read_source(self, slug: str) -> Source | None:
        return self.sources.get(slug)

    def list_pages(self) -> list[str]:
        return [*self.claims, *self.concepts, *self.sources]

    def append_log(self, event: str) -> None:
        self.log_events.append(event)


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


def test_no_llm_call_when_summaries_agree_or_one_is_empty(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="Water is a compound."))
    update = CompiledUpdate(concepts=[Concept(slug="water", concept_title="Water", summary="")])
    client = _FakeLLMClient(content="should not be called")
    ledger = _ledger(tmp_path)

    merged = DefaultMerger(client, ledger).merge(update, writer, batch_id=1)  # type: ignore[arg-type]

    assert merged.concepts[0].summary == "Water is a compound."
    assert client.calls == []
    assert ledger.read_events() == []


def test_real_conflict_calls_llm_and_uses_merged_summary_when_above_threshold(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="Water is a liquid compound."))
    update = CompiledUpdate(
        concepts=[Concept(slug="water", concept_title="Water", summary="Water freezes at 0 degrees Celsius.")]
    )
    merged_summary = "Water is a liquid compound that freezes at 0 degrees Celsius."
    client = _FakeLLMClient(content=merged_summary)
    ledger = _ledger(tmp_path)

    merged = DefaultMerger(client, ledger).merge(update, writer, batch_id=2)  # type: ignore[arg-type]

    assert merged.concepts[0].summary == merged_summary
    assert len(client.calls) == 1
    events = ledger.read_events()
    assert len(events) == 1
    assert events[0].stage == "Merger.summary_merge"
    assert events[0].batch_id == 2
    assert events[0].tokens_in == 5
    assert events[0].tokens_out == 7


def test_merged_summary_below_70_percent_threshold_is_rejected_keeps_old(tmp_path: Path) -> None:
    writer = _FakeWriter()
    long_old_summary = "Water is a liquid compound that is essential for all known forms of life on Earth."
    writer.write_concept(Concept(slug="water", concept_title="Water", summary=long_old_summary))
    update = CompiledUpdate(
        concepts=[Concept(slug="water", concept_title="Water", summary="Water freezes at 0 degrees Celsius.")]
    )
    # Suspiciously short "merged" result — well under 70% of max(len(old), len(new)).
    client = _FakeLLMClient(content="Water.")
    ledger = _ledger(tmp_path)

    merged = DefaultMerger(client, ledger).merge(update, writer, batch_id=1)  # type: ignore[arg-type]

    assert merged.concepts[0].summary == long_old_summary
    assert len(client.calls) == 1  # the LLM was still called; only its result was rejected


def test_summarize_source_within_budget_makes_one_call_at_round_zero(tmp_path: Path) -> None:
    client = _FakeLLMClient(content="Water boils at 100C and freezes at 0C.")
    ledger = _ledger(tmp_path)

    summary = DefaultMerger(client, ledger).summarize_source(  # type: ignore[arg-type]
        "doc-1", ["Water boils at 100C.", "Water freezes at 0C."], _FakeWriter(), batch_id=1
    )

    assert summary == "Water boils at 100C and freezes at 0C."
    assert len(client.calls) == 1
    events = ledger.read_events()
    assert len(events) == 1
    assert events[0].stage == "Merger.summarize_source"
    assert events[0].batch_id == 1
    assert events[0].round == 0


def test_summarize_source_over_budget_recurses_across_multiple_rounds(tmp_path: Path) -> None:
    """D21 §1.5: claims too long for one call are split into budget-sized batches, summarized, then the
    batch summaries are recursively reduced until they fit."""
    # 4 claims x 2000 chars = 8000 chars, over the 6000-char budget: splits into 2 batches (3 claims, 1 claim).
    claim_texts = [f"Claim {i}: " + ("x" * 1990) for i in range(4)]
    client = _FakeLLMClient(content="Short batch summary.")
    ledger = _ledger(tmp_path)

    summary = DefaultMerger(client, ledger).summarize_source(  # type: ignore[arg-type]
        "doc-1", claim_texts, _FakeWriter(), batch_id=3
    )

    assert summary == "Short batch summary."  # round 1's single final call, over the round-0 batch summaries
    assert len(client.calls) == 3  # 2 batch calls at round 0, 1 final reduce call at round 1
    events = ledger.read_events()
    assert sorted(e.round for e in events) == [0, 0, 1]
    assert all(e.stage == "Merger.summarize_source" and e.batch_id == 3 for e in events)
