# TODO

> Consolidated task list for completing the `llm_yuki` POC, derived from
> [`README.md`](./README.md) POC Status, [`docs/llm-yuki-v0.1-proposal/SPEC.md`](./docs/llm-yuki-v0.1-proposal/SPEC.md)
> Success Criteria, and [`docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md`](./docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md) §C.
> This is a working checklist, not a decision record — the reasoning behind each item lives in the proposal docs
> linked inline. Update checkboxes as items complete; do not delete completed items, so this stays an audit trail.

---

## A. Pre-flight (before Phase 2 scaffolding starts)

- [ ] Walk the `ASSUMPTIONS.md` pre-flight checklist end to end, with special attention to:
  - [ ] **B-1** — the `deepagents` skill extension point (`Connector`/`Extractor`/`Writer` swapped in as a
        deepagents skill) is unverified and high-risk. `knowledge-base/frameworks/deepagents-0.7.6/analysis.md`
        is still missing; this was deliberately deferred (README.md proposal, "下一步"), not resolved.
  - [ ] **B-2** — `contradicted_by` recall under Phase 1's parallel extraction is unverified (medium risk).
        Needs a small-scale data check early in scaffolding.

## B. Core domain logic (fill in the stubs)

All of these currently raise `NotImplementedError` or are undefined; see
[`src/llm_yuki/domain/pipeline.py`](./src/llm_yuki/domain/pipeline.py) and
[`src/llm_yuki/domain/error_book.py`](./src/llm_yuki/domain/error_book.py).

- [ ] `Extractor.select_pages` / `Extractor.compile_wiki_pages` — LLM-backed implementation
      (Algorithm 1 lines 1–3; proposal `ARCHITECTURE.md` §2.2.1)
- [ ] `Merger.merge` — dedupe candidates against existing pages, resolve `is_new`
      (proposal `ARCHITECTURE.md` §2.2.2)
- [ ] `Validator.structural_validate` — deterministic checks: dangling links, OKF conformance, etc.
      (proposal `ARCHITECTURE.md` §2.2.3, §4.1)
- [ ] `Validator.content_validate` — LLM-based checks: unsupported facts, cross-page contradictions
      (proposal `ARCHITECTURE.md` §2.2.3, §4.1)
- [ ] `ErrorBook.update_error_book` — Discover + Attribute + Constrain (Algorithm 1 line 8)
- [ ] `ErrorBook.active_constraints` — Inject: open entries' constraint text (Algorithm 1 line 9)
- [ ] `ErrorBook.periodic_fix_due` — cadence check for `LLMPeriodicFix` (Algorithm 1 line 14, §4.3)
- [ ] `ErrorBook.verify_and_close` — re-check open entries, close resolved ones (Algorithm 1 line 16)
- [ ] `ErrorBook` persistence to `pipeline-state/error_book.yaml` (proposal `ARCHITECTURE.md` §4.4)
- [ ] `Fixer.code_auto_fix` — deterministic repair of structural issues, applied every batch
      (Algorithm 1 line 10)
- [ ] `Fixer.llm_periodic_fix` — LLM-driven repair of content issues, every N batches
      (Algorithm 1 line 15, §4.3)
- [ ] `cost_ledger.jsonl` recording (D19) — append-only token usage + wall-clock time per pipeline stage
      (proposal `ARCHITECTURE.md` §7)

## C. Test coverage gaps (ASSUMPTIONS.md §C)

- [ ] Unit tests for **B-3**: `Writer` incremental backlink maintenance (`key_facts` field)
- [ ] Unit tests for **B-4**: body/frontmatter rendering logic (proposal decision D17, direction A)

## D. Known risks to watch during implementation

- [ ] **D15** — `Concept` page length has no cap/split rule; watch for context-window issues once real
      `M3SciQA`/`MMDocRAG` data is run through `SelectPages`/`CompileWikiPages`.
- [ ] **D3/D16** — if scaffolding finds the `deepagents` skill-swap mechanism doesn't support the intended
      extension points, the `Connector`/`Extractor`/`Writer` architecture needs to be revisited, not patched.

## E. Validation experiments (SPEC.md Success Criteria)

- [ ] Compilation/maintenance correctness: `index.md` completeness (no orphan/missing pages); `log.md` audit
      trail precision/recall against manually injected contradictions
- [ ] Retrieval/reasoning correctness: `M3SciQA`/`MMDocRAG` QA accuracy/F1 vs. a plain vector-RAG baseline
- [ ] Cross-domain portability: core `Claim`/`Concept` types and contradiction pipeline run on both domains
      with no core pipeline changes (only domain-specific customization)
- [ ] Differentiation vs. `openwiki`: demonstrable diagnose → root-cause → targeted-fix records that
      `openwiki` has no equivalent for
- [ ] Cost efficiency: `cost_ledger.jsonl`-derived token/time cost not meaningfully worse than vector RAG or
      `openwiki`'s daily full-rebuild cost

Quantitative thresholds for the above are intentionally undecided — SPEC.md defers them to scaffolding-stage
baseline measurements (see SPEC.md "待決定").

## F. Wrap-up

- [ ] Write `RESULT.md` once the POC run completes
- [ ] Write `knowledge-base/decisions/<topic>.md` per repository convention

---

## Out of scope for this POC (do not add back without a new decision)

Per `SPEC.md` Minimal Scope — listed here so nobody "fixes" these as if they were oversights:

- Multimodal/image understanding (no OCR/vision)
- PDF → Raw Sources conversion
- Fixed-length chunk extraction (vs. natural paragraph/concept units)
- Fully-sequential execution as an alternative to Phase 1 parallel / Phase 2 sequential
- Merging both domains into a single cross-domain bundle
- Manual page-by-page content review, wikilink semantic review, user studies
- `Writer` backends other than filesystem markdown
- Active cost budget/governance alerts (cost ledger is passive recording only)
