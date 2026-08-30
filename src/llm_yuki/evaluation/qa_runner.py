"""Runs a `QueryEngine` (D25) over a set of question/gold-answer pairs against an existing OKF bundle, and
scores EM/F1 — the mechanism behind SPEC.md's "檢索/推理正確性" success criterion (D5/D8: `M3SciQA`/`MMDocRAG`
QA accuracy/F1 vs. a plain vector-RAG baseline).

**Dataset-agnostic by design**: this harness does not itself vendor `M3SciQA`/`MMDocRAG`/`MuSiQue` — it reads
any JSONL of ``{"question": ..., "answers": [...]}`` rows (see :func:`load_qa_examples`). Pointing it at a real
benchmark requires a separate, dataset-specific conversion step first: (a) the benchmark's own QA pairs
reshaped into this JSONL format, and (b) the benchmark's source documents compiled into an OKF bundle via
`llm-yuki compile` (which itself requires converting the benchmark's raw files into D10's Raw Source folder
format — a Raw Source is assumed pre-converted, not something this pipeline does). Both conversions are
tracked as follow-up work in `TODO.md`, not implemented by this module — see `docs/implementation/query.md`'s
"Explicitly out of scope" note.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from llm_yuki.domain.query import QueryEngine
from llm_yuki.evaluation.qa_metrics import best_exact_match, best_f1
from llm_yuki.ports.writer import Writer


@dataclass(frozen=True)
class QAExample:
    """One question/gold-answer(s) pair — one row of a benchmark's QA JSONL."""

    question: str
    gold_answers: list[str]
    example_id: str = ""


@dataclass(frozen=True)
class QAResult:
    """One example's outcome: the engine's answer, its citations, and EM/F1 against ``example.gold_answers``."""

    example: QAExample
    predicted_answer: str
    cited_slugs: list[str]
    exact_match: bool
    f1: float


@dataclass(frozen=True)
class EvaluationReport:
    """Aggregate EM/F1 over every example, plus the raw per-example results."""

    method: str
    results: list[QAResult] = field(default_factory=list)

    @property
    def count(self) -> int:
        """Number of examples this report covers."""
        return len(self.results)

    @property
    def exact_match(self) -> float:
        """Aggregate exact-match rate across every example (``0.0`` if there are none)."""
        return _average(result.exact_match for result in self.results)

    @property
    def f1(self) -> float:
        """Aggregate mean F1 across every example (``0.0`` if there are none)."""
        return _average(result.f1 for result in self.results)

    def to_dict(self) -> dict[str, object]:
        """Serialize the aggregate metrics plus every per-example result to a plain JSON-able dict."""
        return {
            "method": self.method,
            "count": self.count,
            "exact_match": self.exact_match,
            "f1": self.f1,
            "results": [dataclasses.asdict(result) for result in self.results],
        }


def load_qa_examples(path: Path | str) -> list[QAExample]:
    """Read QA pairs from a JSONL file, one object per line.

    Each line must have a ``question`` key and either an ``answers`` key (a list of acceptable strings, for
    multi-reference gold answers) or a single ``answer`` key (a string); an optional ``id`` key is kept for
    reporting.
    """
    examples: list[QAExample] = []
    with Path(path).open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            answers = row.get("answers")
            if answers is None:
                answers = [row["answer"]]
            examples.append(
                QAExample(question=row["question"], gold_answers=list(answers), example_id=str(row.get("id", "")))
            )
    return examples


def run_qa_evaluation(
    examples: list[QAExample], engine: QueryEngine, writer: Writer, batch_id: int = 1, top_k: int = 8
) -> EvaluationReport:
    """Run ``engine`` over every example, score EM/F1 against its gold answers, and aggregate."""
    results = [_evaluate_one(example, engine, writer, batch_id, top_k) for example in examples]
    return EvaluationReport(method=engine.method_name, results=results)


def _evaluate_one(example: QAExample, engine: QueryEngine, writer: Writer, batch_id: int, top_k: int) -> QAResult:
    answer = engine.answer(example.question, writer, batch_id, top_k=top_k)
    return QAResult(
        example=example,
        predicted_answer=answer.answer,
        cited_slugs=answer.cited_slugs,
        exact_match=best_exact_match(answer.answer, example.gold_answers),
        f1=best_f1(answer.answer, example.gold_answers),
    )


def _average(values: Iterable[bool] | Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        return 0.0
    return sum(float(value) for value in materialized) / len(materialized)
