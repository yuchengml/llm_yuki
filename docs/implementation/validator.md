# Validator

Module: `adapters/validation/default_validator.py::DefaultValidator`, implementing
`domain/pipeline.py::Validator`. Runs in D12's Phase 2, right after `Merger.merge` and before `Fixer` — see
`pipeline-overview.md`. Covers all seven of the proposal's error types (§4.1): five structural (deterministic,
no LLM), two content (LLM-backed).

```python
class DefaultValidator(Validator):
    def __init__(self, llm_client: OpenAICompatibleClient | None = None, cost_ledger: JsonlCostLedger | None = None) -> None: ...
    def structural_validate(self, update: CompiledUpdate, selected: list[str], writer: Writer) -> list[ValidationIssue]: ...
    def content_validate(self, update: CompiledUpdate, passage: str, writer: Writer, batch_id: int) -> list[ValidationIssue]: ...
```

Both live on one class because the abstract `Validator` interface declares both as required, even though only
`content_validate` actually needs an LLM client — `structural_validate` works with `DefaultValidator()`
(no arguments) standalone; `content_validate` raises `RuntimeError` without one.

Every check returns a list of `ValidationIssue` (`domain/error_book.py`): `{error_type, phenomenon,
affected_refs}`. These feed directly into `ErrorBook.update_error_book` (`error-book.md`) and, for structural
issues, into `Fixer.code_auto_fix` (`pipeline-overview.md`).

## The five structural checks (`structural_validate`)

Run unconditionally, in this fixed order, against the in-flight `CompiledUpdate` — never against an LLM.

### 1. Dangling Links

```python
known_slugs = {c.slug for c in update.claims} | {c.slug for c in update.concepts} | set(writer.list_pages())
```

For every `Claim.related_concepts`/`contradicted_by` target and every `Concept.related_pages` target, flags
one issue per target slug not in `known_slugs` — i.e. a link to something that neither this update nor the
already-persisted bundle defines. One `ValidationIssue` per dangling target (`affected_refs = [target]`), not
per referencing page.

### 2. Incomplete Pages

Uses `domain/structural_checks.py`'s pure helpers: `claim_is_complete` (non-empty `claim_text` and
`source_ref` after stripping) and `concept_is_complete` (non-empty `concept_title` and `summary`). One issue
per incomplete claim/concept.

### 3. Malformed Refs

`source_ref_well_formed` (`domain/structural_checks.py`) checks against a loose pattern:
`^[\w./-]+(#[\w./-]+)?$` — a document/passage identifier, optionally followed by `#locator`, allowing only
word characters, dots, slashes, and hyphens. Not a strict grammar (the proposal deliberately leaves the exact
`source_ref` format open) — this only catches the obvious failure modes: empty, whitespace-only, or containing
characters no reasonable reference format would use. Runs against whatever the LLM originally produced for
`source_ref`, **before** `Orchestrator._anchor_source_refs` overwrites it (see `pipeline-overview.md`) — this
is intentional, so malformed-ref lint signal still exists even though the final persisted value is always
well-formed by construction.

### 4. Unseen Overwrite

```python
selected_set = set(selected)
existing_slugs = set(writer.list_pages())
touched_slugs = [c.slug for c in update.claims] + [c.slug for c in update.concepts]
```

Flags any touched slug that's already in `existing_slugs` (a real page, persisted before this check ran) but
*not* in `selected_set` (this passage's own `SelectPages` output — see `extractor.md`) — i.e. `CompileWikiPages`
modified a page it never declared as relevant. `code_auto_fix` responds to this by dropping the whole
candidate, not sanitizing it (see `pipeline-overview.md`).

**Known false-positive source, since D12's Phase 1 parallelism landed**: `selected` reflects a snapshot taken
*before* the batch's Phase 1 ran (see `pipeline-overview.md`), but `existing_slugs` reflects the *live* Writer
state at Phase 2 time — which now includes anything written by an earlier passage in this same batch's
sequential Phase 2 loop. Two passages of the same batch that independently touch the same page will flag the
second one as an Unseen Overwrite even though nothing is actually wrong — tracked as a known gap (`TODO.md`
§B3/§D, extends the pre-existing B-2 `contradicted_by`-recall risk), not fixed.

### 5. Index Inconsistency

Two checks, both about the same slug being claimed by two different core types:

```python
for slug in claim_slugs & concept_slugs:               # within this same update
    ...
for claim in update.claims:
    if writer.read_concept(claim.slug) is not None: ... # Claim vs. already-persisted Concept
    if writer.read_source(claim.slug) is not None: ... # Claim vs. already-persisted Source
for concept in update.concepts:
    if writer.read_claim(concept.slug) is not None: ...
    if writer.read_source(concept.slug) is not None: ...
```

`Source` pages are never part of a `CompiledUpdate` (they're created deterministically by `Orchestrator`,
never by the LLM-backed `Extractor` — see `core-types.md`), so a `Source` can only collide as an
*already-persisted* page a candidate's slug happens to match, not within the update itself — there's no
"Source vs Source in one update" case to check.

**Scope note**: the proposal's literal definition of Index Inconsistency (`ARCHITECTURE.md` §4.1 #5) is a full
bidirectional diff between `index.md` and the filesystem — this codebase never implemented that; it was
already scoped down to same-slug-different-type collision detection before `Source` existed, and D23's
addition of a third type only extended that existing narrower scope. A true `index.md`-vs-filesystem diff
remains unimplemented (pre-existing gap, not introduced by any recent change).

## The two content checks (`content_validate`) — one LLM call per passage

```python
def content_validate(self, update, passage, writer, batch_id) -> list[ValidationIssue]:
    if self._llm_client is None or self._cost_ledger is None:
        raise RuntimeError(...)
    if not update.claims:
        return []
    claims_text = "\n\n".join(self._describe_claim(claim, update, writer) for claim in update.claims)
    ...
```

One call covers **every** candidate claim in the update at once (not one call per claim) — cost efficiency
per D19. For each claim, `_describe_claim` includes its `claim_text`, `provenance_state`, and up to 8 "sibling
claims" gathered by `_gather_siblings`: every slug already in `contradicted_by` (candidate conflicts flagged
at extraction time), plus every other claim sharing a related `Concept`'s `key_facts` (i.e. claims about the
same topic). Siblings are resolved first against `writer` (already-persisted), falling back to `update.claims`
(candidates from this same passage that haven't been written yet).

The LLM checks for exactly two things, per the system prompt:

- **`unsupported_facts`**: `claim_text` isn't actually grounded in the passage — matters most when
  `provenance_state == "extracted"` (claimed to be taken directly from the source).
- **`cross_page_contradictions`**: `claim_text` genuinely conflicts with a listed sibling — contradicting
  dates, values, relationships — not merely related or overlapping topics.

Instructed to only report an issue it's confident is genuine — not to flag imprecision or uncertainty as an
error. Response parsed as `{"issues": [{"error_type": ..., "phenomenon": ..., "affected_refs": [...]}]}` and
validated against the `ValidationIssue` schema; a shape mismatch raises `LLMOutputError`. Cost recorded as
`"Validator.ContentValidate"`.
