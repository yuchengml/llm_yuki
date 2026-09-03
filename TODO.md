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

### B4. Rename `Document` core type to `Source` (2026-08-29) — **implemented and verified**

The per-Raw-Source navigation page core type introduced by D21 was originally implemented under the name
`Document` (see B2/B3 above — those entries describe work done under that name and are left as-is, per this
file's audit-trail convention). Renamed to `Source` to match the naming `nashsu/llm_wiki` (D21's inspiration)
itself uses, and to stop colliding in spirit with `ports.connector.Document` (the *raw* Connector input text —
an unrelated, unchanged type). Full rename across `src/` and `tests/`, plus every doc under
`docs/implementation/`, root `README.md`, and `ARCHITECTURE.md`:

- [x] `domain.entities.Document` → `Source`; field `document_title` → `source_title`
- [x] `Writer.write_document`/`read_document` → `write_source`/`read_source`
- [x] `MarkdownWriter`'s `documents/` bundle subdirectory → `sources/`; frontmatter `type: Document` →
      `type: Source`; `_maintain_document_backlinks` → `_maintain_source_backlinks`
- [x] `Merger.summarize_document` → `summarize_source`; cost-ledger stage `"Merger.summarize_document"` →
      `"Merger.summarize_source"`
- [x] `Orchestrator._ensure_document_pages`/`_finalize_document_summaries` → `_ensure_source_pages`/
      `_finalize_source_summaries`; `_Passage.document_slug` → `source_slug`
- [x] `ports.connector.Document` (raw Connector input) deliberately left untouched — verified via grep this is
      a distinct, unrelated type
- [x] All 12 affected test files updated; full `mypy`/`ruff`/`pytest` sweep (143 passed) plus a real CLI run
      against a local mock LLM server, confirming `bundle/sources/<slug>.md` with `type: Source` renders
      correctly

### B5. Add a materialized `description` field to `Claim`/`Concept`/`Source`, for `index.md` entries (2026-08-30) — **implemented and verified**

D23's original decision (`docs/llm-yuki-v0.1-proposal/README.md`, D23 point 2) said each `index.md` entry's
one-line description would be *composed at render time* from an existing field — `claim_text` verbatim for
`Claim`, `f"{concept_title}: {summary}"` for `Concept`/`Source` — with no separate field. User feedback asked
for a real, independent `description` in each page's frontmatter instead. This **extends D23 beyond its
literal text** (`docs/llm-yuki-v0.1-proposal/` is the authoritative decision-log record of *why* D1–D23 were
decided and is never edited to reflect later implementation changes, per `AGENTS.md`'s description of that
folder's role — so this deviation from D23's literal text is recorded here instead):

