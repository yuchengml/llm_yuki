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
        Needs a small-scale data check early in scaffolding. Now that Phase 1 parallelism is actually
        implemented (§B3), a second, related same-batch-blind-spot risk was found: a false-positive Unseen
        Overwrite when two passages of one batch touch the same page — see §B3's last bullet.

## B. Core domain logic (fill in the stubs)

> **Implementation note**: the LLM-backed steps (`Extractor.compile_wiki_pages`, `Validator.content_validate`,
> `Fixer.llm_periodic_fix`, and — as of D21/D22 below — `Merger`'s `Document.summary` batch-reduce and
> `Concept.summary` conflict merges) call an **OpenAI-compatible Chat Completions API** — either via
> **OpenRouter**, or a **self-hosted OpenAI-compatible server** (e.g. vLLM, Ollama) — not a vendor-specific
> native SDK, via the `openai` Python package with a configurable `base_url`/`api_key`. See root
> [`ARCHITECTURE.md`](./ARCHITECTURE.md) §2.1/§5 and [`.env.example`](./.env.example).

**Status: the original stub list (below) is fully implemented.** `docs/llm-yuki-v0.1-proposal/` was updated
to D1–D23 after that work landed (D20→D21 added a `Document` core type, D22 specifies `Merger`'s merge
mechanics, D23 restructures `index.md`) — **§B2 below is new, not-yet-implemented work from that update.**
Everything in this first list is checked off; kept as an audit trail of what was built and where — see each
linked module for the concrete class.

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

**Gap found by inspecting a real CLI run's output bundle** (2026-08-27, after the §B2 work above landed):
`bundle/log.md` was only ever initialized with its `# Log` header — `MarkdownWriter.append_log` existed but
nothing called it, so proposal `ARCHITECTURE.md` §4.4's requirement ("每次 `UpdateErrorBook`/`VerifyAndClose`
都要同步寫一筆事件進 `log.md`" — every `UpdateErrorBook`/`VerifyAndClose` call must also write an event to
`log.md`) was silently unmet. Fixed: `append_log` is now part of the abstract `Writer` port (all fake Writers
across the test suite updated); `ErrorBook.update_error_book` gained a required `writer` parameter and writes
one log line per issue (opened or recurring); `ErrorBook.verify_and_close` writes one line per closed entry;
`Orchestrator` passes `self._writer` through. Verified against a real CLI run with a deliberately dangling
`related_concepts` reference — `log.md` now records the same `dangling_links` event that lands in
`error_book.yaml`.

### B2. New work from the D20–D23 proposal update (2026-08-27) — **implemented and verified**

This resolves the gap tracked below in §D2 ("no guaranteed one-page-per-document") — D21 formally reversed
D20 and added a third core type. All items below are built and covered by `pytest`/`mypy`/`ruff` (132 tests,
`poetry run pytest -q` / `poetry run mypy src` / `poetry run ruff check .` all clean).

