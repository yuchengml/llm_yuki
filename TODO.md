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

### B2. New work from the D20–D23 proposal update (2026-08-27) — not yet implemented

This resolves the gap tracked below in §D2 ("no guaranteed one-page-per-document") — D21 formally reversed
D20 and added a third core type. None of this is built yet.

- [ ] **`Document` core type** (D21, proposal `ARCHITECTURE.md` §1.5) — add to `domain/entities.py`:
      `document_title`/`source_path`/`ingested_at`/`summary`/`produced_claims`/`produced_concepts`/
      `related_pages`. One per D10 Raw Source document.
- [ ] **`Writer.write_document`/`read_document`** — `MarkdownWriter` needs a `documents/` directory,
      analogous to `claims/`/`concepts/`.
- [ ] **`Writer` backlink maintenance for `Document`** — `produced_claims`/`produced_concepts` maintained
      incrementally on write, same mechanism as D18's `Concept.key_facts` (see `_maintain_claim_backlinks`
      in `adapters/writers/markdown_writer.py` for the existing pattern to extend).
- [ ] **`Document.summary` recursive batch-reduce generation** (D21 §1.5, `Merger`'s responsibility, *not*
      folded into any single passage's `Extractor` call) — LLM-backed:
      1. Triggers once all of a document's passages have completed Phase 1 extraction (all its `Claim`s exist).
         `Orchestrator`/`Merger` don't currently track "which document is this passage's Claims from" or
         "are all of a document's passages done" — this bookkeeping doesn't exist yet and needs designing.
      2. Collects the document's `Claim.claim_text`s, checks against a context-window budget (borrowing the
         `context-budget.ts` fixed-ratio-quota approach, per D21) — fits: one LLM call summarizes directly;
         doesn't fit: batch the claims, summarize each batch, recurse on the batch summaries until it fits.
      3. Records cost under `stage="Merger.summarize_document"` (optionally with a `round` field per D21 point 3).
      4. **No convergence-round safety cap** — deliberately unbounded per D21's explicit exclusion; tracked as
         a risk below (ASSUMPTIONS.md B-5).
- [ ] **`Merger` three-layer merge protection** (D22, replaces `DefaultMerger`'s current simple union-everything
      approach for `Concept` updates where `is_new = false`):
      1. Layer 1 (deterministic, already have this): array fields (`aliases`/`tags`/`key_facts`/
         `related_pages`/`related_sources`) — set union, no LLM call.
      2. Layer 2 (LLM merge + rejection, **missing**): only call the LLM to merge `summary` when old and new
         have a real conflict (not just concatenation); if the merged result is `< 70%` of
         `max(len(old), len(new))`, reject it as suspected content loss and fall back to layer 1's result with
         the old `summary` kept. The 70% threshold is borrowed verbatim from `llm_wiki`'s
         `BODY_SHRINK_THRESHOLD` (ASSUMPTIONS.md A-13 — not recalibrated for our data).
      3. Layer 3 (locked fields, **missing**): `concept_title`/`type`/`created` always keep the existing
         value regardless of what layer 2 produced — same "deterministic overrides LLM" principle as D17/D18.
- [ ] **Soft-collision dedup — architecture placeholder only, do not implement** (D22 point 2, ASSUMPTIONS.md
      A-12): leave room in `Merger`'s interface for a future LLM-based "these differently-named candidates are
      probably the same entity" detection pass (modeled on `llm_wiki`'s `dedup.ts`), but this POC deliberately
      ships without it — same treatment as the deepagents skill-swap point (D16). Don't build this; just don't
      design `Merger` in a way that would block adding it later.
- [ ] **Hierarchical `index.md`** (D23, replaces `MarkdownWriter._regenerate_index`'s single flat list):
      - Root `bundle/index.md`: three type-block entry point (`# Claims` / `# Concepts` / `# Documents`),
        each linking to that subdirectory's own `index.md` — no longer lists individual pages itself.
      - `claims/index.md`, `concepts/index.md`, `documents/index.md`: each fully lists that type's pages.
      - Every entry gets a one-line description: `Concept`/`Document` → `concept_title`/`document_title` +
        `summary`; `Claim` → `claim_text` itself (no separate summary field).
      - No deeper nesting than the type level (ASSUMPTIONS.md A-14 — deliberate, OKF allows it, not needed here).
      - Still `Writer`-rendered deterministically from disk + frontmatter, never LLM-generated (same principle
        as D17/D18/D22).
- [ ] **`Validator.structural_validate`: Index Inconsistency check needs rework for D23** — bidirectional diff
      now needs to run per-subdirectory (`claims/`, `concepts/`, `documents/`) plus a root-level check that
      the three type-block links exist and point correctly, instead of the current single flat-list diff.
- [ ] **Missing `Document` page reclassified as Incomplete Pages, not a new error type** (D21 point 5): a Raw
      Source with no corresponding `Document` page is an existing structural error (§4.1 #2, Incomplete
      Pages), not an 8th error category — update `DefaultValidator`'s incomplete-pages check accordingly once
      `Document` exists.

## C. Test coverage gaps (ASSUMPTIONS.md §C)

- [x] Unit tests for **B-3**: `Writer` incremental backlink maintenance (`key_facts` field) — already covered
      in `tests/integration/test_markdown_writer.py`
- [x] Unit tests for **B-4**: body/frontmatter rendering logic (proposal decision D17, direction A) — added
      to `tests/integration/test_markdown_writer.py` (asserts rendered body sections match frontmatter, and
      that empty sections are omitted)
- [ ] Unit tests for **B-5**: `Document.summary` recursive batch-reduce — various `Claim` counts/sizes,
      including the multi-round recursion path, once §B2's implementation lands
- [ ] Unit tests for **B-6**: hierarchical `index.md` rendering — root 3-type-block linking, each subdirectory
      index's completeness, and that each entry's one-line description pulls from the right field
      (`Concept.summary`/`Document.summary`/`Claim.claim_text`)
- [ ] Tests for D22's `Merger` three-layer protection — array union unaffected, LLM-merge-then-70%-rejection
      fallback path, and that locked fields never change regardless of LLM output

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
- Fully-sequential execution as an alternative to Phase 1 parallel / Phase 2 sequential
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