- [x] `Claim.description`/`Concept.description`: new `str = ""` field, **LLM output** — `CompileWikiPages`'s
      (and `LLMPeriodicFix`'s) prompt schema now asks for it explicitly, alongside `claim_text`/`summary`, as
      a short one-sentence index blurb distinct from the (potentially longer) content field
- [x] `Source.description`: new `str = ""` field, **never LLM output** — `MarkdownWriter._write_source_file`
      deterministically overwrites it on every write from `source_title`/`summary`
      (`f"{source_title}: {summary}"`, or just `source_title` while `summary` is still empty), same
      "deterministic overrides LLM" treatment `_anchor_source_refs` gives `source_ref` (D17/D18/D22)
- [x] Merge behavior: `Claim.description`/`Concept.description` merge `new or old`, same as `claim_text` —
      deliberately **not** routed through D22's 3-layer `Concept.summary` protection, since this is index
      metadata, not body content that needs loss-protection
- [x] `MarkdownWriter`'s index-entry builders now read `description`, falling back to the pre-B5 composed
      string when empty (an older bundle written before this field existed, or an LLM that omitted the key)
- [x] `docs/implementation/core-types.md`/`writer.md`/`extractor.md`/`merger.md` updated; new tests in
      `tests/integration/test_markdown_writer.py`; full `mypy`/`ruff`/`pytest` sweep (146 passed) plus a real
      CLI run against a local mock LLM server, confirming `index.md` entries render the LLM-supplied
      description and `Source.description` ignores an LLM-supplied value in favor of the deterministic one

### B6. Stop duplicating `claim_text`/`Concept.summary`/`Source.summary` into frontmatter — content only, body-only (2026-08-30) — **implemented and verified**

User feedback: a page's main free-text field ("content," as opposed to short/structured "metadata") shouldn't
be duplicated into the YAML frontmatter block — YAML is a poor format for multi-line prose, and it was already
being rendered into the body anyway. This **extends D23 beyond its literal text** the same way B5 does (see
B5's note on why the deviation is recorded here rather than in `docs/llm-yuki-v0.1-proposal/`):

- [x] `MarkdownWriter._write_claim_file`/`_write_concept_file`/`_write_source_file`: frontmatter dict now
      built via `model.model_dump(mode="json", exclude={"claim_text"})` (or `{"summary"}` for
      `Concept`/`Source`) — the content field is rendered into the body only, via the existing
      `_render_*_body` methods (unchanged — they already read the in-memory model, not frontmatter)
- [x] New `MarkdownWriter._extract_content(body) -> str`: recovers the content field from a page's body on
      read — scans from the `# <title>` heading to the first `## ...` subsection (or end of body if there is
      none), strips leading/trailing whitespace. Doesn't handle a content value that itself contains a line
      starting with `## ` (not expected in practice — see `writer.md`). **⚠️ 2026-08-30 superseded by B7**:
      that assumption turned out wrong within the same day — see B7, which replaces this scan with a sentinel
      marker once `summary` was allowed to have its own `## ` subsections
- [x] `read_claim`/`read_concept`/`read_source`: now read both frontmatter *and* body from `_read_page`
      (previously discarded body with `frontmatter, _ = ...`), merge `_extract_content(body)` into the
      frontmatter dict under the right key before `Model.model_validate(frontmatter)` — the content field
      would otherwise be missing and fail Pydantic validation
- [x] `description` (B5) stays in frontmatter — it's short index metadata, not body content, so it's
      unaffected by this change
- [x] New tests: frontmatter block asserted to no longer contain `claim_text:`/`summary:` keys;
      multi-paragraph content (embedded blank lines) and content with zero `## ` sections following it (the
      end-of-body edge case) both round-trip correctly through `_extract_content`
- [x] Full `mypy`/`ruff`/`pytest` sweep (148 passed, all pre-existing round-trip tests kept passing
      unmodified — they only ever asserted `read_back == <constructed model>`, never inspected raw
      frontmatter text) plus a real CLI run against a local mock LLM server, confirming the on-disk
      `claims/`/`concepts/`/`sources/*.md` files no longer duplicate `claim_text`/`summary` into frontmatter

### B7. `description` = one refined sentence, `summary` = full write-up with optional subsections; sentinel-based content/section boundary (2026-08-30) — **implemented and verified**

User feedback: `description` (B5) should always be a precisely refined one-liner; `summary` (`Concept`/
`Source`) should be free to be a complete write-up, including markdown subsections, rather than the
one-paragraph cap the prompts and `entities.py` docstrings both enforced. This **extends D23 beyond its
literal text**, same as B5/B6:

- [x] `entities.py`: `Concept.summary`/`Source.summary` docstrings changed from "one-paragraph" to "not
      capped to one paragraph — plain prose or markdown `## ` subsections, LLM/batch-reduce's judgment call"
- [x] `LLMExtractor`'s `_COMPILE_WIKI_PAGES_SYSTEM_PROMPT`: new rule giving the LLM explicit permission (not a
      requirement) to structure `summary` with `## ` subsections when a Concept has multiple distinct facets;
      reaffirms `description` stays a single sentence regardless
- [x] `DefaultMerger`'s `_MERGE_SUMMARY_SYSTEM_PROMPT` (D22 layer 2) and `_SUMMARIZE_SOURCE_SYSTEM_PROMPT`
      (D21 §1.5 recursive batch-reduce): both dropped their hard "one-paragraph" constraint; both now instruct
      the LLM to preserve/merge `## ` subsection structure from either input rather than flattening it back
      into prose when structure is already present. The 70%-length-rejection safety net (D22 layer 2) is
      kept as-is (character-length percentage, not a subsection-aware check) — a deliberate scope decision,
      not an oversight
- [x] `DefaultFixer`'s `_LLM_PERIODIC_FIX_SYSTEM_PROMPT`: added a rule to preserve a concept's existing `## `
      subsection structure while fixing an unrelated content issue, since it must repeat every field in full
- [x] **Real bug found and fixed by a manual CLI smoke run, not by the pre-existing test suite**: B6's
      `_extract_content` (scans for the first line starting with `## ` to find where content ends) breaks the
      moment `summary` legitimately contains its own `## ` subsection — it silently truncates everything past
      that point, since it can't distinguish "the LLM's own subsection heading" from "the Writer's `##
      Related Pages`/etc. sections." Fixed by introducing `_SECTIONS_SENTINEL` (`<!-- llm-yuki:sections -->`,
      an HTML comment invisible when rendered) — `_render_*_body` always writes it between content and the
      Writer's sections, `_extract_content` now splits on the sentinel instead of scanning for a heading
- [x] **A second real bug, same smoke run**: `_source_description`'s `f"{source_title}: {summary}"` breaks
      just as badly once `summary` can be multi-line/multi-section — the composed `description` (and the
      `concepts/index.md`/`sources/index.md` line built from it) ends up containing raw newlines, which
      breaks the one-bullet-per-page `index.md` format. Fixed with a new `_plain_text_snippet(text,
      max_chars=160)` helper (strips `#`/`## ` markers, collapses whitespace/newlines to single spaces,
      truncates with `…`), applied at the single choke point (`_write_type_index`) so it covers every path
      into an index entry — the deterministic `Source` fallback, the `Concept` `concept_title: summary`
      fallback, and even a syntactically-valid but instruction-ignoring LLM-supplied `description`.
      **⚠️ 2026-08-30 superseded by B8**: the `f"{source_title}: ..."`/`f"{concept_title}: ..."` composite
      format itself was wrong, not just its multi-line handling — see B8
