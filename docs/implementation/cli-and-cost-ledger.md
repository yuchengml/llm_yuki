# CLI and Cost Ledger

Four mechanisms that don't belong to any single pipeline stage: how the whole thing gets invoked
(`llm_yuki.cli`), how every LLM-backed call's cost gets recorded (`adapters/cost_ledger.py`, D19), how a
whole run's statistics get rolled up into a report (`adapters/stats.py`, D24), and operational console
logging (`llm_yuki.logging`) for watching a run happen in real time.

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
| `--pipeline-state-dir` | `<bundle_dir's parent>/pipeline-state` | Where `error_book.yaml`/`cost_ledger.jsonl`/`stat_<timestamp>.md` live |
| `--max-workers` | `4` | Caps Phase 1's `ThreadPoolExecutor` concurrency — see `pipeline-overview.md` |

### `main()` / `_run_compile()` — what actually happens

```python
def main(argv=None) -> int:
    configure_logging()
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

    before_snapshot = snapshot_bundle(bundle_dir, writer)
    started = time.monotonic()
    orchestrator.run_batch(batch_id)
    e2e_wall_clock_ms = (time.monotonic() - started) * 1000

    error_book_store.save(error_book)

    run_stats = compute_run_stats(
        batch_id=batch_id, bundle_dir=bundle_dir, writer=writer, cost_ledger=cost_ledger,
        error_book=error_book, e2e_wall_clock_ms=e2e_wall_clock_ms, before=before_snapshot,
    )
    write_stats_report(run_stats, pipeline_state_dir)
    return 0
```

Every adapter gets constructed here, once, and shares the *same* `llm_client`/`cost_ledger` instance across
`Extractor`/`Merger`/`Validator`/`Fixer` — which is exactly why `JsonlCostLedger.record` needs to be
thread-safe (Phase 1 calls it concurrently through `LLMExtractor`, see below).

- **`configure_logging()` first, before anything else** — see "Operational Logging" below. Called once, here,
  so every module's `get_logger(__name__)` call (evaluated at import time, throughout `domain/`/`adapters/`)
  has something to propagate up to by the time `run_batch` actually starts producing log records.
- **`.env` auto-loading**: `load_dotenv(find_dotenv(usecwd=True))` runs next, before argument parsing. `usecwd=True` is
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

## Compilation Statistics (D24)

Module: `src/llm_yuki/adapters/stats.py`. Answers "what did this run actually produce, and what did it
cost" as one Markdown report — `pipeline-state/stat_<timestamp>_batch<N>.md`, written once per `compile`
invocation, right after `error_book_store.save(error_book)` in `_run_compile`. Purely a read-only rollup
over data the rest of the pipeline already produces (the bundle itself, `cost_ledger.jsonl`, the in-memory
`ErrorBook`) — it does not change `CostEvent`'s schema, does not touch `Writer`/`Orchestrator`, and never
writes to `bundle/`.

```python
class PageStats(BaseModel):
    total: int             # pages of this core type in bundle_dir right now
    new_this_run: int       # present after this run, absent before it

class LinkFieldStats(BaseModel):
    field: str               # e.g. "Claim.related_concepts"
    total: int
    added_this_run: int

class ComponentStats(BaseModel):
    component: str           # "Extractor" / "Merger" / "Validator" / "Fixer"
    phase_label: str          # inferred from where Orchestrator actually calls that component
    call_count: int
    tokens_in: int
    tokens_out: int
    wall_clock_ms: float
    pct_of_e2e: float | None

class RunStats(BaseModel):
    batch_id: int
    e2e_wall_clock_ms: float
    claims: PageStats
    concepts: PageStats
    sources: PageStats
    link_fields: list[LinkFieldStats]
    components: list[ComponentStats]
    llm_call_count: int
    tokens_in_total: int
    tokens_out_total: int
    errors: list[ErrorTypeRunStats]
```

### How each number is computed

| Stat | Source | How |
|---|---|---|
| `claims`/`concepts`/`sources` | `bundle_dir` before/after `run_batch` (`snapshot_bundle`) | Glob `claims/`/`concepts/`/`sources/*.md` (excluding `index.md`) for slugs, read each back via `Writer.read_claim`/`read_concept`/`read_source`. `total` = after-snapshot size; `new_this_run` = after − before (set difference) |
| `link_fields` | Same two snapshots | Sum the length of each of 9 link-bearing frontmatter fields (`Claim.related_concepts`/`contradicted_by`/`source_ref`, `Concept.key_facts`/`related_pages`/`related_sources`, `Source.produced_claims`/`produced_concepts`/`related_pages`) across every page of that type; `added_this_run` = after-total − before-total. Body wikilinks/`index.md` entries are **not** counted separately — the `Writer` renders both deterministically from these same fields (§2.3.1/§5.4), so counting them too would double-count |
| `components`/`tokens_*`/`llm_call_count` | `cost_ledger.read_events()`, filtered to `batch_id == this run's batch_id` | Grouped by `stage.split(".", 1)[0]` — which, because `Extractor` is only ever called from Phase 1's `ThreadPoolExecutor` and `Merger`/`Validator`/`Fixer` only from Phase 2/periodic-fix, doubles as the Phase 1 vs. Phase 2 breakdown for free. `llm_call_count` only counts events with nonzero tokens (excludes `Validator.StructuralValidate`'s `record_call()` timing-only events) |
| `e2e_wall_clock_ms` | `cli.py`'s own `time.monotonic()` around `orchestrator.run_batch(batch_id)` | Not reconstructed from `cost_ledger` timestamps — Phase 1's concurrent calls have overlapping timestamps, so min/max subtraction would be wrong |
| `errors` | The in-memory `ErrorBook.entries` (not `log.md`) | Grouped by `error_type`; `discovered_at_batch`/`closed_at_batch == batch_id` → this-run counts; `status == "open"` → currently-open total |

