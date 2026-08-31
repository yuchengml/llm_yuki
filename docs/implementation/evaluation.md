# QA Evaluation Harness

Module: `evaluation/qa_metrics.py` (pure EM/F1 scoring) + `evaluation/qa_runner.py` (runs a `QueryEngine`
over QA pairs and aggregates). Backs SPEC.md's "檢索/推理正確性" success criterion (D5/D8): `M3SciQA`/
`MMDocRAG` QA accuracy/F1 vs. a plain vector-RAG baseline. Lives outside `domain`/`ports`/`adapters` — this is
evaluation tooling built on top of the Query module (`query.md`), not core pipeline logic, the same top-level
status `cli.py` already has (see root `ARCHITECTURE.md`).

## Dataset-agnostic by design

**The harness itself does not vendor `M3SciQA`/`MMDocRAG`/`MuSiQue`** — it reads any JSONL of question/
gold-answer pairs and runs any `QueryEngine` against any already-compiled bundle. Pointing it at a real
benchmark needs two separate, dataset-specific conversion steps first:

1. The benchmark's raw documents converted into D10's Raw Source folder format (`folder = document, txt +
   images/`), then compiled into an OKF bundle via `llm-yuki compile` — same "Raw Sources arrive
   pre-converted" assumption D10 already makes for the rest of the pipeline.
2. The benchmark's own QA pairs reshaped into this harness's JSONL shape (below).

**`MuSiQue` now has both** — `scripts/musique_subset_to_raw_sources.py` (D26, below) — verified against real
downloaded data, though not yet run through an actual `compile`/`evaluate-qa` pass (needs real LLM
credentials this session doesn't have). `M3SciQA` (~3,066 papers) and `MMDocRAG` (222 documents, avg. 67
pages) still need their own conversion scripts — tracked as follow-up work in root `TODO.md` — large academic
corpora needing their own acquisition/conversion effort, separate from the harness itself being ready to run
against them.

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

## MuSiQue subset experiment (D26)

`scripts/musique_subset_to_raw_sources.py` is a working conversion script for `MuSiQue` — the one benchmark
of the three D5 named where a converter has actually been built and run (verified against real data, not just
designed). See D26 (proposal `README.md`) for why this exists and its explicit scope limits.

**Why MuSiQue needed a different approach than `M3SciQA`/`MMDocRAG`**: those two are each a fixed, shared
document corpus that every question in the benchmark draws from — a natural fit for this pipeline's
"compile once, query many times" model. MuSiQue isn't: each of its 25K questions carries its *own* set of ~20
short Wikipedia paragraphs (2–4 "supporting," the rest deliberate distractors), not a corpus shared across
questions. Pooling *all* 25K questions' paragraphs would work in principle but is enormous; the script instead
supports a bounded sample.

**Data source**: MuSiQue's own distribution is a Google Drive zip (no direct-download JSONL) — unreachable
from this environment's egress policy when D26 was written. The script instead downloads (and caches)
`OSU-NLP-Group/HippoRAG`'s `reproduce/dataset/musique.json`, a 1000-question MuSiQue dev subset that
HippoRAG/LightRAG/GraphRAG-Bench-adjacent literature uses for this exact kind of evaluation — verified by
cloning that repo directly and confirming its paragraphs, deduplicated, exactly match its separate
`musique_corpus.json` (11,656 entries either way).

```bash
poetry run python scripts/musique_subset_to_raw_sources.py \
    --num-questions 20 --seed 0 \
    --out-raw-sources data/raw_sources/musique-sample \
    --out-qa-jsonl data/musique-sample-qa.jsonl
# then, with LLM config set up (root README.md "Run the CLI"):
poetry run llm-yuki compile data/raw_sources/musique-sample bundle
poetry run llm-yuki evaluate-qa bundle data/musique-sample-qa.jsonl --output report.json
```

- **Sample mode (default)**: samples `--num-questions` questions (`--seed` for reproducibility), pools only
  their own paragraphs into Raw Source documents — bounded compile cost, good for trying the pipeline
  end to end. **Its EM/F1 is not comparable to published MuSiQue baselines** (D26 decision 3) — those report
  against the full 1000-question set.
- **`--full-corpus`**: all 1000 questions / ~11,656 paragraphs — the literature-comparable setup, but
  expensive to compile through an LLM-backed `Extractor`. Not run by default; needs an explicit decision to
  spend that budget.

**Verified this session** (no real LLM access in this environment, so this stops short of an actual
`compile`/`evaluate-qa` run): downloaded the real `musique.json`, sampled 5 questions, generated 100 Raw
Source documents + a 5-line QA JSONL, and round-tripped both through the real `TxtFileConnector.read_source`
and `load_qa_examples` — confirming the output is genuinely valid pipeline input, not just plausible-looking
files. Actually running `compile`/`evaluate-qa` against it needs real `OPENAI_API_KEY`/`OPENAI_BASE_URL`/
`LLM_MODEL` (see root README.md), which this session doesn't have.

## What "done" looks like for a real benchmark run

`M3SciQA`/`MMDocRAG` conversion is not attempted yet — recorded here so the next pass knows the shape of the
remaining work:

1. Write a `M3SciQA`-specific (and separately, `MMDocRAG`-specific) conversion script: raw benchmark files →
   D10 Raw Source folders, and the benchmark's QA pairs → this harness's JSONL shape.
2. `llm-yuki compile` each converted corpus into its own bundle (D9's "two domains, not merged" scope,
   still in force — see `ASSUMPTIONS.md` A-8).
3. `llm-yuki evaluate-qa` each bundle against its own QA JSONL, once per `QueryEngine` (`single-pass` and
   `agentic`) — the two methods D25 built specifically so both could be run through this exact loop.
4. Build (or reuse an existing) simple vector-RAG baseline for the D8 comparison — out of scope for the
   Query module itself (D25 decision 1 leaves embedding retrieval unimplemented), so this baseline is a
   separate, self-contained comparison harness, not a mode of this one.
5. For an actual literature-comparable `MuSiQue` number: run `musique_subset_to_raw_sources.py --full-corpus`
   (above) — the harder remaining part is the LLM budget/time to compile ~11,656 documents, not any missing
   mechanism.
