"""End-to-end test proving the QA evaluation harness works against a real bundle — real `MarkdownWriter`,
real `SinglePassQueryEngine`/`StructuredSignalSearch`/fusion/graph-expansion, a scripted fake LLM client for
`AnswerSynthesizer`, real EM/F1 scoring. `M3SciQA`/`MMDocRAG` themselves aren't vendored in this repo (see
`evaluation/qa_runner.py`'s module docstring) — this is the harness's own correctness proof on a small
synthetic corpus, not a real-benchmark run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.answer_synthesizer import LLMAnswerSynthesizer
from llm_yuki.adapters.llm.client import LLMResponse
from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.query import SinglePassQueryEngine, StructuredSignalSearch
from llm_yuki.evaluation.qa_runner import load_qa_examples, run_qa_evaluation

pytestmark = pytest.mark.e2e


class _ScriptedSynthesizerClient:
    """Answers each question deterministically from a fixed lookup, keyed by a substring of the question."""

    def __init__(self, answers_by_keyword: dict[str, str]) -> None:
        self._answers_by_keyword = answers_by_keyword

    def complete(self, messages: list[dict[str, str]], *, response_format_json: bool = False) -> LLMResponse:
        user_message = messages[-1]["content"].lower()
        for keyword, answer in self._answers_by_keyword.items():
            if keyword in user_message:
                return LLMResponse(
                    content=json.dumps({"answer": answer, "cited_slugs": ["water-boils"]}), tokens_in=10, tokens_out=5
                )
        return LLMResponse(content=json.dumps({"answer": "unknown", "cited_slugs": []}), tokens_in=10, tokens_out=5)


def test_evaluate_qa_computes_em_and_f1_against_a_real_bundle(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    writer = MarkdownWriter(bundle_dir)
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="Water is a chemical compound."))
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

    qa_path = tmp_path / "qa.jsonl"
    qa_path.write_text(
        "\n".join(
            [
                json.dumps({"id": "q1", "question": "At what temperature does water boil?", "answers": ["100C"]}),
                json.dumps({"id": "q2", "question": "What is the capital of France?", "answers": ["Paris"]}),
            ]
        ),
        encoding="utf-8",
    )
    examples = load_qa_examples(qa_path)

    llm_client = _ScriptedSynthesizerClient(
        answers_by_keyword={"boil": "Water boils at 100C at sea level.", "capital": "unknown"}
    )
    cost_ledger = JsonlCostLedger(tmp_path / "pipeline-state")
    engine = SinglePassQueryEngine(
        strategies=[StructuredSignalSearch()],
        synthesizer=LLMAnswerSynthesizer(llm_client, cost_ledger),  # type: ignore[arg-type]
    )

    report = run_qa_evaluation(examples, engine, writer, batch_id=1, top_k=8)

    assert report.method == "single_pass"
    assert report.count == 2
    # q1: "100C" is a substring of the correct answer -> both EM and F1 credit it.
    assert report.results[0].exact_match is False  # "100C" != "water boils at 100c at sea level" after normalization
    assert report.results[0].f1 > 0.0  # but partial token overlap still scores
    # q2: nothing in the bundle answers this — the synthesizer honestly returns "unknown".
    assert report.results[1].exact_match is False
    assert report.results[1].f1 == 0.0
    assert 0.0 < report.f1 < 1.0

    report_dict = report.to_dict()
    assert report_dict["count"] == 2
    assert report_dict["results"][0]["example"]["example_id"] == "q1"