`Extractor`'s wall-clock/`pct_of_e2e` can legitimately exceed 100% — it runs in parallel (D12), so several
calls' durations sum to more than the wall-clock time they actually took; `render_stats_report` adds a note
explaining this rather than letting it read as a bug.

### Report structure

Fixed section order: Summary (one auto-generated sentence) → Knowledge Graph Growth (claims/concepts/sources
totals + this-run deltas) → Links (the 9-field table) → LLM Usage (tokens/call count) → Timing by Component
→ Error Book Cross-Reference (only rendered when the run actually touched the Error Book). See
`render_stats_report`/`report_filename`/`write_stats_report` for the exact Markdown produced.

## Operational Logging

Module: `src/llm_yuki/logging.py`. Timestamped console lines on stderr, via Python's standard `logging`
module — for watching a `compile` run happen in real time. **Not the same thing as `log.md`**
(`Writer.append_log`, written by `ErrorBook.update_error_book`/`verify_and_close`, §4.4): that is a durable,
audit-trail artifact inside the OKF bundle, read back for D7's precision/recall validation. This module
produces nothing durable and nothing any pipeline logic reads back — purely operator-facing, and safe to
ignore entirely if you only care about the bundle's contents.

```python
def configure_logging(level: int | str | None = None) -> None: ...  # attach the stderr handler, once
def get_logger(name: str) -> logging.Logger: ...                     # logging.getLogger(name), no side effects
```

- **`configure_logging()`** is called exactly once, as early as possible, only from `cli.py::main` — the
  standard "only entrypoints configure logging, libraries just call `get_logger`" convention. Idempotent about
  the handler (a second call updates the level but never attaches a second handler, so log lines never
  duplicate); level resolves from the explicit argument, else the `LLM_YUKI_LOG_LEVEL` environment variable
  (matching how the rest of the CLI reads config from the environment, see `.env.example`), else `INFO`.
- **`get_logger(name)`** is called at module scope (`logger = get_logger(__name__)`) throughout `domain/` and
  `adapters/`, including `domain/pipeline.py` (`Orchestrator`) and `domain/error_book.py` (`ErrorBook`) — using
  the standard `logging` module from `domain/` does **not** violate that layer's "no filesystem/network I/O"
  module-boundary rule (`.ai/rules/python.md`): that rule targets I/O that needs a `ports/` abstraction to
  keep the domain swappable/testable (`Connector`/`Writer`); stderr logging needs no port and is inert (zero
  output) unless `configure_logging()` has run, so it never affects test behavior or determinism.
- **Format**: `"%(asctime)s %(levelname)-8s %(name)s: %(message)s"`, e.g.
  `2026-08-30T17:04:31+0000 INFO     llm_yuki.domain.pipeline: batch 1: complete`. `name` is always the
  calling module's `__name__`, which — since every module in the package already has a dotted name starting
  with `llm_yuki` — naturally nests under the `llm_yuki` logger `configure_logging` attaches its handler to,
  with no manual prefixing needed.

### Where log lines come from

| Layer | Examples |
|---|---|
| `cli.py` | INFO on compile start/finish; ERROR on `LLMConfigError` (alongside the existing user-facing `print(..., file=sys.stderr)`, not a replacement for it) |
| `domain/pipeline.py` (`Orchestrator`) | INFO batch start/Phase 1 start/periodic-fix/batch complete; DEBUG per-passage extraction counts; WARNING when Phase 2 finds structural/content issues |
| `domain/error_book.py` (`ErrorBook`) | WARNING when a new entry opens, INFO on a recurrence or a close — mirrors the same events `log.md` records, at the operational-visibility layer instead of the audit-trail layer |
| `adapters/cost_ledger.py` (`JsonlCostLedger.record`) | DEBUG per stage call (stage, tokens, wall-clock ms) — the single choke point every `Extractor`/`Merger`/`Validator`/`Fixer` LLM-backed (and timed non-LLM) call already funnels through, so this one hook covers all of them without touching each adapter class individually |
| `adapters/connectors/txt_file_connector.py` | INFO on `list_sources`; DEBUG per `read_source` |
| `adapters/writers/markdown_writer.py` | DEBUG per `write_claim`/`write_concept`/`write_source` |
| `adapters/state/error_book_store.py` | DEBUG/INFO on load; DEBUG on save |
| `adapters/fixing/default_fixer.py` | INFO when `code_auto_fix` actually drops/sanitizes something, or `llm_periodic_fix` runs/applies fixes |

At the default `INFO` level, a `compile` run reads as a clean high-level narrative (batch start → Phase 1 →
any issues found → periodic fix if due → batch complete); `LLM_YUKI_LOG_LEVEL=DEBUG` adds per-passage and
per-LLM-call detail on top, without changing what gets written to `log.md`/`cost_ledger.jsonl`/the bundle —
this is purely an additional, optional, non-durable view onto the same run.
