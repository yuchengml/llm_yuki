"""Unit tests for `evaluation/qa_runner.py` — `load_qa_examples` (real filesystem, tmp_path) and
`run_qa_evaluation` (fake `QueryEngine`/`Writer`, no real retrieval/LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_yuki.domain.query import QueryAnswer
from llm_yuki.evaluation.qa_runner import QAExample, load_qa_examples, run_qa_evaluation
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.unit


class _FakeWriter(Writer):
    def write_claim(self, claim: object) -> None:
        raise NotImplementedError

    def write_concept(self, concept: object) -> None:
        raise NotImplementedError

    def write_source(self, source: object) -> None:
        raise NotImplementedError

    def read_claim(self, slug: str) -> None:
        return None

    def read_concept(self, slug: str) -> None:
        return None

    def read_source(self, slug: str) -> None:
        return None

    def list_pages(self) -> list[str]:
        return []

    def append_log(self, event: str) -> None:
        pass


class _ScriptedEngine:
    """Returns each answer in ``answers`` in order, one per ``answer()`` call — bypasses real retrieval."""

    method_name = "fake"

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)
        self.questions: list[str] = []

    def answer(self, question: str, writer: Writer, batch_id: int, top_k: int = 8) -> QueryAnswer:
        self.questions.append(question)
        return QueryAnswer(question=question, answer=self._answers.pop(0), cited_slugs=["x"], method=self.method_name)


# -- load_qa_examples ---------------------------------------------------------


def test_load_qa_examples_reads_answers_list(tmp_path: Path) -> None:
    path = tmp_path / "qa.jsonl"
    path.write_text('{"id": "q1", "question": "What is water?", "answers": ["H2O", "water"]}\n', encoding="utf-8")

    [example] = load_qa_examples(path)

    assert example.question == "What is water?"
    assert example.gold_answers == ["H2O", "water"]
    assert example.example_id == "q1"


def test_load_qa_examples_reads_single_answer_key(tmp_path: Path) -> None:
    path = tmp_path / "qa.jsonl"
    path.write_text('{"question": "What is water?", "answer": "H2O"}\n', encoding="utf-8")

    [example] = load_qa_examples(path)

    assert example.gold_answers == ["H2O"]
    assert example.example_id == ""


def test_load_qa_examples_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "qa.jsonl"
    path.write_text('{"question": "q1", "answer": "a1"}\n\n{"question": "q2", "answer": "a2"}\n', encoding="utf-8")

    examples = load_qa_examples(path)

    assert [e.question for e in examples] == ["q1", "q2"]


# -- run_qa_evaluation ---------------------------------------------------------


def test_run_qa_evaluation_scores_every_example() -> None:
    examples = [
        QAExample(question="What is water?", gold_answers=["H2O"]),
        QAExample(question="What is fire?", gold_answers=["combustion"]),
    ]
    engine = _ScriptedEngine(answers=["H2O", "not even close"])

    report = run_qa_evaluation(examples, engine, _FakeWriter())  # type: ignore[arg-type]

    assert report.method == "fake"
    assert report.count == 2
    assert engine.questions == ["What is water?", "What is fire?"]
    assert report.results[0].exact_match is True
    assert report.results[0].f1 == 1.0
    assert report.results[1].exact_match is False
    assert report.results[1].f1 == 0.0
    assert report.exact_match == 0.5  # 1 of 2 exact matches
    assert report.f1 == 0.5  # (1.0 + 0.0) / 2


def test_run_qa_evaluation_empty_examples_returns_zeroed_report() -> None:
    report = run_qa_evaluation([], _ScriptedEngine(answers=[]), _FakeWriter())  # type: ignore[arg-type]

    assert report.count == 0
    assert report.exact_match == 0.0
    assert report.f1 == 0.0


def test_report_to_dict_serializes_aggregate_and_per_example_results() -> None:
    examples = [QAExample(question="q", gold_answers=["a"], example_id="q1")]
    engine = _ScriptedEngine(answers=["a"])

    report = run_qa_evaluation(examples, engine, _FakeWriter())  # type: ignore[arg-type]
    as_dict = report.to_dict()

    assert as_dict["method"] == "fake"
    assert as_dict["count"] == 1
    assert as_dict["exact_match"] == 1.0
    assert as_dict["results"][0]["example"]["example_id"] == "q1"
    assert as_dict["results"][0]["predicted_answer"] == "a"