- [x] New tests: a `Concept.summary` containing its own `## History`/`## Usage` subsections round-trips
      correctly and the Writer's own `## Key Facts` section is still parsed correctly afterward; a
      `Source.summary` with subsections produces a single-line flattened `description`; a deliberately
      multi-line `description` (simulating an LLM that ignored the "one sentence" instruction) still renders
      as one `index.md` bullet
- [x] Full `mypy`/`ruff`/`pytest` sweep (151 passed) plus two real CLI runs against a local mock LLM server —
      the first one is what caught both bugs above (a `sources/index.md` bullet visibly broken across
      multiple lines); the second, after the fix, confirmed clean single-line `index.md` entries and intact
      multi-section body content

### B8. `description` is always plain discourse, never a `"<name>: <text>"` composite (2026-08-30) — **implemented and verified**

User feedback: `description`, regardless of type, should be one paragraph of discourse — the frontmatter
value must never look like `"Doc 1: This document describes..."`. B7's `_source_description` and the
`Concept` index fallback both baked the page's title into the composed string; this corrects that (the
title/slug is already the index entry's own `[[slug]]` link text, so repeating it is redundant, not just
stylistically off). Extends beyond D23's literal text, same as B5/B6/B7:

- [x] `MarkdownWriter._source_description`: dropped the `f"{source_title}: ..."` prefix — now just
      `_plain_text_snippet(source.summary)` when `summary` is non-empty, or `""` (not `source_title`) when it
      isn't. This is a real behavior change, not cosmetic: `Source.description` in frontmatter used to always
      contain the title; it no longer does, ever
- [x] `MarkdownWriter._concept_index_entries`'s fallback (used only when `Concept.description` is empty):
      changed from `f"{concept_title}: {summary}"` to `summary` alone — this fallback was never written to
      frontmatter (only into a transient `index.md` display string), but the same "no name prefix" principle
      applies to it for consistency
- [x] `MarkdownWriter._write_type_index`: when the flattened description is empty (a fresh `Source` with no
      `summary` yet), the entry renders as bare `[[slug]]` — no trailing `— ` with nothing after it, which is
      what a naive `""`-becomes-`""`-after-title-removed would have produced
- [x] `entities.py`: `Source.description` field docstring updated to state the "plain discourse, never a
      composite" rule explicitly
- [x] 4 pre-existing tests updated (they asserted the old `"Doc 1: ..."`/`"Water: ..."` format); 1 new test
      added for the bare-`[[slug]]`-when-empty rendering
- [x] Full `mypy`/`ruff`/`pytest` sweep (152 passed) plus a real CLI run against a local mock LLM server,
      confirming `Source.description` in the actual `.md` frontmatter is now pure discourse with no
      `doc-eiffel: ` prefix

### B9. Operational console logging (2026-08-30) — **implemented and verified**

User request: write logs for the appropriate parts of a compile run, via a dedicated module defining the log
format and a `get_logger()` helper. This is a genuinely new mechanism, not covered by any proposal decision
(D1–D23 never discuss operational logging — only `log.md`, the durable domain audit trail, D14/§4.4) — so
there is no D-number/literal-text this extends, unlike B5–B8.

