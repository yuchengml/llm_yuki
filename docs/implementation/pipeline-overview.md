# Pipeline Overview

Module: `domain/pipeline.py::Orchestrator`. Pure domain logic — no filesystem/network access, only calls the
`Connector`/`Writer` ports and the `Extractor`/`Merger`/`Validator`/`Fixer`/`ErrorBook` abstract interfaces
defined in the same file. This is what stays domain-agnostic (AGENTS.md §4): it never contains a line that
knows anything about a specific corpus.

## The abstract interfaces

`Orchestrator` only knows about these four abstract classes (plus `ErrorBook`, covered in
[`error-book.md`](./error-book.md)) — concrete implementations live under `adapters/`:

```python
class Extractor(abc.ABC):
    def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]: ...
    def compile_wiki_pages(self, passage: str, selected: list[str], constraints: list[str], batch_id: int) -> CompiledUpdate: ...

class Merger(abc.ABC):
    def merge(self, update: CompiledUpdate, writer: Writer, batch_id: int) -> CompiledUpdate: ...
    def summarize_source(self, source_slug: str, claim_texts: list[str], writer: Writer, batch_id: int) -> str: ...

class Validator(abc.ABC):
    def structural_validate(self, update: CompiledUpdate, selected: list[str], writer: Writer) -> list[ValidationIssue]: ...
    def content_validate(self, update: CompiledUpdate, passage: str, writer: Writer, batch_id: int) -> list[ValidationIssue]: ...

class Fixer(abc.ABC):
    def code_auto_fix(self, update: CompiledUpdate, structural_issues: list[ValidationIssue]) -> CompiledUpdate: ...
    def llm_periodic_fix(self, error_book: ErrorBook, writer: Writer, batch_id: int) -> None: ...
```

`CompiledUpdate` is the in-flight candidate bundle a passage produces before it's merged/validated/written:

```python
@dataclass
class CompiledUpdate:
    claims: list[Claim] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)
```

Concrete implementations: `LLMExtractor` ([`extractor.md`](./extractor.md)), `DefaultMerger`
([`merger.md`](./merger.md)), `DefaultValidator` ([`validator.md`](./validator.md)), `DefaultFixer` (covered
inline below and in `error-book.md`).

## `run_batch`: the whole algorithm in one method

```python
def run_batch(self, batch_id: int) -> None:
    constraints = self._error_book.active_constraints()
    passages = self._collect_passages()
    source_slugs = _unique_in_order(passage.source_slug for passage in passages)

    phase1_results = self._run_phase1(passages, constraints, batch_id)
    self._ensure_source_pages(source_slugs)

    for result in phase1_results:
        self._run_phase2(result, batch_id)

    self._finalize_source_summaries(source_slugs, batch_id)

    if self._error_book.periodic_fix_due(batch_id):
        self._fixer.llm_periodic_fix(self._error_book, self._writer, batch_id)
        self._error_book.verify_and_close(self._writer, batch_id)
```

Six steps, always in this order:

1. **`active_constraints()`** — pulled once per batch, not per passage. These are `constraint_rule` strings
   from every currently-open `ErrorBookEntry` (see `error-book.md`), injected into every `CompileWikiPages`
   call this batch so the LLM doesn't repeat a previously-diagnosed mistake.
2. **`_collect_passages()`** — reads every source via `Connector.list_sources()`/`read_source()`, splits each
   document's text into natural paragraphs (D11, see `passage-splitting.md`). Produces a flat list of
   `_Passage(source_slug, index, text)` across *all* sources in the batch — a document with 3 paragraphs
   contributes 3 entries; a batch with 2 documents of 2 paragraphs each contributes 4.
3. **`_run_phase1(...)`** — D12 Phase 1, covered below.
4. **`_ensure_source_pages(...)`** — creates a placeholder `Source` page (D21) for every distinct source
   touched this batch, with an empty `summary`. Deliberately happens *after* Phase 1, not before — see
   "Why Source creation waits" below.
5. **Phase 2 loop** — `_run_phase2(result, batch_id)` called once per `_Phase1Result`, in the same order
   `_collect_passages()` produced them (i.e. source order, then paragraph order within a source).
6. **`_finalize_source_summaries(...)`** — after *every* passage in the batch has been through Phase 2 (not
   interleaved with it), regenerates each touched source's `Source.summary` via
   `Merger.summarize_source`. See `merger.md` for the recursive batch-reduce algorithm itself.
