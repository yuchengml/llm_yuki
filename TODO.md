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

> **Implementation note**: the LLM-backed steps (`Extractor.compile_wiki_pages`, `Validator.content_validate`,
> `Fixer.llm_periodic_fix`) call an **OpenAI-compatible Chat Completions API** — either via **OpenRouter**,
> or a **self-hosted OpenAI-compatible server** (e.g. vLLM, Ollama) — not a vendor-specific native SDK, via
> the `openai` Python package with a configurable `base_url`/`api_key`. See root
> [`ARCHITECTURE.md`](./ARCHITECTURE.md) §2.1/§5 and [`.env.example`](./.env.example).

**Status: all of section B is implemented.** Everything below is checked off; kept as an audit trail of what
was built and where — see each linked module for the concrete class.

- [x] `Extractor.select_pages` / `Extractor.compile_wiki_pages` — LLM-backed implementation
      (Algorithm 1 lines 1–3; proposal `ARCHITECTURE.md` §2.2.1) → `adapters/llm/extractor.py::LLMExtractor`
- [x] `Merger.merge` — dedupe candidates against existing pages, resolve `is_new`
      (proposal `ARCHITECTURE.md` §2.2.2) → `adapters/merging/default_merger.py::DefaultMerger`
      (slug-exact dedupe; semantic/fuzzy dedupe across different slugs is out of scope, see the module docstring)
- [x] `Validator.structural_validate` — deterministic checks: dangling links, OKF conformance, etc.
      (proposal `ARCHITECTURE.md` §2.2.3, §4.1) → `adapters/validation/default_validator.py::DefaultValidator`
- [x] `Validator.content_validate` — LLM-based checks: unsupported facts, cross-page contradictions
      (proposal `ARCHITECTURE.md` §2.2.3, §4.1) → same class, `content_validate`
- [x] `ErrorBook.update_error_book` — Attribute + Constrain (Discover happens in `Validator`; Algorithm 1
      line 8) → `domain/error_book.py`
- [x] `ErrorBook.active_constraints` — Inject: open entries' constraint text (Algorithm 1 line 9)
- [x] `ErrorBook.periodic_fix_due` — cadence check for `LLMPeriodicFix` (Algorithm 1 line 14, §4.3)
- [x] `ErrorBook.verify_and_close` — re-checks dangling_links/incomplete_pages/malformed_refs deterministically;
      unseen_overwrite/index_inconsistency and the two content types are left open (documented in the
      docstring — the first two have nothing meaningful to re-check post-write, the content types need an
      LLM-driven re-verification not yet built) (Algorithm 1 line 16)
- [x] `ErrorBook` persistence to `pipeline-state/error_book.yaml` (proposal `ARCHITECTURE.md` §4.4) →
      `adapters/state/error_book_store.py::YamlErrorBookStore`
- [x] `Fixer.code_auto_fix` — deterministic repair of structural issues, applied every batch
      (Algorithm 1 line 10) → `adapters/fixing/default_fixer.py::DefaultFixer`
- [x] `Fixer.llm_periodic_fix` — LLM-driven repair of content issues, every N batches
      (Algorithm 1 line 15, §4.3) → same class, `llm_periodic_fix`
- [x] `cost_ledger.jsonl` recording (D19) — append-only token usage + wall-clock time, recorded by every
      LLM-backed call (`adapters/cost_ledger.py::JsonlCostLedger`). **Scope note**: only the three genuinely
      LLM-backed calls record cost events; deterministic steps (`StructuralValidate`, `CodeAutoFix`, `Merger`)
      do *not* yet emit the 0-token events proposal §7.2 calls for, since that would mean threading a cost
      port into the domain-pure `Orchestrator`. `JsonlCostLedger.record_call()` exists for that later if wanted.