- [x] New `src/llm_yuki/logging.py`: `configure_logging(level=None)` (attaches one stderr `StreamHandler` to
      the `llm_yuki` logger namespace, idempotent about the handler; level resolves from the argument, else
      `LLM_YUKI_LOG_LEVEL` env var, else `INFO`) + `get_logger(name)` (thin `logging.getLogger(name)`
      passthrough, no side effects — the standard "libraries don't configure logging" convention). Format:
      `"%(asctime)s %(levelname)-8s %(name)s: %(message)s"`
- [x] **Explicitly not `log.md`**: that remains `Writer.append_log`'s durable, OKF-bundle-adjacent audit
      trail (read back for D7 validation); this module produces nothing durable and nothing any pipeline
      logic reads back — purely operator-facing stderr output. Documented as such in both places to avoid
      future confusion between the two
- [x] Using the standard `logging` module from `domain/pipeline.py`/`domain/error_book.py` does **not**
      violate those modules' "no filesystem/network I/O" rule (`.ai/rules/python.md`) — that rule is scoped
      to I/O needing a `ports/` abstraction for testability (`Connector`/`Writer`); stderr logging needs no
      port and is inert (zero output) unless `configure_logging()` has run, so it never affects test
      behavior/determinism. Documented inline in `logging.py`'s module docstring
- [x] `cli.py` calls `configure_logging()` first thing in `main()`; logs compile start/finish and the
      `LLMConfigError` path (alongside, not replacing, the existing user-facing `print(..., file=sys.stderr)`)
- [x] Logging added at the "appropriate parts" across every layer: `domain/pipeline.py` (`Orchestrator`) —
      batch/Phase 1 start, periodic-fix trigger, batch complete (INFO), per-passage extraction (DEBUG),
      structural/content issues found (WARNING); `domain/error_book.py` (`ErrorBook`) — entry
      opened/recurrence/closed, mirroring the same events already written to `log.md`;
      `adapters/cost_ledger.py`'s `record()` — a single DEBUG choke point covering every
      `Extractor`/`Merger`/`Validator`/`Fixer` LLM-backed (and timed non-LLM) call, so no need to instrument
      each adapter class separately; `adapters/connectors/txt_file_connector.py`, `adapters/writers/
      markdown_writer.py`, `adapters/state/error_book_store.py` — lighter-touch INFO/DEBUG on
      list/read/write/load/save
- [x] New `tests/unit/test_logging.py` (8 tests): handler attachment/idempotency, level resolution
      (explicit arg > env var > default), no side effects from `get_logger` alone, child-logger propagation
      to the configured root. Uses an autouse fixture to reset the module-global handler/level state before
      and after each test, since `configure_logging` is a process-wide side effect otherwise shared with
      `tests/unit/test_cli.py` (which also exercises `main()`)
- [x] Full `mypy`/`ruff`/`pytest` sweep (160 passed, 32 source files) plus a real CLI run at both `INFO` (the
      default) and `LLM_YUKI_LOG_LEVEL=DEBUG`, confirming the format renders correctly, DEBUG lines are
      genuinely suppressed at INFO, and the log stream reads as a coherent narrative of the batch

### B10. Query module (D25): modular multi-strategy retrieval + agentic iteration, plus a dataset-agnostic QA evaluation harness (2026-08-30) — implemented and verified

`docs/llm-yuki-v0.1-proposal/QUERY-SEARCH-SURVEY.md` found that the Query circle (Karpathy's third, after
Ingest/Compile and Lint) had never been decided or built — D8's success criteria need it to actually run
`M3SciQA`/`MMDocRAG` QA pairs, but nothing in `ARCHITECTURE.md` covered it. This work opens and implements
D25 (proposal `README.md`), then builds the QA-scoring harness D25 makes runnable. Full `mypy src`/`ruff
check`/`ruff format --check`/`pytest` sweep: 233 tests passed, 93%+ line coverage (well above the 60%
threshold), `mypy --strict` clean across all 40 source files.

