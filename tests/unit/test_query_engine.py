"""Unit tests for `QueryEngine` orchestration control flow — fake `SearchStrategy`/`AnswerSynthesizer`/
`NextActionDecider`, so these tests exercise loop shape (T_max/patience/evidence accumulation), not real
retrieval scoring (see `test_query_strategies.py` for that)."""

from __future__ import annotations

import pytest

from llm_yuki.domain.entities import Claim, Concept, Source
from llm_yuki.domain.query import (
    EvidenceItem,
    IterativeAgenticQueryEngine,
    PageRecord,
    QueryAction,
    SearchHit,
    SinglePassQueryEngine,
    StructuredSignalSearch,
    SynthesizedAnswer,
)
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.unit


class _FakeWriter(Writer):
    def __init__(self) -> None:
        self.claims: dict[str, Claim] = {}
        self.concepts: dict[str, Concept] = {}
        self.sources: dict[str, Source] = {}

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
        pass


class _FakeSynthesizer:
    def __init__(self, answer: str = "the answer") -> None:
        self.answer = answer
        self.calls: list[list[PageRecord]] = []

    def synthesize(self, question: str, pages: list[PageRecord], batch_id: int) -> SynthesizedAnswer:
        self.calls.append(pages)
        return SynthesizedAnswer(answer=self.answer, cited_slugs=[p.slug for p in pages])


class _EmptyStrategy:
    def search(self, query: str, corpus: list[PageRecord], top_k: int) -> list[SearchHit]:
        return []


class _ScriptedDecider:
    """Returns each action in ``actions`` in order, one per ``decide`` call."""

    def __init__(self, actions: list[QueryAction]) -> None:
        self._actions = list(actions)
        self.calls: list[list[EvidenceItem]] = []

    def decide(self, question: str, evidence: list[EvidenceItem]) -> QueryAction:
        self.calls.append(evidence)
        return self._actions.pop(0)


# -- SinglePassQueryEngine ---------------------------------------------------------


def test_single_pass_engine_requires_at_least_one_strategy() -> None:
    with pytest.raises(ValueError, match="at least one"):
        SinglePassQueryEngine(strategies=[], synthesizer=_FakeSynthesizer())


def test_single_pass_engine_returns_synthesized_answer_with_method_name() -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="Water is a compound."))
    synthesizer = _FakeSynthesizer(answer="Water is H2O.")

    engine = SinglePassQueryEngine(strategies=[StructuredSignalSearch()], synthesizer=synthesizer)
    result = engine.answer("What is water?", writer, batch_id=1)

    assert result.question == "What is water?"
    assert result.answer == "Water is H2O."
    assert result.method == "single_pass"
    assert result.cited_slugs == ["water"]
    assert synthesizer.calls[0][0].slug == "water"


def test_single_pass_engine_passes_empty_pages_when_nothing_matches() -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="fire", concept_title="Fire", summary="Combustion."))
    synthesizer = _FakeSynthesizer()

    engine = SinglePassQueryEngine(strategies=[StructuredSignalSearch()], synthesizer=synthesizer)
    engine.answer("something about oceans", writer, batch_id=1)

    assert synthesizer.calls[0] == []


# -- IterativeAgenticQueryEngine ---------------------------------------------------------


def test_iterative_agentic_engine_stops_immediately_on_decider_stop() -> None:
    writer = _FakeWriter()
    synthesizer = _FakeSynthesizer()
    decider = _ScriptedDecider([QueryAction(tool="stop")])

    engine = IterativeAgenticQueryEngine(strategy=_EmptyStrategy(), decider=decider, synthesizer=synthesizer)  # type: ignore[arg-type]
    result = engine.answer("a question", writer, batch_id=1)

    assert result.method == "iterative_agentic"
    assert synthesizer.calls == [[]]
    assert len(decider.calls) == 1


def test_iterative_agentic_engine_terminates_on_patience_after_empty_searches() -> None:
    writer = _FakeWriter()
    synthesizer = _FakeSynthesizer()
    # Every decide() call asks to search; _EmptyStrategy always returns no hits, so patience should trip
    # before t_max (t_max is deliberately generous here).
    decider = _ScriptedDecider([QueryAction(tool="wiki_search", query="x") for _ in range(10)])

    engine = IterativeAgenticQueryEngine(
        strategy=_EmptyStrategy(),  # type: ignore[arg-type]
        decider=decider,
        synthesizer=synthesizer,
        t_max=10,
        patience=2,
    )
    engine.answer("a question", writer, batch_id=1)

    assert len(decider.calls) == 2  # stopped after 2 consecutive empty searches, not the full t_max=10


def test_iterative_agentic_engine_terminates_on_t_max() -> None:
    writer = _FakeWriter()
    synthesizer = _FakeSynthesizer()
    decider = _ScriptedDecider([QueryAction(tool="wiki_search", query="x") for _ in range(10)])

    engine = IterativeAgenticQueryEngine(
        strategy=_EmptyStrategy(),  # type: ignore[arg-type]
        decider=decider,
        synthesizer=synthesizer,
        t_max=3,
        patience=100,  # patience deliberately generous — t_max should trip first
    )
    engine.answer("a question", writer, batch_id=1)

    assert len(decider.calls) == 3


def test_iterative_agentic_engine_accumulates_pages_from_search_and_read() -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="Water is a compound."))
    writer.write_concept(Concept(slug="fire", concept_title="Fire", summary="Combustion."))
    synthesizer = _FakeSynthesizer(answer="synthesized")

    decider = _ScriptedDecider(
        [
            QueryAction(tool="wiki_search", query="water"),
            QueryAction(tool="wiki_read", slugs=["water"]),
            QueryAction(tool="stop"),
        ]
    )
    engine = IterativeAgenticQueryEngine(
        strategy=StructuredSignalSearch(), decider=decider, synthesizer=synthesizer, t_max=10, patience=10
    )

    result = engine.answer("What is water?", writer, batch_id=1)

    assert result.answer == "synthesized"
    pages_seen = synthesizer.calls[0]
    assert {p.slug for p in pages_seen} == {"water"}
    assert len(decider.calls) == 3
    # Second decide() call sees the first round's search evidence.
    assert decider.calls[1][0].kind == "search"
    assert decider.calls[1][0].hits[0].slug == "water"


def test_iterative_agentic_engine_ignores_read_slugs_not_present_in_corpus() -> None:
    writer = _FakeWriter()
    synthesizer = _FakeSynthesizer()
    decider = _ScriptedDecider([QueryAction(tool="wiki_read", slugs=["ghost"]), QueryAction(tool="stop")])

    engine = IterativeAgenticQueryEngine(strategy=_EmptyStrategy(), decider=decider, synthesizer=synthesizer)  # type: ignore[arg-type]
    engine.answer("a question", writer, batch_id=1)

    assert synthesizer.calls == [[]]
