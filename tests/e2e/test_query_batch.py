"""End-to-end tests for the Query module (D25): real `MarkdownWriter`, real `StructuredSignalSearch`/fusion/
graph-expansion, and a scripted fake LLM client standing in for `AnswerSynthesizer`/`NextActionDecider` — real
filesystem, no real network access (same convention as `test_compile_batch.py`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.answer_synthesizer import LLMAnswerSynthesizer
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.llm.next_action_decider import LLMActionDecider
from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.domain.entities import Claim, Concept, Source
from llm_yuki.domain.query import IterativeAgenticQueryEngine, SinglePassQueryEngine, StructuredSignalSearch

pytestmark = pytest.mark.e2e


class _ScriptedLLMClient:
    """Dispatches on system prompt content, so one fake stands in for both the synthesizer and the decider."""

    def __init__(self, decider_script: list[dict[str, object]] | None = None) -> None:
        self._decider_script = list(decider_script or [])
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, response_format_json: bool = False) -> LLMResponse:
        self.calls.append(messages)
        system = messages[0]["content"]
        if "answer-synthesis" in system:
            return LLMResponse(
                content=json.dumps({"answer": "Water boils at 100C at sea level.", "cited_slugs": ["water-boils"]}),
                tokens_in=20,
                tokens_out=10,
            )
        if "action-decider" in system:
            action = self._decider_script.pop(0)
            return LLMResponse(content=json.dumps(action), tokens_in=8, tokens_out=4)
        raise AssertionError(f"unexpected system prompt: {system[:80]!r}")


def _seed_bundle(bundle_dir: Path) -> MarkdownWriter:
    writer = MarkdownWriter(bundle_dir)
    writer.write_source(
        Source(
            slug="doc-1",
            source_title="Doc 1",
            source_path="raw_sources/doc-1",
            ingested_at="2026-08-30",
            summary="Covers water's boiling point.",
        )
    )
    writer.write_concept(
        Concept(slug="water", concept_title="Water", summary="Water is a chemical compound.", tags=["chemistry"])
    )
    writer.write_claim(
        Claim(
            slug="water-boils",
            claim_text="Water boils at 100C at sea level.",
            source_ref="doc-1#p0",
            confidence=0.9,
            provenance_state="extracted",
            related_concepts=["water"],
        )
    )
    return writer


def test_single_pass_query_answers_from_a_real_bundle(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    writer = _seed_bundle(bundle_dir)
    llm_client = _ScriptedLLMClient()
    cost_ledger = JsonlCostLedger(tmp_path / "pipeline-state")

    engine = SinglePassQueryEngine(
        strategies=[StructuredSignalSearch()],
        synthesizer=LLMAnswerSynthesizer(llm_client, cost_ledger),  # type: ignore[arg-type]
    )
    result = engine.answer("At what temperature does water boil?", writer, batch_id=1)

    assert result.answer == "Water boils at 100C at sea level."
    assert result.cited_slugs == ["water-boils"]
    assert result.method == "single_pass"
    stages = {event.stage for event in cost_ledger.read_events()}
    assert stages == {"AnswerSynthesizer.Synthesize"}


def test_single_pass_query_graph_expands_to_related_concept(tmp_path: Path) -> None:
    """A query that only matches the Claim's content should still pull in its linked Concept via one-hop
    graph expansion (§8.3) — the Concept doesn't mention "boil" anywhere, only the Claim does."""
    bundle_dir = tmp_path / "bundle"
    writer = _seed_bundle(bundle_dir)
    llm_client = _ScriptedLLMClient()
    cost_ledger = JsonlCostLedger(tmp_path / "pipeline-state")

    engine = SinglePassQueryEngine(
        strategies=[StructuredSignalSearch()],
        synthesizer=LLMAnswerSynthesizer(llm_client, cost_ledger),  # type: ignore[arg-type]
    )
    engine.answer("boil", writer, batch_id=1)

    user_message = llm_client.calls[0][1]["content"]
    assert "water-boils" in user_message
    # The Concept's own content only appears if the page itself was fetched — proves graph expansion actually
    # pulled it in, not just that "water" is a substring of "water-boils".
    assert "Water is a chemical compound." in user_message


def test_iterative_agentic_query_follows_search_then_read_then_stop(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    writer = _seed_bundle(bundle_dir)
    llm_client = _ScriptedLLMClient(
        decider_script=[
            {"tool": "wiki_search", "query": "boiling"},
            {"tool": "wiki_read", "slugs": ["water-boils"]},
            {"tool": "stop"},
        ]
    )
    cost_ledger = JsonlCostLedger(tmp_path / "pipeline-state")

    engine = IterativeAgenticQueryEngine(
        strategy=StructuredSignalSearch(),
        decider=LLMActionDecider(llm_client, cost_ledger, batch_id=1),  # type: ignore[arg-type]
        synthesizer=LLMAnswerSynthesizer(llm_client, cost_ledger),  # type: ignore[arg-type]
    )
    result = engine.answer("At what temperature does water boil?", writer, batch_id=1)

    assert result.answer == "Water boils at 100C at sea level."
    assert result.method == "iterative_agentic"
    stages = [event.stage for event in cost_ledger.read_events()]
    assert stages.count("NextActionDecider.Decide") == 3
    assert stages.count("AnswerSynthesizer.Synthesize") == 1
