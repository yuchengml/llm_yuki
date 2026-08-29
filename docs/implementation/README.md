# Implementation Mechanism Docs

> How the pipeline actually works, in code, as of the current `src/llm_yuki/` implementation. This is a
> different layer from [`docs/llm-yuki-v0.1-proposal/`](../llm-yuki-v0.1-proposal/), which is the discussion
> record of *why* each decision (D1–D23) was made — that folder is not modified by these docs and should stay
> the authoritative decision log. These docs describe *how* those decisions ended up implemented: concrete
> modules, method signatures, algorithms, and file formats, so a reader doesn't have to reconstruct the
> mechanism from the source tree or from a hundred decision entries.

Each file below covers one subsystem in depth. Start with [`pipeline-overview.md`](./pipeline-overview.md) for
the end-to-end flow, then drill into whichever stage you need.

| File | Covers |
|---|---|
| [`pipeline-overview.md`](./pipeline-overview.md) | `Orchestrator.run_batch`, Algorithm 1, D12's Phase 1 (parallel) / Phase 2 (sequential) split, the periodic-fix cadence |
| [`core-types.md`](./core-types.md) | `Claim` / `Concept` / `Source` — every field, what writes it, what reads it |
| [`passage-splitting.md`](./passage-splitting.md) | D11's natural-paragraph splitter — the actual extraction unit |
| [`extractor.md`](./extractor.md) | `LLMExtractor`: `SelectPages`/`CompileWikiPages`, prompts, JSON parsing |
| [`merger.md`](./merger.md) | `DefaultMerger`: slug-exact dedupe, D22's three-layer `Concept` merge protection, D21's `Source.summary` recursive batch-reduce |
| [`validator.md`](./validator.md) | `DefaultValidator`: all 5 structural + 2 content error types, exactly what each check does |
| [`error-book.md`](./error-book.md) | `ErrorBook`'s five-phase lifecycle, `log.md` audit-trail writes, YAML persistence |
| [`writer.md`](./writer.md) | `MarkdownWriter`: bundle layout, body rendering, incremental backlink maintenance, D23's hierarchical `index.md` |
| [`cli-and-cost-ledger.md`](./cli-and-cost-ledger.md) | The `llm-yuki compile` CLI, LLM client config, `cost_ledger.jsonl` |

## Reading order for a first pass

1. `pipeline-overview.md` — the shape of one `run_batch` call.
2. `core-types.md` — what a `Claim`/`Concept`/`Source` actually is.
3. `passage-splitting.md` → `extractor.md` — how a passage becomes candidate pages (Phase 1).
4. `merger.md` → `validator.md` → `error-book.md` → `writer.md` — how a candidate becomes a persisted page,
   in the order Phase 2 actually calls them.
5. `cli-and-cost-ledger.md` — how it all gets invoked and what it costs.

## Conventions used across these docs

- Code identifiers are given as `module.py::ClassName.method_name`, relative to `src/llm_yuki/`.
- "D-numbers" (D9, D11, D17, D21, D22, D23, …) reference decisions in the proposal's
  [`README.md`](../llm-yuki-v0.1-proposal/README.md) discussion log — cited so a reader can trace *why*, but
  these docs describe the resulting mechanism, not the discussion that produced it.
- Anything marked **not yet implemented** or **known gap** is also tracked in root
  [`TODO.md`](../../TODO.md) — that file is the up-to-date source of truth for what's outstanding; these docs
  describe what exists today and flag gaps in passing, but don't duplicate the full tracking detail.