**Also actually run end-to-end** (2026-08-27), not just unit/integration/e2e-tested: `poetry run llm-yuki
compile` against two small Raw Source documents, pointed at a local OpenAI-compatible mock HTTP server
(live network to OpenRouter is blocked by this sandbox's egress policy — see `/root/.ccr/README.md`; the
mock server is the closest available substitute for "OPENAI_BASE_URL points at a real OpenAI-compatible
endpoint", which is exactly what the CLI itself can't tell apart from a real one). Confirmed on disk: a
`bundle/` with `claims/`/`concepts/`/`documents/` subdirectories, each with its own populated `index.md`;
the root `index.md` linking to all three; `Document` pages with correctly populated `produced_claims`/
`produced_concepts` backlinks; `Claim.source_ref` correctly anchored to the real source id (not whatever the
mock LLM returned); `cost_ledger.jsonl` recording every stage including `Merger.summarize_document`'s `round`
field; and an empty `error_book.yaml` (no structural/content issues on this clean input).

- [x] **`Document` core type** (D21, proposal `ARCHITECTURE.md` §1.5) — added to `domain/entities.py`:
      `document_title`/`source_path`/`ingested_at`/`summary`/`produced_claims`/`produced_concepts`/
      `related_pages`. One per D10 Raw Source document (`slug` = the source's `SourceRef.id`).
- [x] **`Writer.write_document`/`read_document`** — `MarkdownWriter` has a `documents/` directory,
      analogous to `claims/`/`concepts/`.
- [x] **`Writer` backlink maintenance for `Document`** — `produced_claims`/`produced_concepts` maintained
      incrementally on write (`_maintain_document_backlinks` in `adapters/writers/markdown_writer.py`), same
      mechanism as D18's `Concept.key_facts`. Depends on `Claim.source_ref`'s leading `<document-slug>`
      segment matching the real `Document.slug` — see the `Orchestrator._anchor_source_refs` note below.
- [x] **`Document.summary` recursive batch-reduce generation** (D21 §1.5) → `Merger.summarize_document` in
      `adapters/merging/default_merger.py::DefaultMerger`:
      1. **Trigger** (updated 2026-08-29 — see §B3): `Orchestrator._finalize_document_summaries` calls this
         once per document, after *every* passage of that document has gone through Phase 2 (not per-passage;
         a document can now have multiple passages — D11/D12, §B3), using the document's complete
         `produced_claims` backlink to gather every `Claim.claim_text` it produced across all its passages.
      2. Collects the document's `Claim.claim_text`s, checks against a fixed character-count budget
         (`_DOCUMENT_BUDGET_CHARS`, spirit borrowed from `context-budget.ts`, not token-accurate) — fits: one
         LLM call summarizes directly; doesn't fit: batch the claims, summarize each batch, recurse on the
         batch summaries until they fit.
      3. Records cost under `stage="Merger.summarize_document"`, with a `round` field (added to `CostEvent`/
         `JsonlCostLedger.record`, optional/`None` for every other stage) marking the batch-reduce round.
      4. **No convergence-round safety cap** — deliberately unbounded per D21's explicit exclusion; tracked as
         a risk below (ASSUMPTIONS.md B-5).
      5. **Also added, not originally called out**: `Orchestrator._anchor_source_refs` deterministically
         overwrites every compiled Claim's `source_ref` leading id segment with the real source id
         (`document.ref.id`), after `CodeAutoFix` runs (so `malformed_refs` lint still sees the LLM's original
         value) but before `Document`/backlink writes. The Extractor's LLM call has no guaranteed way to know
         the real source id, and `Document` backlink maintenance requires an exact match — this is a new
         instance of the "deterministic overrides LLM" principle (D17/D18/D22), not a design gap.
- [x] **`Merger` three-layer merge protection** (D22) → same `DefaultMerger`, for `Concept` updates where
      `is_new = false`:
      1. Layer 1 (deterministic): array fields (`aliases`/`tags`/`key_facts`/`related_pages`/`related_sources`)
         — set union, no LLM call; `summary` falls back to `new or old`.
      2. Layer 2 (LLM merge + rejection): only calls the LLM to merge `summary` when old and new have a real
         conflict (`_has_real_conflict` — both non-empty, unequal, and neither a substring of the other; a
         substring relationship is treated as simple concatenation, handled by layer 1 alone). If the merged
         result is `< 70%` of `max(len(old), len(new))`, rejects it as suspected content loss and keeps the
         *old* `summary` instead. The 70% threshold is borrowed verbatim from `llm_wiki`'s
         `BODY_SHRINK_THRESHOLD` (ASSUMPTIONS.md A-13 — not recalibrated for our data).
         **`llm_client=None` disables this layer entirely** (falls back to layer 1's `new or old`, same as
         pre-D22 behavior) rather than raising — `merge()` runs unconditionally every passage, unlike the
         periodic-only `llm_periodic_fix`, so it can't require an LLM client to function at all.
      3. Layer 3 (locked fields): `concept_title` always keeps the existing value on merge, regardless of what
         layers 1-2 produce (`type`/`created` aren't domain-model fields in this codebase — OKF frontmatter
         handles `type`, and there's no `created` field on `Concept` — so `concept_title` is the only field
         this layer applies to here).
- [ ] **Soft-collision dedup — architecture placeholder only, do not implement** (D22 point 2, ASSUMPTIONS.md
      A-12): leave room in `Merger`'s interface for a future LLM-based "these differently-named candidates are
      probably the same entity" detection pass (modeled on `llm_wiki`'s `dedup.ts`), but this POC deliberately
      ships without it — same treatment as the deepagents skill-swap point (D16). Don't build this; just don't
      design `Merger` in a way that would block adding it later. *(Confirmed still true: `DefaultMerger`'s
      slug-exact dedup and the new `summarize_document`/three-layer-merge methods don't assume anything about
      slugs being the only way two pages could refer to the same entity — no changes needed to keep this open.)*
- [x] **Hierarchical `index.md`** (D23, replaces `MarkdownWriter._regenerate_index`'s single flat list):
      - Root `bundle/index.md`: three type-block entry point (`# Claims` / `# Concepts` / `# Documents`),
        each linking to that subdirectory's own `index.md` — no longer lists individual pages itself.
      - `claims/index.md`, `concepts/index.md`, `documents/index.md`: each fully lists that type's pages.
      - Every entry gets a one-line description: `Concept`/`Document` → `concept_title`/`document_title` +
        `summary`; `Claim` → `claim_text` itself (no separate summary field).
      - No deeper nesting than the type level (ASSUMPTIONS.md A-14 — deliberate, OKF allows it, not needed here).
      - Still `Writer`-rendered deterministically from disk + frontmatter, never LLM-generated (same principle
        as D17/D18/D22).
- [x] **`Validator.structural_validate`: Index Inconsistency check extended for `Document`** — `Document` joins
      Claim/Concept as a third type whose slug can collide with a compiled candidate's (`_check_index_inconsistency`
      now also checks each candidate Claim/Concept's slug against `writer.read_document`). **Scope note**: the
      proposal's literal definition of this error type (`ARCHITECTURE.md` §4.1 #5) is a full bidirectional diff
      between `index.md` and the filesystem; this codebase's `DefaultValidator` never implemented that — it was
      already scoped down to same-slug-different-type collision detection before D23 (see the type-level
      docstring/`error_book.py`'s `_ROOT_CAUSE_TEMPLATES`), and this pass only extends that existing, narrower
      scope to the new third type. A true `index.md`-vs-filesystem diff (per-subdirectory or otherwise) remains
      unimplemented — pre-existing gap, not introduced or worsened by D23.
- [x] **Missing `Document` page reclassified as Incomplete Pages, not a new error type (D21 point 5) — satisfied
      by construction, no Validator check added.** `Orchestrator._ensure_document_pages` runs unconditionally
      for every source `run_batch` processes (before Phase 2's first write — see §B3 below for why this moved
      off the old per-passage `_compile_passage`), so a processed Raw Source without a `Document` page can't
      occur through this pipeline's normal flow — there's no reachable state for a Validator-side check to
      catch, and `structural_validate`'s signature (`update`/`selected`/`writer`, no source-ref) has no
      natural way to know "which source is this batch currently on" without a broader interface change for a
      condition that's already structurally impossible.

### B3. D11/D12: natural-paragraph passage splitting + Phase 1 parallel / Phase 2 sequential (2026-08-29) — **implemented and verified**

Neither of these was ever actually built — `TxtFileConnector` fed each whole document to the Extractor as a
single "passage" (no paragraph splitting at all, D11 unimplemented), and `Orchestrator.run_batch` processed
one document at a time, fully sequentially end-to-end (D12's two-phase parallel/sequential split
unimplemented — previously listed in this file's "Out of scope" section, which was a mischaracterization:
it was deferred work, not a deliberate scope cut). Now implemented:

- [x] **`domain/passage_splitter.py::split_into_natural_paragraphs`** (D11): blank-line-delimited natural
      paragraphs, pure/no I/O, domain-agnostic. A document with no blank lines becomes exactly one passage
      (still a valid natural unit, per D11) — this is why every pre-existing single-line test fixture kept
      passing unmodified. The real per-corpus splitting rule is still delegated to a future domain skill
      (D3, B-1) — this is only the core pipeline's own baseline default.
- [x] **`Orchestrator` restructured around D12's two phases** (`domain/pipeline.py`):
      1. `_collect_passages`: reads every source via `Connector`, splits each into passages.
      2. Phase 1 (`_run_phase1`/`_extract_one`): `SelectPages`+`CompileWikiPages` for every passage in the
         batch, run concurrently via `concurrent.futures.ThreadPoolExecutor` (`max_workers`, constructor arg,
         CLI `--max-workers`, default 4). Genuinely parallel, not just structurally separated — proven by
         `tests/unit/test_orchestrator.py::test_phase1_runs_passages_from_different_sources_concurrently`
         (a 2-party `threading.Barrier` that only resolves if two Phase 1 calls are in flight at once;
         deterministic pass/fail, not timing-based). Read-only against `Writer` — nothing is written until
         Phase 2, so "current Writer state during Phase 1" and "the batch-start snapshot" are the same thing,
         satisfying the proposal's "各自比對 wiki index 的 snapshot" without needing an explicit snapshot object.
      3. `_ensure_document_pages` (D21): creates every batch's `Document` placeholders once, after Phase 1,
         right before Phase 2's first write — not per-passage any more, since one document's passages are now
         interleaved with other documents' across the whole batch.
      4. Phase 2 (`_run_phase2`, one call per passage, sequential): `Merger`/`Validator`/`ErrorBook`/`Fixer`/
         `ApplyUpdates`, in passage order — matches D12's "序列化執行...避免並發寫入衝突" (serialized, to avoid
         concurrent write conflicts).
      5. `_finalize_document_summaries` (D21 §1.5): after *all* of a batch's Phase 2 writes are done, not
         per-passage — re-reads each touched Document's now-complete `produced_claims` backlink and generates
         its `summary` once. Multi-passage documents previously couldn't exist under the old design, so this
         didn't need to change until now: `Document.summary` must reflect every passage's Claims, not just
         the first one processed.
      6. `_anchor_source_refs` (D17/D18/D22 "deterministic overrides LLM") upgraded from `<document_slug>`
         (optionally keeping whatever locator the LLM guessed) to always `<document_slug>#p<passage_index>` —
         a real, deterministic pointer to which natural paragraph a Claim came from, not an LLM-invented one.
- [x] **`JsonlCostLedger.record` made thread-safe** (`threading.Lock`) — Phase 1 now calls it concurrently
      from multiple `Extractor` calls sharing one ledger instance.
- [ ] **New risk, discovered by implementing D12 properly — extends B-2, not yet mitigated**: when two
      passages *of the same batch* independently produce a candidate touching the *same* existing-by-then
      page (e.g. two paragraphs of one document both emit a `Concept` update for the same slug), the second
      passage's Phase 1 `SelectPages` ran before that page existed (same snapshot problem as B-2's
      `contradicted_by` gap) — so the page is outside its `selected` list, and `StructuralValidate` flags a
      **false-positive Unseen Overwrite** at Phase 2 time, which `CodeAutoFix` then drops entirely, silently
      losing that second candidate's contribution (e.g. a `Concept.summary` merge). Real integration/e2e tests
      deliberately avoid tripping this (second passage only adds a `related_concepts` link, never re-declares
      the same `Concept`) — this is a known gap, not yet exercised as a fixed regression. Needs the same
      small-scale real-data validation as B-2 before deciding whether it's worth `SelectPages`-refreshing
      mid-batch or loosening `Unseen Overwrite`'s check for this specific case.

## C. Test coverage gaps (ASSUMPTIONS.md §C)

- [x] Unit tests for **B-3**: `Writer` incremental backlink maintenance (`key_facts` field) — already covered
      in `tests/integration/test_markdown_writer.py`
- [x] Unit tests for **B-4**: body/frontmatter rendering logic (proposal decision D17, direction A) — added
      to `tests/integration/test_markdown_writer.py` (asserts rendered body sections match frontmatter, and
      that empty sections are omitted)
- [x] Unit tests for **B-5**: `Document.summary` recursive batch-reduce — `tests/unit/test_default_merger.py`
      (empty claims, missing `llm_client`) + `tests/integration/test_default_merger_llm.py` (single-call
      within-budget path, and the multi-round recursion path when over budget)
- [x] Unit tests for **B-6**: hierarchical `index.md` rendering — `tests/integration/test_markdown_writer.py::
      test_index_lists_all_pages` (root 3-type-block linking + each subdirectory index's completeness); each
      entry's one-line description sourcing is exercised by `_claim_index_entries`/`_concept_index_entries`/
      `_document_index_entries` reading the real `claim_text`/`concept_title`+`summary`/`document_title`+
      `summary` fields (no separate dedicated test for the description-sourcing logic in isolation)
- [x] Tests for D22's `Merger` three-layer protection — `tests/unit/test_default_merger.py` (array union
      unaffected, locked `concept_title`, layer-2-skipped-without-`llm_client`) + `tests/integration/
      test_default_merger_llm.py` (LLM-merge-then-70%-rejection fallback path)
- [x] Tests for D11's natural-paragraph splitter — `tests/unit/test_passage_splitter.py` (blank-line breaks,
      multiple-blank-line collapsing, whitespace trimming, empty/whitespace-only input, no-blank-line input
      stays one passage)
- [x] Tests for D12's Phase 1 parallel / Phase 2 sequential execution — `tests/unit/test_orchestrator.py::
      test_phase1_runs_passages_from_different_sources_concurrently` (deterministic 2-party-barrier proof of
      real concurrency, not just structural separation) + `tests/e2e/test_compile_batch.py::
      test_multi_paragraph_document_splits_into_passages_and_aggregates_across_them` (real `MarkdownWriter`:
      per-passage `source_ref` anchoring, cross-passage `Concept.key_facts`/`Document.produced_claims`
      accumulation, single `Document.summary` call after all passages of a document finish Phase 2)

## D. Known risks to watch during implementation

- [ ] **D15** — `Concept` page length has no cap/split rule; watch for context-window issues once real
      `M3SciQA`/`MMDocRAG` data is run through `SelectPages`/`CompileWikiPages`.
- [ ] **D3/D16** — if scaffolding finds the `deepagents` skill-swap mechanism doesn't support the intended
      extension points, the `Connector`/`Extractor`/`Writer` architecture needs to be revisited, not patched.
- [ ] **B-5** (D21) — `Document.summary` batch-reduce has no cap on recursion rounds; a document producing an
      extreme number of `Claim`s could spike latency/cost or loop for a long time. Validate the actual round
      distribution on real `M3SciQA`/`MMDocRAG` data early in scaffolding; add a cap if needed.
- [ ] **B-7** — OKF spec has no pinned version and has grown richer across two independent lookups
      (2026-08-19, 2026-08-27); if it changes again, D6's conformance rules and D23's layered `index.md`
      design may need to follow. Re-check the spec once more right before implementation.
- [ ] **B-2 extension (2026-08-29)** — with D12 Phase 1 parallelism actually implemented (§B3), same-batch
      passages can produce a false-positive Unseen Overwrite when two of them touch the same page (the
      second one's `SelectPages` ran before that page existed) — `CodeAutoFix` then silently drops that
      candidate. See §B3's last bullet for the mechanism; needs the same real-data validation as B-2.

## D2. Known gap vs. the referenced Karpathy/LLM-Wiki methodology — **resolved by D21, superseded**

Kept as an audit trail per this file's own convention (don't delete completed items) — do not act on the
items below, they no longer describe the current decision.

- [x] ~~No guaranteed "one wiki page per source document."~~ **Resolved 2026-08-27 by proposal decision D21**
      (which explicitly reverses an intermediate D20 that had confirmed the gap as intentional). The proposal
      now mandates a `Document` core type — one page per D10 Raw Source — closing exactly the gap described
      below. `ASSUMPTIONS.md` A-11 (which had recorded this as an accepted limitation) has been revoked by D21
      accordingly. **The actual implementation work this now requires is tracked in §B2 above, not here.**
  - Original finding (2026-08-27, this session): Karpathy's original gist (quoted in proposal `README.md`
    D11) describes the ingest loop as: LLM reads the source, **writes a summary page**, updates the index,
    updates related entity/concept pages — three distinct outputs. D9's core schema only formalized two
    types, `Claim` and `Concept`; nothing guaranteed a document got its own representative page. In the
    implementation as it stood then (`adapters/llm/extractor.py::LLMExtractor.compile_wiki_pages`), the LLM
    freely decided what `Claim`/`Concept` candidates to extract from a passage — if everything it extracted
    folded into existing `Concept`s, the source document itself could end up with no page representing it.
  - At the time, this gap had not been caught during the original D9 discussion and was not recorded in
    `ASSUMPTIONS.md` §A the way other deliberate scope cuts are. The decision in this session was to record
    it and leave the behavior as-is pending a proposal-level decision — D20/D21 (made independently, outside
    this session) is that decision.

## E. Validation experiments (SPEC.md Success Criteria)

- [ ] Compilation/maintenance correctness: `index.md` completeness (no orphan/missing pages; as of D23 this
      means the root index plus each of `claims/`/`concepts/`/`documents/`); `log.md` audit trail
      precision/recall against manually injected contradictions
- [ ] Retrieval/reasoning correctness: `M3SciQA`/`MMDocRAG` QA accuracy/F1 vs. a plain vector-RAG baseline
- [ ] Cross-domain portability: core `Claim`/`Concept`/`Document` types (D21) and contradiction pipeline run
      on both domains with no core pipeline changes (only domain-specific customization)
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
- Merging both domains into a single cross-domain bundle
- Manual page-by-page content review, wikilink semantic review, user studies
- `Writer` backends other than filesystem markdown
- Active cost budget/governance alerts (cost ledger is passive recording only)
- Soft-collision dedup implementation (D22) — architecture stays extensible, but no LLM-based fuzzy-entity-match
  detection pass this POC
- A safety cap on `Document.summary` batch-reduce recursion rounds (D21) — deliberately unbounded, tracked as
  risk B-5 instead
- Incremental re-ingest of an already-ingested Raw Source / recomputing its `Document.summary` (D21) — this
  POC assumes each Raw Source is ingested exactly once
- Recalibrating D22's 70% merge-rejection threshold against our own `Concept.summary` length distribution —
  used as borrowed from `llm_wiki` verbatim
- `index.md` nesting deeper than the core-type level, and the optional OKF `okf_version` frontmatter field (D23)
