# QA Evaluation Harness

Module: `evaluation/qa_metrics.py` (pure EM/F1 scoring) + `evaluation/qa_runner.py` (runs a `QueryEngine`
over QA pairs and aggregates). Backs SPEC.md's "檢索/推理正確性" success criterion (D5/D8): `M3SciQA`/
`MMDocRAG` QA accuracy/F1 vs. a plain vector-RAG baseline. Lives outside `domain`/`ports`/`adapters` — this is
evaluation tooling built on top of the Query module (`query.md`), not core pipeline logic, the same top-level
status `cli.py` already has (see root `ARCHITECTURE.md`).

## Dataset-agnostic by design

**This harness does not vendor `M3SciQA`/`MMDocRAG`/`MuSiQue`.** It reads any JSONL of question/gold-answer
pairs and runs any `QueryEngine` against any already-compiled bundle. Pointing it at a real benchmark needs
two separate, dataset-specific conversion steps first, neither of which this module does:

1. The benchmark's raw documents converted into D10's Raw Source folder format (`folder = document, txt +
   images/`), then compiled into an OKF bundle via `llm-yuki compile` — same "Raw Sources arrive
   pre-converted" assumption D10 already makes for the rest of the pipeline.
2. The benchmark's own QA pairs reshaped into this harness's JSONL shape (below).

Both are tracked as follow-up work in root `TODO.md`, not attempted by this session — `M3SciQA`
(~3,066 papers) and `MMDocRAG` (222 documents, avg. 67 pages) are large academic corpora that need their own
acquisition/conversion effort, separate from the harness itself being ready to run against them.

## `qa_metrics.py` — EM/F1, the standard QA-eval convention

```python
def normalize_answer(text: str) -> str: ...   # lowercase, strip punctuation, drop articles, collapse whitespace
def exact_match(prediction: str, gold: str) -> bool: ...
def f1_score(prediction: str, gold: str) -> float: ...   # token-overlap F1 after normalization
def best_exact_match(prediction: str, golds: Iterable[str]) -> bool: ...   # multi-reference: best of several golds
def best_f1(prediction: str, golds: Iterable[str]) -> float: ...
```

Same normalization/scoring convention used across the multi-hop QA literature `M3SciQA`/`MMDocRAG`/`MuSiQue`
belong to — the LLM-Wiki paper's own HotpotQA/MuSiQue/2WikiMultiHopQA F1 numbers
(`QUERY-SEARCH-SURVEY.md` §2) use the same normalization, so a number this harness produces is comparable to
those without any extra conversion.

## `qa_runner.py` — load, run, aggregate

```python
@dataclass(frozen=True)
class QAExample:
    question: str
    gold_answers: list[str]
    example_id: str = ""

def load_qa_examples(path: Path | str) -> list[QAExample]: ...

def run_qa_evaluation(
    examples: list[QAExample], engine: QueryEngine, writer: Writer, batch_id: int = 1, top_k: int = 8
) -> EvaluationReport: ...
```

- **`load_qa_examples`**: one JSON object per line, needs `question` plus either `answers` (a list — for
  multi-reference gold answers) or `answer` (a single string); an optional `id` is kept for reporting. Blank
  lines are skipped.
- **`run_qa_evaluation`**: calls `engine.answer(example.question, writer, batch_id, top_k=top_k)` once per
  example (any `QueryEngine` — `SinglePassQueryEngine` or `IterativeAgenticQueryEngine`, see `query.md`),
  scores the returned `QueryAnswer.answer` against `example.gold_answers` via `best_exact_match`/`best_f1`,
  and returns an `EvaluationReport`.
- **`EvaluationReport`**: `method` (from `engine.method_name`), `results: list[QAResult]` (one per example —
  the predicted answer, its citations, and its EM/F1), plus aggregate `count`/`exact_match`/`f1` properties
  (simple means over `results`, `0.0` on an empty report). `.to_dict()` serializes the whole report
  (aggregate + every per-example result) to a plain JSON-able dict, for `--output`.

## CLI

```
llm-yuki evaluate-qa <bundle_dir> <qa_path.jsonl> [--method single-pass|agentic] [--top-k N] \
    [--batch-id N] [--pipeline-state-dir DIR] [--t-max N] [--patience N] [--output report.json]
```

Prints `method=... count=... exact_match=... f1=...` to stdout; `--output` additionally writes the full
`EvaluationReport.to_dict()` JSON (every example's prediction, citations, and per-example EM/F1) to disk.
Shares `_build_query_engine` with the `query` subcommand (`src/llm_yuki/cli.py`) — same LLM-config
fail-fast behavior as `compile`/`query`. Read-only against `bundle_dir`, same as `query`.

## What "done" looks like for a real benchmark run

Not attempted this session — recorded here so the next pass knows the shape of the remaining work:

1. Write a `M3SciQA`-specific (and separately, `MMDocRAG`-specific) conversion script: raw benchmark files →
   D10 Raw Source folders, and the benchmark's QA pairs → this harness's JSONL shape.
2. `llm-yuki compile` each converted corpus into its own bundle (D9's "two domains, not merged" scope,
   still in force — see `ASSUMPTIONS.md` A-8).
3. `llm-yuki evaluate-qa` each bundle against its own QA JSONL, once per `QueryEngine` (`single-pass` and
   `agentic`) — the two methods D25 built specifically so both could be run through this exact loop.
4. Build (or reuse an existing) simple vector-RAG baseline for the D8 comparison — out of scope for the
   Query module itself (D25 decision 1 leaves embedding retrieval unimplemented), so this baseline is a
   separate, self-contained comparison harness, not a mode of this one.