7. **Periodic fix** — only if `error_book.periodic_fix_due(batch_id)` (every `periodic_fix_interval` batches,
   default 5, never twice for the same `batch_id`). Runs `Fixer.llm_periodic_fix` then
   `ErrorBook.verify_and_close` — both take the *whole* `ErrorBook`, not a single passage's issues, since this
   is a batch-level maintenance pass, not part of any one passage's compile.

## D12: Phase 1 (parallel) / Phase 2 (sequential)

This is the proposal's two-stage execution strategy, and it maps directly onto two private methods.

### Phase 1 — `_run_phase1` / `_extract_one`

```python
def _run_phase1(self, passages, constraints, batch_id) -> list[_Phase1Result]:
    if not passages:
        return []
    with ThreadPoolExecutor(max_workers=min(self._max_workers, len(passages))) as pool:
        futures = [pool.submit(self._extract_one, passage, constraints, batch_id) for passage in passages]
        return [future.result() for future in futures]

def _extract_one(self, passage, constraints, batch_id) -> _Phase1Result:
    selected = self._extractor.select_pages(passage.text, self._writer, batch_id)
    update = self._extractor.compile_wiki_pages(passage.text, selected, constraints, batch_id)
    return _Phase1Result(passage=passage, selected=selected, update=update)
```

- Every passage in the batch — regardless of which source it came from — is submitted to one
  `ThreadPoolExecutor` and processed concurrently. `max_workers` is a constructor argument (CLI: `--max-workers`,
  default 4); the pool is capped to `min(max_workers, len(passages))` so a small batch doesn't spin up idle
  threads.
- **Genuinely concurrent, not just structurally separated.** `concurrent.futures.ThreadPoolExecutor` uses real
  OS threads; Python's GIL releases during I/O (an HTTP call to the LLM endpoint, a file read), so multiple
  `Extractor` calls actually overlap in wall-clock time. This is proven by a dedicated test
  (`tests/unit/test_orchestrator.py::test_phase1_runs_passages_from_different_sources_concurrently`) that uses
  a 2-party `threading.Barrier` — a fake `Extractor.compile_wiki_pages` blocks until *two* calls are in
  flight at once; a sequential Orchestrator would deadlock and time out instead of completing. Deterministic
  pass/fail, not timing-based.
- `future.result()` is collected **in submission order**, not completion order — so `phase1_results` is
  always in the same order as `passages` (source order, then paragraph order), regardless of which thread
  happened to finish first. This is what makes Phase 2's iteration order deterministic.
- **Read-only against `Writer`.** Nothing is written to the bundle during Phase 1 — `select_pages`/
  `compile_wiki_pages` only ever call `writer.list_pages()`/`read_claim()`/`read_concept()`. Since nothing
  changes underneath it, "the writer's current state during Phase 1" and "a snapshot taken at the start of
  the batch" are the same thing — the proposal's requirement that every Phase 1 passage compare against the
  same index snapshot is satisfied without needing to construct an explicit snapshot object.
- **Consequence — a known gap, not fixed**: because every passage's `SelectPages` sees the *same* pre-batch
  state, two passages of the *same* batch that end up touching the same page (e.g. two paragraphs of one
  document both produce a `Concept` update for the same slug) will each show up as "outside `selected`" once
  Phase 2 processes the second one — a false-positive Unseen Overwrite (see `validator.md`). Tracked in
  `TODO.md` §B3/§D as an extension of the pre-existing `contradicted_by`-recall risk (B-2); not mitigated
  here. Real tests avoid tripping it (a second passage only *links to* an existing page via
  `related_concepts`, never re-declares the same `Concept`).

### Why Source creation waits until after Phase 1

`_ensure_source_pages` runs after `_run_phase1` returns, not before it and not per-passage. Two reasons:

1. **Correctness**: one document's passages are now spread across the whole batch's Phase 1/Phase 2 run
   (interleaved with other documents' passages) — there's no single "this passage's document" moment before
   Phase 2 where creating the page would be both early enough (before any `write_claim`, so backlink
   maintenance can attach) and late enough (after Phase 1, so it doesn't need to exist yet).
2. **Efficiency**: if `Source` pages existed during Phase 1, they'd show up in `writer.list_pages()` and
   get passed to `SelectPages` as "existing pages a passage might be relevant to" — but a freshly-created
   Source has no `summary` yet and `LLMExtractor._describe_page` has no case for it, so it would just cost
   an LLM call for a page with nothing useful to say. Waiting until Phase 2 avoids this for free.

### Phase 2 — `_run_phase2`

```python
def _run_phase2(self, result: _Phase1Result, batch_id: int) -> None:
    passage = result.passage
    update = self._merger.merge(result.update, self._writer, batch_id)

    structural_issues = self._validator.structural_validate(update, result.selected, self._writer)
    content_issues = self._validator.content_validate(update, passage.text, self._writer, batch_id)
    issues = structural_issues + content_issues

    if issues:
        self._error_book.update_error_book(issues, batch_id, self._writer)
        if structural_issues:
            update = self._fixer.code_auto_fix(update, structural_issues)

    claims = _anchor_source_refs(update.claims, passage.source_slug, passage.index)
    self._apply_updates(CompiledUpdate(claims=claims, concepts=update.concepts))
```

Called once per passage, **strictly sequentially** — the `for result in phase1_results` loop in `run_batch`
has no concurrency at all. This is deliberate: `Merger.merge` dedupes against `writer.read_claim`/
`read_concept` (i.e. against whatever the *previous* passage in this same loop just wrote), `Validator`'s
Unseen Overwrite/Index Inconsistency checks read `writer.list_pages()` live, and `Writer.write_claim`/
`write_concept` mutate the bundle on disk — running any of this concurrently would race. Five steps per
passage:

1. `Merger.merge` — dedupe/merge against whatever's currently in the `Writer` (see `merger.md`).
2. `Validator.structural_validate` + `content_validate` — both kinds of lint checks (see `validator.md`).
3. If there were issues: `ErrorBook.update_error_book` (records them, writes `log.md` lines — see
   `error-book.md`), then `Fixer.code_auto_fix` if any were structural (drops/sanitizes problem candidates —
   see below).
4. `_anchor_source_refs` — deterministically overwrites every surviving claim's `source_ref` to
   `<source_slug>#p<passage_index>`, regardless of what the LLM put there. See "Deterministic overrides
   LLM" below.
5. `_apply_updates` — the actual `Writer.write_concept`/`write_claim` calls. Concepts are written before
   claims: `write_claim`'s backlink maintenance looks up each `related_concepts` target and silently skips
   it if that Concept isn't persisted yet, so writing claims first would drop the backlink for any Concept
   created in the very same passage's update.

`code_auto_fix` (in `adapters/fixing/default_fixer.py::DefaultFixer`) is deterministic and conservative — it
never invents content, only removes or sanitizes:

- `unseen_overwrite` / `index_inconsistency` on a slug → drop that whole claim/concept from the update.
- `dangling_links` on a target slug → strip that slug from every `related_concepts`/`contradicted_by`/
  `related_pages` list that referenced it (the claim/concept itself survives).
- `malformed_refs` on a claim → best-effort sanitize (`str.strip()` + collapse internal whitespace to `-`);
  keep the sanitized value only if it now passes `source_ref_well_formed`, otherwise leave the original
  (still-malformed) value in place for the next round's constraint to catch.

Anything `code_auto_fix` can't safely resolve is left as-is; the `ErrorBookEntry`'s `constraint_rule` (see
`error-book.md`) is what actually prevents the LLM from repeating the mistake on a future batch.

## "Deterministic overrides LLM" — `_anchor_source_refs`

```python
def _anchor_source_refs(claims: list[Claim], source_slug: str, passage_index: int) -> list[Claim]:
    new_ref = f"{source_slug}#p{passage_index}"
    return [
        claim if claim.source_ref == new_ref else claim.model_copy(update={"source_ref": new_ref})
        for claim in claims
    ]
```

The LLM has no reliable way to know the real source id or which natural paragraph it's looking at, so
`CompileWikiPages`'s prompt only asks for *something* plausible-looking in `source_ref`. The `Orchestrator`
knows both facts with certainty (they're structural — which source, which paragraph index — not something an
LLM needs to infer), so it overwrites `source_ref` unconditionally after `code_auto_fix` runs (so
`malformed_refs` lint still evaluates the LLM's *original* value first) and before `_apply_updates` (so
`Writer`'s backlink maintenance, which parses the leading `<source_slug>` segment out of `source_ref` to
find the owning `Source`, always gets an exact match). Same principle as D17 (body-link rendering)/D18
(backlink maintenance)/D22 (locked `Concept` fields) — never let an LLM guess at something the code already
knows for certain.

## Batch identity and periodic fix cadence

`batch_id` is caller-supplied (CLI: `--batch-id`, default 1) and threaded through every LLM-backed call purely
for `cost_ledger.jsonl` bookkeeping (see `cli-and-cost-ledger.md`) — it plays no role in extraction/merge/
validation logic itself. `ErrorBook.periodic_fix_due(batch_id)` fires when `batch_id % periodic_fix_interval
== 0` (and never twice for the same `batch_id`, guarding against a re-processed batch); this is the only place
`batch_id`'s numeric value actually changes behavior.
