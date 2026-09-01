# Error Book

Module: `domain/error_book.py::ErrorBook` (pure, in-memory, no I/O) + `adapters/state/error_book_store.py::
YamlErrorBookStore` (the only thing that reads/writes it to disk) + `MarkdownWriter.append_log`
(`adapters/writers/markdown_writer.py`, the `log.md` audit trail — covered here rather than in `writer.md`
since it's `ErrorBook`'s output, not a bundle-content concern). Implements the proposal's five-phase lint
lifecycle (§4.2): **Discover → Attribute → Constrain → Inject → Verify&Close**.

## The seven error types

```python
ErrorType = Literal[
    "dangling_links", "incomplete_pages", "malformed_refs", "unseen_overwrite", "index_inconsistency",  # structural
    "unsupported_facts", "cross_page_contradictions",  # content
]
```

Discovery itself happens in `Validator` (`validator.md`), against an in-flight `CompiledUpdate` — `ErrorBook`
never inspects a `CompiledUpdate` directly. It receives already-discovered `ValidationIssue` objects
(`{error_type, phenomenon, affected_refs}`) and owns everything from Attribute onward.

## `ErrorBookEntry` — one row of `pipeline-state/error_book.yaml`

```python
class ErrorBookEntry(BaseModel):
    id: str
    error_type: ErrorType
    phenomenon: str
    affected_refs: list[str] = []
    root_cause: str | None = None
    constraint_rule: str | None = None
    verification_method: str | None = None
    status: Literal["open", "closed"] = "open"
    discovered_at_batch: int
    closed_at_batch: int | None = None
```

## Phase by phase

### Discover — `Validator`, not `ErrorBook`

Covered in `validator.md`. Produces the `list[ValidationIssue]` that every other phase below consumes.

### Attribute + Constrain — `update_error_book`

```python
def update_error_book(self, issues: list[ValidationIssue], batch_id: int, writer: Writer) -> list[ErrorBookEntry]:
```

Called once per passage from `Orchestrator._run_phase2`, only when `issues` is non-empty. For each issue:

- **Deduplicates against existing open entries** of the same `(error_type, phenomenon)` — a recurring
  mistake merges its `affected_refs` into the existing entry (`existing.affected_refs.append(ref)` for any
  new ref) rather than creating a fresh row, so the book doesn't flood with duplicates of the same underlying
  problem. `discovered_at_batch` on the existing entry is left unchanged (it stays the *original* discovery
  batch).
- **Otherwise, opens a new entry**: `root_cause` is looked up from a fixed, type-level template dictionary
  (`_ROOT_CAUSE_TEMPLATES` — e.g. `"dangling_links"` → `"A page referenced via a link/related_concepts/
  contradicted_by entry was never written."`), and `constraint_rule` is derived from it mechanically:
  `f"Avoid recreating this issue: {root_cause}"`. Both are deterministic and type-level, not
  instance-specific — a reasonable baseline for structural errors, whose cause largely *is* the type. The two
  content error types would benefit from LLM-driven, instance-specific root-cause analysis instead; that's
  explicitly deferred, not built.
- **Writes one `log.md` audit line per issue**, whether opened or recurring — see "The `log.md` audit trail"
  below.

Returns every `ErrorBookEntry` touched (opened or recurred) this call, though `Orchestrator` doesn't currently
use the return value for anything beyond triggering `code_auto_fix`.

### Inject — `active_constraints`

```python
def active_constraints(self) -> list[str]:
    return [entry.constraint_rule for entry in self.entries if entry.status == "open" and entry.constraint_rule]
```

Called once per **batch** (not per passage) at the very top of `Orchestrator.run_batch`, before Phase 1 even
starts — every `constraint_rule` string from every currently-open entry, injected verbatim into every
`CompileWikiPages` call this batch (see `extractor.md`). This is the mechanism by which a mistake diagnosed on
one batch actually changes the LLM's behavior on the next.

### Verify & Close — `verify_and_close`

```python
def verify_and_close(self, writer: Writer, batch_id: int) -> list[ErrorBookEntry]:
```

Only called when `periodic_fix_due(batch_id)` is true — see below — right after `Fixer.llm_periodic_fix`. For
every currently-`open` entry, `_is_resolved` re-checks it deterministically against the *current* `Writer`
state:

| `error_type` | Re-check |
|---|---|
| `dangling_links` | every `affected_ref` now exists in `writer.list_pages()` |
| `incomplete_pages` | the referenced page (looked up as a Claim, then a Concept) now passes `claim_is_complete`/`concept_is_complete` |
| `malformed_refs` | the referenced Claim's `source_ref` now passes `source_ref_well_formed` |
| `unseen_overwrite`, `index_inconsistency` | **never auto-resolved** — these are only meaningful at structural-validate time (before a page is written); there's nothing post-write left to re-check, so entries of these types stay open until something else (manual intervention, a future design) closes them |
| `unsupported_facts`, `cross_page_contradictions` | **never auto-resolved** — would need an LLM-driven re-verification this deterministic pass can't perform; explicitly deferred |

A resolved entry gets `status = "closed"`, `closed_at_batch = batch_id`,
`verification_method = f"re-checked at batch {batch_id} against current Writer state"`, and one more
`log.md` line.

### `periodic_fix_due` — the cadence gate

```python
def periodic_fix_due(self, batch_id: int) -> bool:
    if self.periodic_fix_interval <= 0:
        return False
    due = batch_id > 0 and batch_id % self.periodic_fix_interval == 0
    return due and batch_id != self._last_periodic_fix_batch
```

`periodic_fix_interval` defaults to 5 (a starting default, not a validated threshold — left undecided at the
architecture level, deferred to scaffolding-stage tuning). Fires every `N`th batch, and — via
`_last_periodic_fix_batch` (set inside `verify_and_close`, not `periodic_fix_due` itself) — never twice for
the same `batch_id`, guarding against a batch being reprocessed (e.g. after a retry). `periodic_fix_interval
<= 0` disables periodic fixing entirely.

When due, `Orchestrator` runs `Fixer.llm_periodic_fix` (LLM-driven repair of open content-type entries —
`unsupported_facts`/`cross_page_contradictions` only; structural issues are always handled immediately by
`code_auto_fix`, never here) and then `verify_and_close`, in that order — the fix runs first so
`verify_and_close`'s re-check has a chance to actually find things resolved.

## The `log.md` audit trail

`MarkdownWriter.append_log(event: str)` appends one line (`f"- {event}\n"`) to `bundle/log.md`, initialized
with just a `# Log\n\n` header at `MarkdownWriter.__init__` time. `append_log` is part of the abstract
`Writer` port — every `Writer` implementation must provide it — but it's called from exactly one place:
`ErrorBook.update_error_book`/`verify_and_close`, never directly by `Orchestrator` or anything else.

Two log-line shapes, both plain sentences, no structured format:

```
- batch 1: UpdateErrorBook opened dangling_links entry 73f9bcd0... — Claim.related_concepts references missing page 'x' (refs: x)
- batch 1: UpdateErrorBook recurrence of dangling_links entry 73f9bcd0... — ... (refs: y)
- batch 5: VerifyAndClose closed dangling_links entry 73f9bcd0... — Claim.related_concepts references missing page 'x'
```

This is `log.md`'s entire purpose per the proposal (§4.4): "每次 UpdateErrorBook/VerifyAndClose 都要同步寫一
筆事件進 log.md" (every `UpdateErrorBook`/`VerifyAndClose` call must also write an event to `log.md`) — an
append-only history distinct from `error_book.yaml`'s current-state snapshot, intended to support later
precision/recall measurement against manually-injected known contradictions (see root `TODO.md` §E).

## Persistence — `YamlErrorBookStore`

```python
class YamlErrorBookStore:
    def __init__(self, pipeline_state_root: Path | str) -> None: ...
    def load(self) -> ErrorBook: ...   # a fresh empty ErrorBook if the file doesn't exist yet
    def save(self, error_book: ErrorBook) -> None: ...  # overwrites the previous snapshot wholesale
```

Writes `<pipeline_state_root>/error_book.yaml` — the full `ErrorBook` model dumped as YAML, always a complete
overwrite (not incremental). Kept as a separate adapter, not a method on `ErrorBook` itself, because
`ErrorBook` stays pure in-memory logic with zero filesystem access (AGENTS.md §4) — the CLI's `_run_compile`
calls `error_book_store.load()` before building the `Orchestrator` and `error_book_store.save(error_book)`
after `run_batch` returns (see `cli-and-cost-ledger.md`).

`error_book.yaml` lives under `pipeline-state/`, not `bundle/` — it's pipeline meta-state, not domain content,
and deliberately doesn't need to pass OKF conformance (see `writer.md`'s bundle-layout section for the
`bundle/`/`pipeline-state/` split).