- [x] LLM client config/env plumbing → `adapters/llm/client.py::OpenAICompatibleClient.from_env()`, reads
      `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`LLM_MODEL`, fails at CLI startup (not mid-batch) if any is unset.
      `.env.example` documents both the OpenRouter and self-hosted cases.
- [x] Wire `llm_yuki.cli compile` to a real `Orchestrator` — `src/llm_yuki/cli.py`, constructs every adapter
      above and runs one batch; `--pipeline-state-dir` controls where `error_book.yaml`/`cost_ledger.jsonl`
      live (defaults to a `pipeline-state` sibling of `bundle_dir`).

**Interface changes made while implementing against the architecture doc** (the original stub signatures in
`domain/pipeline.py` didn't carry enough information to actually implement the spec'd behavior):
`Validator.structural_validate` gained `selected` (needed for Unseen Overwrite); `ErrorBook.verify_and_close`
gained `writer`/`batch_id` (needed to actually re-check anything); `Extractor.select_pages`/
`compile_wiki_pages`, `Validator.content_validate`, and `Fixer.llm_periodic_fix` all gained `batch_id`
(needed for cost-ledger recording); `Validator.content_validate` gained `passage` (needed for source-grounded
Unsupported Facts checking, Algorithm 1's source archive `A`).

**Bug found by the e2e test** (`tests/e2e/test_compile_batch.py`): `Orchestrator._apply_updates` originally
wrote claims before concepts. A claim referencing a concept created in the *same* batch would silently lose
its `related_concepts` backlink, since `Writer.write_claim`'s backlink maintenance (§2.3.2) skips a target
that isn't persisted yet rather than erroring. Fixed by writing concepts first — caught only because the e2e
test exercises the real `MarkdownWriter`, not a fake.

## C. Test coverage gaps (ASSUMPTIONS.md §C)

- [x] Unit tests for **B-3**: `Writer` incremental backlink maintenance (`key_facts` field) — already covered
      in `tests/integration/test_markdown_writer.py`
- [x] Unit tests for **B-4**: body/frontmatter rendering logic (proposal decision D17, direction A) — added
      to `tests/integration/test_markdown_writer.py` (asserts rendered body sections match frontmatter, and
      that empty sections are omitted)

## D. Known risks to watch during implementation

- [ ] **D15** — `Concept` page length has no cap/split rule; watch for context-window issues once real
      `M3SciQA`/`MMDocRAG` data is run through `SelectPages`/`CompileWikiPages`.
- [ ] **D3/D16** — if scaffolding finds the `deepagents` skill-swap mechanism doesn't support the intended
      extension points, the `Connector`/`Extractor`/`Writer` architecture needs to be revisited, not patched.

## D2. Known gap vs. the referenced Karpathy/LLM-Wiki methodology (unresolved, kept as-is for now)

- [ ] **No guaranteed "one wiki page per source document."** Karpathy's original gist (quoted in proposal
      `README.md` D11) describes the ingest loop as: LLM reads the source, **writes a summary page**, updates
      the index, updates related entity/concept pages — three distinct outputs. D9's core schema only
      formalizes two types, `Claim` and `Concept`; nothing guarantees a document gets its own representative
      page. In the actual implementation (`adapters/llm/extractor.py::LLMExtractor.compile_wiki_pages`), the
      LLM freely decides what `Claim`/`Concept` candidates to extract from a passage — if everything it
      extracts folds into existing `Concept`s, the source document itself may end up with no page representing
      it at all.
  - This gap was **not** caught during the D9 discussion and is **not** recorded in `ASSUMPTIONS.md` §A the
    way every other deliberate scope cut is (D9's mention of a domain skill possibly producing `doc:Document`
    is an example of an optional extension type, not a core-pipeline guarantee, and no such skill exists in
    this POC since `Extractor` is domain-agnostic).
  - **Decision (this session): leave the current behavior as-is, do not implement a fix now** — tracked here
    only. If revisited, the options discussed were: (a) make `compile_wiki_pages` guarantee a document-level
    `Concept` (or a new core type) when nothing else represents the document; (b) formally document this as an
    accepted deviation in `ASSUMPTIONS.md` §A, matching this project's own "範疇之外的假設必須顯式記錄"
    principle; (c) both.

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