- [x] **`domain/query.py`** — `PageRecord`/`load_corpus` (the only function here touching `Writer`),
      `SearchStrategy` ABC + `StructuredSignalSearch` (structured-fields-first keyword search, matching the
      LLM-Wiki paper's `wiki_search` description), `reciprocal_rank_fusion`/`graph_result_quota`/
      `expand_via_wikilinks` (RRF + one-hop graph expansion, formulas borrowed from `nashsu/llm_wiki`'s
      `search.rs` per the survey's §3.2), `AnswerSynthesizer`/`NextActionDecider` ABCs, and two swappable
      top-level `QueryEngine`s: `SinglePassQueryEngine` (search → fuse → graph-expand → read → synthesize,
      once) and `IterativeAgenticQueryEngine` (`wiki_search`/`wiki_read` loop, `T_max`/patience termination,
      reconstructed from the survey's §2 pseudocode of the LLM-Wiki paper's own algorithm).
- [x] **Embedding retrieval deliberately not implemented** (D25 decision 1, explicit user instruction this
      session) — `adapters/query/embedding_search.py::EmbeddingSearch` implements `SearchStrategy` but its
      `search()` always raises `NotImplementedError`. Same "leave room, don't build it" treatment D16 gives
      the `deepagents` skill-swap point and D22 gives soft-collision dedup.
- [x] **`adapters/llm/answer_synthesizer.py::LLMAnswerSynthesizer`** / **`adapters/llm/
      next_action_decider.py::LLMActionDecider`** — same shape as `LLMExtractor` (prompt, JSON parse via
      `json_utils.parse_json_object`, `LLMOutputError` on schema mismatch, cost recorded via
      `JsonlCostLedger`). Citations are mandatory (D25 decision 3): `cited_slugs` is required in the
      synthesizer's response schema, filtered against the pages actually provided (hallucinated-slug
      filtering, same precedent as `Extractor.select_pages`) rather than treated as fatal.
- [x] **`llm-yuki query <bundle_dir> "<question>"`** CLI subcommand (`--method single-pass|agentic`,
      `--top-k`, `--t-max`, `--patience`) — read-only against `bundle_dir`, shares the `compile`/existing
      `query` subcommands' LLM-config fail-fast behavior (`src/llm_yuki/cli.py::_run_query`).
- [x] **Query results are not written back to the wiki this POC** (D25 decision 4) — `QueryEngine.answer`
      only reads through `Writer`, never calls a `write_*` method. `ASSUMPTIONS.md` A-15/A-16 record both
      scope cuts (embedding unimplemented, no write-back).
- [x] **`docs/implementation/query.md`** (new) — full mechanism doc, added to the reading order in
      `docs/implementation/README.md`. `docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md` §8 and root
      `ARCHITECTURE.md` also updated with the module design/map (proposal docs are the decision-log layer,
      updated because D25 is a genuinely new decision, not a later deviation from an existing one — unlike
      B5–B9 above).
- [x] **`evaluation/qa_metrics.py`/`evaluation/qa_runner.py`** (new top-level package, outside
      `domain`/`ports`/`adapters` — evaluation tooling, not core pipeline logic, same status `cli.py` has) —
      standard SQuAD-style EM/F1 scoring (`normalize_answer`/`exact_match`/`f1_score`/`best_exact_match`/
      `best_f1`, multi-reference-gold aware) plus `load_qa_examples`/`run_qa_evaluation`/`EvaluationReport`
      wired to any `QueryEngine`. New `llm-yuki evaluate-qa <bundle_dir> <qa.jsonl>` CLI subcommand
      (`--output` writes the full JSON report). `docs/implementation/evaluation.md` documents it and lays out
      the still-outstanding steps for a real run.
- [ ] **Not done this session — explicit follow-up, not an oversight**: the harness is dataset-agnostic and
      proven correct against a small synthetic bundle+QA set (`tests/e2e/test_evaluate_qa_batch.py`), but
      `M3SciQA`/`MMDocRAG` themselves are not vendored or converted, so no real-benchmark EM/F1 numbers exist
      yet. Needed before Section E below can be checked off: (a) a dataset-specific conversion script per
      benchmark (raw files → D10 Raw Source folders, QA pairs → this harness's JSONL shape), (b) `llm-yuki
      compile` each converted corpus, (c) `llm-yuki evaluate-qa` each bundle for both `QueryEngine`s, (d) a
      separate simple vector-RAG baseline for the D8 comparison (out of scope for the Query module itself,
      since D25 leaves embedding retrieval unimplemented — this baseline needs its own harness). See
      `docs/implementation/evaluation.md`'s "What 'done' looks like" section for the concrete task list.
- [x] **`scripts/musique_subset_to_raw_sources.py`** (D26, 2026-08-31) — user question ("MuSiQue 資料集是沒有
      原始文件的嗎") surfaced that MuSiQue's per-question-paragraph structure doesn't fit the "shared corpus"
      model `M3SciQA`/`MMDocRAG` use; user then asked to try converting a MuSiQue subset into a bundle and
      running evaluation anyway. Converts MuSiQue questions (sample mode, default 20; or `--full-corpus` for
      all 1000) into D10 Raw Source folders + an `evaluate-qa` JSONL. Data source: `OSU-NLP-Group/HippoRAG`'s
      `reproduce/dataset/musique.json` (MuSiQue's own Google Drive distribution was unreachable from this
      environment's egress policy) — verified by cloning that repo directly, and by confirming programmatically
      that its 1000 questions' paragraphs, deduplicated, exactly match its separate `musique_corpus.json`
      (11,656 entries either way). **Verified end-to-end this session**: downloaded the real data, sampled 5
      questions, generated 100 Raw Source documents + a QA JSONL, round-tripped both through the real
      `TxtFileConnector.read_source`/`load_qa_examples` — confirmed genuinely valid pipeline input.
      **Not done**: an actual `compile`/`evaluate-qa` run — no real `OPENAI_API_KEY`/`OPENAI_BASE_URL`/
      `LLM_MODEL` available in this session. Sample-mode EM/F1 is explicitly not comparable to published
      MuSiQue baselines (D26 decision 3) — only a `--full-corpus` run is. See `docs/implementation/
      evaluation.md`'s "MuSiQue subset experiment" section.
- [ ] **`T_max`/`patience` defaults (6/2) are untuned placeholders** — same treatment as D15/B-5's other
      untuned constants: validate against real `M3SciQA`/`MMDocRAG` data once available, adjust if the
      agentic loop terminates too early/late in practice.
- [x] **`llm-yuki search` CLI subcommand + `domain/query.py::retrieve`** (2026-08-30, same-day follow-up) —
      user feedback: the CLI should be able to run search on its own. `retrieve()` (search->fuse->
      graph-expand, no synthesis) was pulled out of `SinglePassQueryEngine.answer` into a standalone public
      function it now calls instead of duplicating the steps; `llm-yuki search <bundle_dir> "<query>"
      [--top-k N]` runs it directly — no `OPENAI_*`/`LLM_MODEL` config needed at all, since it never
      constructs an LLM client. This is the one query-module entry point that's actually runnable in an
      environment with no LLM endpoint configured (verified live: `poetry run llm-yuki search <bundle>
      "<query>"` against a manually-seeded bundle, no `.env`, real stdout). `query`/`evaluate-qa` still need
      real LLM config (synthesis is inherently LLM-backed). 240 tests passing (up from 233), same mypy/ruff
      clean, 93%+ coverage.
### B11. Compilation statistics report: entities/concepts/sources/links/token usage/LLM call count/timing, per compile run (D27, 2026-09-01) — **implemented and verified**

Developed on `develop` directly (in parallel with this branch's B10 work above) under the number "D24"/"B10"
— renumbered to D27/B11 when merging the two branches, since both had independently picked the next
available number from the same D23/B9 common ancestor. See proposal `README.md`'s D27 for the full
renumbering note; content below is otherwise unchanged from how it landed on `develop`.

User request: every compile run should track entities, concepts, sources, links, token usage, LLM call
count, e2e compile time, and per-component compile time, and output a report after every run
(`stat_<datetime>.md`). D19 already covers token/time cost recording (`cost_ledger.jsonl`) but not
entities/concepts/sources/links, and there was no rollup-report mechanism — new decision (D27), not a
revision of D19.

- [x] New `src/llm_yuki/adapters/stats.py`: `BundleSnapshot`/`snapshot_bundle` (globs `claims/`/`concepts/`/
      `sources/*.md`, reads pages back via `Writer.read_claim`/`read_concept`/`read_source`, sums 9
      link-bearing frontmatter fields); `RunStats`/`compute_run_stats` (diffs two snapshots for
      entities/concepts/sources/links, filters `cost_ledger.read_events()` to this run's `batch_id` for
      tokens/LLM-call-count/per-component timing, cross-references `ErrorBook.entries` for lint findings);
      `render_stats_report`/`report_filename`/`write_stats_report`
- [x] **Deliberately does not extend `CostEvent`'s schema or touch `Writer`/`Orchestrator`** — a pure
      read-only rollup over data D9/D14/D19/D21/D23 already produce. Component grouping (`stage.split(".",
      1)[0]`) doubles as the Phase 1/Phase 2 breakdown for free, since `Extractor` is only ever called from
      Phase 1's `ThreadPoolExecutor` and `Merger`/`Validator`/`Fixer` only from Phase 2/periodic-fix in
      `domain/pipeline.py`
- [x] `cli.py::_run_compile`: snapshot `bundle_dir` before `run_batch`, time the whole call with
      `time.monotonic()` (not reconstructed from `cost_ledger` timestamps — Phase 1's concurrent calls
      overlap), write the report after `error_book_store.save`
- [x] New `tests/unit/test_stats.py` (pure logic: component grouping, error cross-referencing, report
      rendering) + `tests/integration/test_stats_bundle.py` (real `MarkdownWriter` bundle + `JsonlCostLedger`
      round trip); `tests/integration/test_cli_compile.py` gained an assertion that a `stat_*.md` file is
      actually produced
- [x] Full `mypy --strict`/`ruff`/`pytest` sweep (179 passed, 93.8% coverage, `adapters/stats.py` itself at
      96%) — on `develop` before this merge; re-run after merging with B10's work above, see the merge
      commit's own sweep numbers.

### B12. Phase 1 two-level concurrency: bound "documents open at once" independently of worker-pool size (2026-09-02) — **implemented and verified**

User request: with real batches, Phase 1's original flat design (every passage of every source submitted to
one pool at once, D12/B-3) made "how many documents are being touched right now" and "how many workers exist"
the same number — no way to keep memory/log footprint predictable for a big document while still letting
many workers race through its passages, or vice versa. Extends D12's Phase 1 scheduling (not a new
D-numbered decision — the phase split, the "fully completes before Phase 2" guarantee, and the "read-only
against a stable snapshot" property are all unchanged, only *which passages get submitted when* changes).

- [x] `domain/pipeline.py::Orchestrator`: new constructor param `max_concurrent_documents` (CLI
      `--max-concurrent-documents`, default 4, same default as `max_workers`) alongside the existing
      `max_workers`. `_run_phase1` restructured into sliding-window scheduling: passages grouped by
      `source_slug`; up to `max_concurrent_documents` sources "open" (all their passages submitted to one
      shared `ThreadPoolExecutor`) at once; `concurrent.futures.wait(..., return_when=FIRST_COMPLETED)` drives
      a loop that opens the next queued source the instant an open source's passages all finish. `max_workers`
      sizes the pool and is independent of the document window — can exceed it (many workers on one open
      document) or sit below the open documents' combined passage count (passages simply queue for a free
      worker, no polling). Final result list is reconstructed in original `passages` order (a
      `dict[_Passage, _Phase1Result]`, keyed off `_Passage`'s frozen/hashable dataclass) regardless of
      completion order — preserves the pre-existing invariant Phase 2 and its tests depend on.
- [x] `cli.py`: `--max-concurrent-documents` flag, threaded through `_run_compile` into `Orchestrator`; INFO
      log line reports both knobs.
- [x] `tests/unit/test_orchestrator.py`: the pre-existing 2-party-barrier concurrency proof
      (`test_phase1_runs_passages_from_different_sources_concurrently`) still passes unmodified under the new
      defaults (2 sources ≤ default window of 4, so both still open immediately). Two new deterministic
      tests: `test_phase1_runs_one_documents_passages_concurrently_when_worker_pool_exceeds_document_window`
      (3-party barrier, one document/3 passages, `max_concurrent_documents=1`/`max_workers=3` — proves a
      worker pool larger than the document window still saturates one open document's passages) and
      `test_phase1_never_opens_more_documents_than_max_concurrent_documents` (a locked shared counter across
      4 single-passage documents, `max_workers=4`/`max_concurrent_documents=2` — proves observed concurrency
      peaks at exactly 2, never 4).
- [x] `docs/implementation/pipeline-overview.md`: Phase 1 section rewritten for the two-level model (full
      `_run_phase1` code, the three concurrency tests, the document-window/worker-pool interaction).
      Root `README.md`/`ARCHITECTURE.md` and `docs/implementation/cli-and-cost-ledger.md` updated wherever
      they described the old flat `--max-workers`-only behavior.
- [x] Full `mypy --strict`/`ruff check .`/`pytest` sweep: 261 passed, no lint/type errors.

### B13. Fix body/index link notation: `[[slug]]` wikilink syntax → standard markdown link (D17, 2026-09-03) — **implemented and verified**

User asked "what names do the three page types' frontmatter use to represent links to other pages" — while
answering, found and confirmed a real deviation from an already-decided text: D17 (proposal `README.md`)
explicitly inventories the body-link mechanism as "**標準 markdown link**" (standard markdown link), but the
actual `MarkdownWriter` implementation rendered every cross-page link as `[[slug]]` — Obsidian/wiki-style
double-bracket notation, which is *not* standard markdown and doesn't render as a clickable link in GitHub or
any plain markdown viewer. This is not a new decision — D17's own text already said what the format should
be — so no new D-number; it's a bug-fix bringing the implementation back in line with the decision it always
claimed to follow, same pattern as B5–B12 above.

- [x] `adapters/writers/markdown_writer.py`: new `_wiki_link(slug, from_dir, to_dir)` helper renders
      `[slug](relative/path.md)` — same-directory (`<slug>.md`) when `from_dir == to_dir`, one level over
      (`../<to_dir>/<slug>.md`) otherwise (the three type directories are flat siblings under the bundle
      root, so no deeper case exists). Replaces every `f"- [[{slug}]]"` call site: `_render_claim_body`
      (`related_concepts` → concepts/), `_render_concept_body` (`key_facts` → claims/, `related_pages` →
      concepts/), `_render_source_body` (`produced_claims` → claims/, `produced_concepts` → concepts/,
      `related_pages` → sources/), and `_write_type_index` (every `index.md` entry, always same-directory).
- [x] **Verified against the actual code, not assumed from field names** — this surfaced two pre-existing
      inconsistencies unrelated to the bracket-vs-markdown question itself, both left as-is (out of scope for
      a pure notation fix) and documented in `docs/implementation/core-types.md`'s new "How pages link to
      each other" table:
      1. `Claim.contradicted_by` is a slug-bearing field but has **no body section at all** — only
         `Concept.key_facts`/`related_pages`/`Source.produced_claims`/`produced_concepts`/`related_pages`/
         `Claim.related_concepts` are actually rendered.
      2. `Concept.related_sources` was already inconsistent with every other link field *before* this
         fix — rendered as a bare unlinked string (`f"- {src}"`, no brackets at all, deterministic-overrides-
         LLM), not because it isn't a slug but because the `CompileWikiPages` prompt doesn't require it to
         resolve like `related_pages` does, and `entities.py`'s own docstring calls it a vaguer "Source/
         provenance digest link". `domain/query.py`'s graph expansion nonetheless walks it exactly like the
         other backlink fields. Left unchanged; flagged as a real but separate gap.
- [x] Updated every place that echoed the old notation: `entities.py`'s `Source.description` docstring,
      `markdown_writer.py`'s `_source_description` docstring, `docs/implementation/writer.md` (page-format
      example, body-rendering section, index.md section), `docs/implementation/core-types.md` (new
      link-mapping table + the one inline mention in "What's not an LLM-editable field").
- [x] `tests/integration/test_markdown_writer.py` (every `[[slug]]` assertion → `[slug](...)`, cross-directory
      paths for body sections, same-directory for index entries) + `tests/e2e/test_compile_batch.py` (one
      body assertion). No test asserted on the literal `related_sources`/`contradicted_by` rendering, so
      neither needed a change beyond the notation fix itself.
- [x] Full `mypy --strict`/`ruff check .`/`pytest` sweep: 261 passed, no lint/type errors.

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
- [ ] Retrieval/reasoning correctness: `M3SciQA`/`MMDocRAG` QA accuracy/F1 vs. a plain vector-RAG baseline.
      **Mechanism now exists (§B10, D25)** — `llm-yuki evaluate-qa` + `evaluation/qa_runner.py` can produce
      this number for any bundle/QA-JSONL pair; what's still missing is the dataset acquisition/conversion
      work itself (see §B10's last bullet and `docs/implementation/evaluation.md`), plus the vector-RAG
      baseline harness to compare against.
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
- A real `EmbeddingSearch` implementation (D25) — the `SearchStrategy` interface accommodates one, but no
  embedding provider is wired up this POC; `search()` always raises `NotImplementedError`
- Writing `QueryEngine` answers/query results back into the wiki as new pages (D25) — Query is read-only this
  POC; `QueryEngine.answer` never calls a `Writer.write_*` method
- Throughput/latency comparison between `SinglePassQueryEngine` and `IterativeAgenticQueryEngine` (D25) —
  both exist to each be validated against `M3SciQA`/`MMDocRAG`, not to be benchmarked against each other
- Locking in specific `T_max`/patience numbers for `IterativeAgenticQueryEngine`, or a formal query-latency
  SLA (D25) — left as constructor/CLI-tunable defaults, see §B10's last bullet
