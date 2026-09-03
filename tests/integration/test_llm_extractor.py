"""Integration tests for LLMExtractor — fake LLM client (no network), real cost ledger filesystem writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.adapters.llm.extractor import LLMExtractor
from llm_yuki.domain.entities import Claim, Concept, Source
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


def test_select_pages_returns_empty_list_without_calling_llm_when_no_known_pages(tmp_path: Path) -> None:
    client = _FakeLLMClient(content="{}")
    extractor = LLMExtractor(client, _ledger(tmp_path))  # type: ignore[arg-type]

    result = extractor.select_pages("some passage", _FakeWriter(), batch_id=1)

    assert result == []
    assert client.calls == []


def test_select_pages_filters_to_known_slugs_and_records_cost(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A compound."))
    client = _FakeLLMClient(content=json.dumps({"selected": ["water", "hallucinated-slug"]}))
    ledger = _ledger(tmp_path)
    extractor = LLMExtractor(client, ledger)  # type: ignore[arg-type]

    result = extractor.select_pages("passage about water", writer, batch_id=3)

    assert result == ["water"]  # hallucinated slug filtered out
    events = ledger.read_events()
    assert len(events) == 1
    assert events[0].stage == "Extractor.SelectPages"
    assert events[0].batch_id == 3
    assert events[0].tokens_in == 5
    assert events[0].tokens_out == 7


def test_select_pages_raises_on_non_list_selected(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="x"))
    client = _FakeLLMClient(content=json.dumps({"selected": "not-a-list"}))
    extractor = LLMExtractor(client, _ledger(tmp_path))  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        extractor.select_pages("passage", writer, batch_id=1)


def test_select_pages_raises_on_malformed_json(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="x"))
    client = _FakeLLMClient(content="not json at all")
    extractor = LLMExtractor(client, _ledger(tmp_path))  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        extractor.select_pages("passage", writer, batch_id=1)


def test_compile_wiki_pages_parses_claims_and_concepts(tmp_path: Path) -> None:
    payload = {
        "claims": [
            {
                "slug": "claim-1",
                "claim_text": "Water boils at 100C at sea level.",
                "source_ref": "doc-1#p1",
                "confidence": 0.9,
                "provenance_state": "extracted",
                "related_concepts": ["water"],
                "contradicted_by": [],
            }
        ],
        "concepts": [
            {
                "slug": "water",
                "concept_title": "Water",
                "aliases": [],
                "tags": ["chemistry"],
                "summary": "A chemical compound.",
                "related_pages": [],
                "related_sources": [],
                "key_facts": ["should-be-dropped"],
            }
        ],
    }
    client = _FakeLLMClient(content=json.dumps(payload))
    ledger = _ledger(tmp_path)
    extractor = LLMExtractor(client, ledger)  # type: ignore[arg-type]

    update = extractor.compile_wiki_pages("passage", selected=["water"], constraints=["avoid X"], batch_id=2)

    assert len(update.claims) == 1
    assert update.claims[0].slug == "claim-1"
    assert len(update.concepts) == 1
    assert update.concepts[0].key_facts == []  # LLM-provided key_facts is stripped, not trusted

    events = ledger.read_events()
    assert events[0].stage == "Extractor.CompileWikiPages"
    assert events[0].batch_id == 2


def test_compile_wiki_pages_skips_malformed_item_keeps_the_rest(tmp_path: Path) -> None:
    """A single malformed Claim/Concept (missing required fields) is dropped, not treated as a reason to
    discard every other candidate in the same response — real-world failure that motivated this: one
    Concept missing concept_title used to abort an entire batch, losing every other passage's work too
    (see TODO.md's dated note)."""
    payload = {
        "claims": [{"slug": "x"}],  # missing claim_text/source_ref/confidence/provenance_state
        "concepts": [
            {"slug": "bad"},  # missing concept_title/summary
            {
                "slug": "water",
                "concept_title": "Water",
                "aliases": [],
                "tags": [],
                "summary": "A chemical compound.",
                "related_pages": [],
                "related_sources": [],
            },
        ],
    }
    client = _FakeLLMClient(content=json.dumps(payload))
    extractor = LLMExtractor(client, _ledger(tmp_path))  # type: ignore[arg-type]

    update = extractor.compile_wiki_pages("passage", selected=[], constraints=[], batch_id=1)

    assert update.claims == []
    assert [c.slug for c in update.concepts] == ["water"]


def test_compile_wiki_pages_raises_on_non_list_claims(tmp_path: Path) -> None:
    """Still fatal: a structurally broken payload isn't "one bad item," it's not a response this function
    can make sense of at all."""
    client = _FakeLLMClient(content=json.dumps({"claims": "not-a-list", "concepts": []}))
    extractor = LLMExtractor(client, _ledger(tmp_path))  # type: ignore[arg-type]

    with pytest.raises(LLMOutputError):
        extractor.compile_wiki_pages("passage", selected=[], constraints=[], batch_id=1)


def test_compile_wiki_pages_empty_result_is_valid(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"claims": [], "concepts": []}))
    extractor = LLMExtractor(client, _ledger(tmp_path))  # type: ignore[arg-type]

    update = extractor.compile_wiki_pages("passage", selected=[], constraints=[], batch_id=1)

    assert update.claims == []
    assert update.concepts == []


def test_compile_wiki_pages_prompt_includes_constraints_and_selected_pages(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"claims": [], "concepts": []}))
    extractor = LLMExtractor(client, _ledger(tmp_path))  # type: ignore[arg-type]

    extractor.compile_wiki_pages("my passage", selected=["water"], constraints=["never do X"], batch_id=1)

    user_message = client.calls[0][1]["content"]
    assert "my passage" in user_message
    assert "water" in user_message
    assert "never do X" in user_message
