"""Integration tests for DefaultValidator.content_validate — fake LLM client, real cost ledger filesystem writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.adapters.validation.default_validator import DefaultValidator
from llm_yuki.domain.entities import Claim, Concept, ContradictionRef, Source
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
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, response_format_json: bool = False) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(content=self._content, tokens_in=4, tokens_out=6)


def _claim(**overrides: object) -> Claim:
    defaults: dict[str, object] = {
        "slug": "claim-1",
        "claim_text": "Water boils at 100C.",
        "source_ref": "doc-1#p1",
        "confidence": 0.9,
        "provenance_state": "extracted",
    }
    defaults.update(overrides)
    return Claim.model_validate(defaults)


def test_content_validate_returns_empty_without_calling_llm_when_no_claims(tmp_path: Path) -> None:
    client = _FakeLLMClient(content="{}")
    validator = DefaultValidator(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]

    issues = validator.content_validate(CompiledUpdate(), "passage", _FakeWriter(), batch_id=1)

    assert issues == []
    assert client.calls == []


def test_content_validate_parses_reported_issues_and_records_cost(tmp_path: Path) -> None:
    payload = {
        "issues": [
            {
                "error_type": "unsupported_facts",
                "phenomenon": "claim not grounded in passage",
                "affected_refs": ["claim-1"],
            }
        ]
    }
    client = _FakeLLMClient(content=json.dumps(payload))
    ledger = JsonlCostLedger(tmp_path)
    validator = DefaultValidator(client, ledger)  # type: ignore[arg-type]
    update = CompiledUpdate(claims=[_claim()])

    issues = validator.content_validate(update, "unrelated passage text", _FakeWriter(), batch_id=5)

    assert len(issues) == 1
    assert issues[0].error_type == "unsupported_facts"
    assert issues[0].affected_refs == ["claim-1"]

    events = ledger.read_events()
    assert events[0].stage == "Validator.ContentValidate"
    assert events[0].batch_id == 5


def test_content_validate_no_issues_returns_empty_list(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"issues": []}))
    validator = DefaultValidator(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]
    update = CompiledUpdate(claims=[_claim()])

    issues = validator.content_validate(update, "passage", _FakeWriter(), batch_id=1)

    assert issues == []


def test_content_validate_raises_on_malformed_json(tmp_path: Path) -> None:
    client = _FakeLLMClient(content="not json")
    validator = DefaultValidator(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]
    update = CompiledUpdate(claims=[_claim()])

    with pytest.raises(LLMOutputError):
        validator.content_validate(update, "passage", _FakeWriter(), batch_id=1)


def test_content_validate_raises_on_schema_mismatch(tmp_path: Path) -> None:
    client = _FakeLLMClient(content=json.dumps({"issues": [{"error_type": "not-a-real-type"}]}))
    validator = DefaultValidator(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]
    update = CompiledUpdate(claims=[_claim()])

    with pytest.raises(LLMOutputError):
        validator.content_validate(update, "passage", _FakeWriter(), batch_id=1)


def test_content_validate_prompt_includes_passage_and_sibling_claims(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="x", key_facts=["claim-sibling"]))
    writer.write_claim(_claim(slug="claim-sibling", claim_text="Water freezes at 0C."))
    client = _FakeLLMClient(content=json.dumps({"issues": []}))
    validator = DefaultValidator(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]
    update = CompiledUpdate(claims=[_claim(related_concepts=["water"])])

    validator.content_validate(update, "the source passage", writer, batch_id=1)

    user_message = client.calls[0][1]["content"]
    assert "the source passage" in user_message
    assert "claim-sibling" in user_message
    assert "Water freezes at 0C." in user_message


def test_content_validate_includes_contradicted_by_candidate_as_sibling(tmp_path: Path) -> None:
    writer = _FakeWriter()
    writer.write_claim(_claim(slug="claim-other", claim_text="The meeting was Tuesday."))
    client = _FakeLLMClient(content=json.dumps({"issues": []}))
    validator = DefaultValidator(client, JsonlCostLedger(tmp_path))  # type: ignore[arg-type]
    update = CompiledUpdate(
        claims=[_claim(contradicted_by=[ContradictionRef(slug="claim-other", reason="conflicting day")])]
    )

    validator.content_validate(update, "passage", writer, batch_id=1)

    user_message = client.calls[0][1]["content"]
    assert "claim-other" in user_message
    assert "The meeting was Tuesday." in user_message
