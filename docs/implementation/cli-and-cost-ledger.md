# CLI and Cost Ledger

Two mechanisms that don't belong to any single pipeline stage: how the whole thing gets invoked
(`llm_yuki.cli`), and how every LLM-backed call's cost gets recorded (`adapters/cost_ledger.py`, D19).

## The `llm-yuki` CLI

Module: `src/llm_yuki/cli.py`, installed as the `llm-yuki` console script (`pyproject.toml`
`[tool.poetry.scripts]`). Pipeline execution is CLI-first by design — no web/API service is planned for this
POC (root `ARCHITECTURE.md` §5).

### `compile` subcommand

```
llm-yuki compile <source_dir> <bundle_dir> [--batch-id N] [--pipeline-state-dir DIR] [--max-workers N]
```

| Argument | Default | Meaning |
|---|---|---|
| `source_dir` | required | Raw Sources root — one subfolder per document, each a `.txt` body + optional `images/` |
| `bundle_dir` | required | Output OKF bundle directory (see `writer.md`) |
| `--batch-id` | `1` | Passed straight through to `Orchestrator.run_batch` — see `pipeline-overview.md` |
| `--pipeline-state-dir` | `<bundle_dir's parent>/pipeline-state` | Where `error_book.yaml`/`cost_ledger.jsonl` live |
| `--max-workers` | `4` | Caps Phase 1's `ThreadPoolExecutor` concurrency — see `pipeline-overview.md` |

### `main()` / `_run_compile()` — what actually happens

```python
def main(argv=None) -> int:
    load_dotenv(find_dotenv(usecwd=True))
    args = build_parser().parse_args(argv)
    if args.command == "compile":
        pipeline_state_dir = args.pipeline_state_dir or (args.bundle_dir.parent / "pipeline-state")
        return _run_compile(args.source_dir, args.bundle_dir, pipeline_state_dir, args.batch_id, args.max_workers)

def _run_compile(source_dir, bundle_dir, pipeline_state_dir, batch_id, max_workers) -> int:
    try:
        llm_client = OpenAICompatibleClient.from_env()
    except LLMConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    connector = TxtFileConnector(source_dir)
    writer = MarkdownWriter(bundle_dir)
    cost_ledger = JsonlCostLedger(pipeline_state_dir)
    error_book_store = YamlErrorBookStore(pipeline_state_dir)
    error_book = error_book_store.load()

    orchestrator = Orchestrator(
        connector=connector, writer=writer,
        extractor=LLMExtractor(llm_client, cost_ledger),
        merger=DefaultMerger(llm_client, cost_ledger),
        validator=DefaultValidator(llm_client, cost_ledger),
        fixer=DefaultFixer(llm_client, cost_ledger),
        error_book=error_book, max_workers=max_workers,
    )
    orchestrator.run_batch(batch_id)
    error_book_store.save(error_book)
    return 0
```

Every adapter gets constructed here, once, and shares the *same* `llm_client`/`cost_ledger` instance across
`Extractor`/`Merger`/`Validator`/`Fixer` — which is exactly why `JsonlCostLedger.record` needs to be
thread-safe (Phase 1 calls it concurrently through `LLMExtractor`, see below).

- **`.env` auto-loading**: `load_dotenv(find_dotenv(usecwd=True))` runs before anything else. `usecwd=True` is
  deliberate — `python-dotenv`'s default search starts from the *calling source file's* location, which for
  an installed package would search the package's install path, not wherever the user actually ran the
  command from. A real environment variable always takes precedence over a `.env` value if both are set.
- **Fail fast on missing LLM config**: `OpenAICompatibleClient.from_env()` is the very first thing that can
  fail, before any Connector/Writer/Orchestrator object is even constructed — a missing `OPENAI_API_KEY`/
  `OPENAI_BASE_URL`/`LLM_MODEL` produces a clear one-line error naming every missing variable at once and
  exits with code 1, rather than failing deep inside a batch on the first LLM-backed call.
- `error_book_store.save(error_book)` runs after `run_batch` returns — the whole batch's `ErrorBook` mutations
  (opened/closed entries) get persisted in one write at the end, not incrementally.

