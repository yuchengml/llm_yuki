"""End-to-end test: real Connector/Writer/Orchestrator, real (deterministic) Merger/ErrorBook/structural
Validator/CodeAutoFix, and a scripted fake LLM client standing in for the three LLM-backed calls — real
filesystem, no real network access (testing.md: "no live LLM calls in unit/integration/e2e tests — mock them").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_yuki.adapters.connectors.txt_file_connector import TxtFileConnector
from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.fixing.default_fixer import DefaultFixer
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.llm.extractor import LLMExtractor
from llm_yuki.adapters.merging.default_merger import DefaultMerger
from llm_yuki.adapters.validation.default_validator import DefaultValidator
from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.domain.error_book import ErrorBook
from llm_yuki.domain.pipeline import Orchestrator

pytestmark = pytest.mark.e2e

_COMPILE_RESULT = {
    "claims": [
        {
            "slug": "water-boils",
            "claim_text": "Water boils at 100C at sea level.",
            "source_ref": "doc-1",
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
            "tags": [],
            "summary": "A chemical compound.",
            "related_pages": [],
            "related_sources": [],
        }
    ],
}


class _ScriptedLLMClient:
    """Dispatches on which system prompt was used, so one fake stands in for all three LLM-backed stages."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, response_format_json: bool = False) -> LLMResponse:
        self.calls.append(messages)
        system = messages[0]["content"]
        if "SelectPages" in system:
            return LLMResponse(content=json.dumps({"selected": []}), tokens_in=5, tokens_out=2)
        if "CompileWikiPages" in system:
            return LLMResponse(content=json.dumps(_COMPILE_RESULT), tokens_in=20, tokens_out=15)
        if "ContentValidate" in system:
            return LLMResponse(content=json.dumps({"issues": []}), tokens_in=10, tokens_out=2)
        if "LLMPeriodicFix" in system:
            return LLMResponse(content=json.dumps({"claims": [], "concepts": []}), tokens_in=1, tokens_out=1)
        if "Document.summary generation" in system:
            return LLMResponse(content="Doc 1 covers water boiling at sea level.", tokens_in=8, tokens_out=6)
        raise AssertionError(f"unexpected system prompt: {system[:80]!r}")


def test_full_pipeline_compiles_one_batch_and_maintains_backlinks(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw_sources"
    doc_dir = source_dir / "doc-1"
    doc_dir.mkdir(parents=True)
    (doc_dir / "body.txt").write_text("Water boils at 100C at sea level.", encoding="utf-8")

    bundle_dir = tmp_path / "bundle"
    pipeline_state_dir = tmp_path / "pipeline-state"
    llm_client = _ScriptedLLMClient()
    cost_ledger = JsonlCostLedger(pipeline_state_dir)
    writer = MarkdownWriter(bundle_dir)

    orchestrator = Orchestrator(
        connector=TxtFileConnector(source_dir),
        writer=writer,
        extractor=LLMExtractor(llm_client, cost_ledger),  # type: ignore[arg-type]
        merger=DefaultMerger(llm_client, cost_ledger),  # type: ignore[arg-type]
        validator=DefaultValidator(llm_client, cost_ledger),  # type: ignore[arg-type]
        fixer=DefaultFixer(llm_client, cost_ledger),  # type: ignore[arg-type]
        error_book=ErrorBook(),
    )

    orchestrator.run_batch(batch_id=1)

    claim = writer.read_claim("water-boils")
    assert claim is not None
    assert claim.claim_text == "Water boils at 100C at sea level."
    assert claim.related_concepts == ["water"]

    concept = writer.read_concept("water")
    assert concept is not None
    assert concept.key_facts == ["water-boils"]  # backlink maintained by Writer, not the LLM (§2.3.2)

    body = (bundle_dir / "claims" / "water-boils.md").read_text(encoding="utf-8")
    assert "## Related Pages" in body
    assert "- [[water]]" in body

    document = writer.read_document("doc-1")
    assert document is not None
    assert document.summary == "Doc 1 covers water boiling at sea level."
    assert document.produced_claims == ["water-boils"]  # backlink maintained by Writer (D21), not the LLM
    assert document.produced_concepts == ["water"]

    # Extractor.SelectPages is skipped (no cost event) when there are no existing pages to select from yet
    # — LLMExtractor.select_pages returns [] without calling the LLM in that case.
    stages = {event.stage for event in cost_ledger.read_events()}
    assert stages == {"Extractor.CompileWikiPages", "Validator.ContentValidate", "Merger.summarize_document"}