## LLM client — `OpenAICompatibleClient`

Module: `adapters/llm/client.py`. A thin wrapper around the `openai` Python package, deliberately generic —
targets either OpenRouter or a self-hosted OpenAI-compatible server (vLLM, Ollama, …), never a
vendor-specific native SDK. `from_env()` reads `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`LLM_MODEL`; there's
deliberately no default `base_url` — forcing an explicit choice avoids silently talking to a real paid
endpoint nobody configured on purpose. `complete(messages, response_format_json=False)` returns an
`LLMResponse(content, tokens_in, tokens_out)`. Does not record cost itself — it has no notion of `stage`/
`batch_id`; every LLM-backed caller (`LLMExtractor`, `DefaultValidator`, `DefaultFixer`, `DefaultMerger`)
times its own call and records it via `cost_ledger.record(...)`.

## Cost Ledger (D19)

Module: `adapters/cost_ledger.py::JsonlCostLedger`. Append-only `pipeline-state/cost_ledger.jsonl`, one JSON
line (`CostEvent`) per pipeline stage call — including non-LLM steps, which explicitly record `0` tokens
rather than being omitted from the log entirely (matters for later cost-comparison analysis, per §7.2 of the
proposal — though in the current codebase, only genuinely LLM-backed calls actually call `record`; purely
deterministic steps like `StructuralValidate`/`CodeAutoFix`/array-union merging don't yet emit their own
0-token events, since that would mean threading a cost port into the domain-pure `Orchestrator`;
`record_call()` exists as a context-manager helper for that later if wanted).

```python
class CostEvent(BaseModel):
    event_id: str          # uuid4 hex, auto-generated
    stage: str
    batch_id: int
    tokens_in: int
    tokens_out: int
    wall_clock_ms: float
    round: int | None = None   # only meaningful for Merger.summarize_source's batch-reduce rounds
    timestamp: str          # ISO 8601 UTC, auto-generated
```

### Every stage that records a `CostEvent`

| `stage` | Recorded by | When |
|---|---|---|
| `Extractor.SelectPages` | `LLMExtractor.select_pages` | Skipped entirely if `writer.list_pages()` is empty (see `extractor.md`) |
| `Extractor.CompileWikiPages` | `LLMExtractor.compile_wiki_pages` | Every passage, Phase 1 |
| `Merger.summary_merge` | `DefaultMerger._call_llm_merge` | Only on a real `Concept.summary` conflict with an `llm_client` configured (D22 layer 2, see `merger.md`) |
| `Merger.summarize_source` | `DefaultMerger._summarize_batch` | Once (or more, if recursion is needed) per source, after all its passages finish Phase 2 — the only stage that sets `round` |
| `Validator.ContentValidate` | `DefaultValidator.content_validate` | Every passage with at least one candidate claim, Phase 2 |
| `Fixer.LLMPeriodicFix` | `DefaultFixer.llm_periodic_fix` | Only when `periodic_fix_due(batch_id)` and there are open content-type entries |

### Thread safety

```python
def __init__(self, pipeline_state_root: Path | str) -> None:
    ...
    self._lock = threading.Lock()

def record(self, ...) -> CostEvent:
    event = CostEvent(...)
    with self._lock, self._path.open("a", encoding="utf-8") as f:
        f.write(event.model_dump_json() + "\n")
    return event
```

D12's Phase 1 runs multiple `Extractor` calls concurrently across threads, all sharing one `JsonlCostLedger`
instance (constructed once in `cli.py::_run_compile`, threaded through every LLM-backed adapter) — without the
lock, concurrent `open("a")` + `write()` calls could interleave. The lock serializes every `record()` call
regardless of which stage or which thread it came from; contention is negligible since each write is a single
small JSON line.

### Reading it back

`read_events() -> list[CostEvent]` reads and parses the whole file (empty list if it doesn't exist yet) — used
by tests and any future cost-rollup tooling. There's no partial/streaming read; for this POC's scale, reading
the whole file back is fine.
