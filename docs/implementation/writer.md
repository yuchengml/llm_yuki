# Writer

Module: `adapters/writers/markdown_writer.py::MarkdownWriter`, implementing `ports/writer.py::Writer` — the
only `Writer` backend implemented/validated in this POC (D16 explicitly scopes out alternatives; see
`domain/pipeline.py`'s "Out of scope" note in `TODO.md`). Persists `Claim`/`Concept`/`Source` pages as
OKF-style markdown with YAML frontmatter, and is the *only* place allowed to write into `bundle/` — every
other module reaches the bundle only through this interface (AGENTS.md §4).

```python
class Writer(abc.ABC):
    def write_claim(self, claim: Claim) -> None: ...
    def write_concept(self, concept: Concept) -> None: ...
    def write_source(self, source: Source) -> None: ...
    def read_claim(self, slug: str) -> Claim | None: ...
    def read_concept(self, slug: str) -> Concept | None: ...
    def read_source(self, slug: str) -> Source | None: ...
    def list_pages(self) -> list[str]: ...
    def append_log(self, event: str) -> None: ...
```

## Bundle layout (D23 hierarchical index)

```
<bundle_root>/
    index.md              — root entry point: links to each type's own index.md
    log.md                — append-only event log (§4.4, see error-book.md)
    claims/
        index.md           — full listing of Claim pages, one-line description each
        <slug>.md ...
    concepts/
        index.md
        <slug>.md ...
    sources/
        index.md
        <slug>.md ...
```

Every type gets its own subdirectory with its own `index.md`; the root `index.md` only links to the three
subdirectory indices — it doesn't list individual pages itself (OKF's "progressive disclosure" principle).
`bundle_root`'s `claims/`/`concepts/`/`sources/` directories and `log.md` are all created/initialized at
`MarkdownWriter.__init__` time, so a fresh bundle always has the full skeleton even before anything is
written.

This is a different location from `pipeline-state/` (`error_book.yaml`, `cost_ledger.jsonl`) — `bundle/` must
pass OKF conformance, `pipeline-state/` is internal meta-state that deliberately never mixes in (see
`error-book.md`, `cli-and-cost-ledger.md`).

## Page file format

Every `<slug>.md` is YAML frontmatter + a markdown body:

```
---
type: Claim
slug: water-boils
description: Water's boiling point at sea level.
...every other field except claim_text, dumped via claim.model_dump(mode="json", exclude={"claim_text"})...
---

# water-boils

Water boils at 100C at sea level.

<!-- llm-yuki:sections -->

## Related Pages
- [[water]]

## Related Sources
- doc-1#p0
```

`type` is injected as the first frontmatter key (not a field on the Pydantic models themselves) —
`{"type": "Claim", **claim.model_dump(mode="json", exclude={"claim_text"})}` — matching OKF's
typed-frontmatter requirement. **`claim_text`/`Concept.summary`/`Source.summary` are excluded from
frontmatter entirely** — each type's main free-text field is "content," not metadata (extends D23 beyond its
literal text, see `TODO.md`'s dated entry): it lives only in the body, right under the `# <title>` heading,
never duplicated into YAML. Everything else (short/structured fields, including `description`, the one-line
index blurb) stays in frontmatter as before.

`Concept.summary`/`Source.summary` are not capped to one paragraph (see `entities.py`) — the LLM/batch-reduce
may structure them with their own markdown `## ` subsections (e.g. `## History`, `## Usage`) when a topic
warrants it. That means "the content ends at the first `## ` line" is no longer a safe rule — a content
value's own subsection heading would trip it. `_SECTIONS_SENTINEL` (the HTML comment
`<!-- llm-yuki:sections -->` above — invisible when the markdown renders) is always written between content
and the Writer's own sections, precisely so the two can never be confused regardless of what content contains.

`read_claim`/`read_concept`/`read_source` parse the frontmatter block back out with `yaml.safe_load`, then
recover the content field from the body via `_extract_content` (everything between the `# <title>` line and
`_SECTIONS_SENTINEL`) and merge it into the frontmatter dict *before* reconstructing the model via
`Model.model_validate(frontmatter)` — the content field would otherwise be missing and fail Pydantic
validation. A missing file returns `None`, never raises. The one thing `_extract_content` still can't handle
is a content value that itself contains the literal sentinel string — not expected in practice, since it's an
internal implementation detail no prompt ever mentions to the LLM.

## Body rendering — deterministic, never LLM-generated

Every `write_*` call renders the body from that same call's in-memory model fields, via a static
`_render_*_body` method — `## Related Pages` / `## Related Sources` / `## Key Facts` / `## Produced Claims` /
`## Produced Concepts` sections all come from this, never independently asked of an LLM. This is what keeps
body and frontmatter from ever drifting apart, and avoids an entire class of consistency-check that would
otherwise be needed (D17). A section is omitted entirely (not rendered as an empty heading) when its source
list is empty — e.g. a `Claim` with no `related_concepts` gets no `## Related Pages` heading at all. The
content field (`claim_text`/`summary`) is always the first thing rendered, right after the title — it's the
*only* place that field is written to disk at all, see "Page file format" above.

| Type | Body sections (in order) |
|---|---|
| `Claim` | title, `claim_text`, `_SECTIONS_SENTINEL`, `## Related Pages` (from `related_concepts`, if any), `## Related Sources` (from `source_ref`, if non-empty) |
| `Concept` | title, `summary`, `_SECTIONS_SENTINEL`, `## Key Facts` (from `key_facts`), `## Related Pages` (from `related_pages`), `## Related Sources` (from `related_sources`) |
| `Source` | title, `summary`, `_SECTIONS_SENTINEL`, `## Produced Claims`, `## Produced Concepts`, `## Related Pages`, `## Source` (always rendered — `source_path`) |

`_SECTIONS_SENTINEL` is always written, even when every section after it is empty (a `Claim`/`Concept` with
nothing to link to still gets the sentinel, just nothing following it) — this keeps `_extract_content`'s
boundary rule unconditional, with no "only if there are sections" special case.

## Incremental backlink maintenance (§2.3.2, D18/D21)

Every `write_claim` call, after writing the claim file itself, runs `_maintain_claim_backlinks`:

```python
def _maintain_claim_backlinks(self, claim: Claim) -> None:
    for concept_slug in claim.related_concepts:
        concept = self.read_concept(concept_slug)
        if concept is None:
            continue  # dangling link — not this Writer's job to fix
        if claim.slug not in concept.key_facts:
            concept.key_facts.append(claim.slug)
            self._write_concept_file(concept)

    for ref in claim.contradicted_by:
        other = self.read_claim(ref.slug)
        if other is None:
            continue
        if not any(existing.slug == claim.slug for existing in other.contradicted_by):
            other.contradicted_by.append(ContradictionRef(slug=claim.slug, reason=ref.reason))
            self._write_claim_file(other)

    self._maintain_source_backlinks(claim)
```

Three backlinks maintained, all incrementally, all on every `write_claim`:

1. **`Concept.key_facts`**: every `related_concepts` target that already exists gets this claim's slug
   appended (if not already present) and gets re-written. A target that doesn't exist yet is silently
   skipped — that's a dangling link, a `Validator` concern (`validator.md`), not this method's job to fix.
2. **Symmetric `Claim.contradicted_by`**: if claim A lists claim B in `contradicted_by`, and B already
   exists, B gets a matching entry pointing back at A (same `reason`) — so the contradiction shows up on
   *both* pages, not just the one that happened to declare it first.
3. **`Source.produced_claims`/`produced_concepts`** — via `_maintain_source_backlinks`:

```python
def _maintain_source_backlinks(self, claim: Claim) -> None:
    source_slug = claim.source_ref.split("#", 1)[0]
    source = self.read_source(source_slug)
    if source is None:
        return
    if claim.slug not in source.produced_claims:
        source.produced_claims.append(claim.slug)
    for concept_slug in claim.related_concepts:
        if concept_slug not in source.produced_concepts:
            source.produced_concepts.append(concept_slug)
    ...  # write_source_file only if something actually changed
```

The owning `Source` is identified purely by parsing `claim.source_ref`'s leading segment before an
optional `#` — the exact convention `Orchestrator._anchor_source_refs` guarantees every persisted claim's
`source_ref` follows (`<source_slug>#p<passage_index>`, see `pipeline-overview.md`). If that `Source`
hasn't been written yet, this is treated the same as an unresolved `related_concepts` target: silently
skipped, not this `Writer`'s job to fix (in practice this never happens in the current `Orchestrator` flow,
since `_ensure_source_pages` always runs before any Phase 2 write — see `pipeline-overview.md`).

`write_concept` and `write_source` do **not** trigger any backlink maintenance of their own — only
`write_claim` does, since claims are the only type that *points at* the other two.

## Hierarchical `index.md` (D23)

Regenerated in full on **every** `write_claim`/`write_concept`/`write_source` call, via `_regenerate_index`:

```python
def _regenerate_index(self) -> None:
    self._write_type_index(_CLAIMS_DIR, "Claims", self._claim_index_entries())
    self._write_type_index(_CONCEPTS_DIR, "Concepts", self._concept_index_entries())
    self._write_type_index(_SOURCES_DIR, "Sources", self._source_index_entries())
    self._write_root_index()
```

Not incremental — every write re-scans that type's directory (`_page_slugs`, which globs `*.md` and excludes
`index.md` itself) and re-reads every page to build the current entry list. Simple and always-correct at the
cost of doing more I/O than strictly necessary per write; acceptable for this POC's scale.

Each subdirectory's `index.md` fully lists that type's pages, one line each, with a one-line description
sourced from that page's own `description` frontmatter field (D23 §5.4, extended beyond the original
decision — see `TODO.md`'s dated entry). `description` is never separately generated for the index alone;
it's the same field already persisted on the page:

| Type | `description` origin | Fallback when empty (older bundle, or an LLM that omitted it) |
|---|---|---|
| `Claim` | LLM output, alongside `claim_text` | `claim_text` itself |
| `Concept` | LLM output, alongside `summary` | `summary` alone |
| `Source` | `MarkdownWriter._write_source_file`, deterministically, on every write — never LLM output (see `core-types.md`) | (none needed — `_source_description` always sets it, to `""` while `summary` is still empty) |

`_claim_index_entries`/`_concept_index_entries`/`_source_index_entries` each read `description or <fallback>`
— so a page written before this field existed still gets a usable index entry, it just isn't the
LLM-authored one-liner. **Neither the origin nor any fallback ever prepends the page's title/slug** —
`description` is plain discourse for all three types, never a `"<name>: <text>"` composite; the title is
already the index entry's own `[[slug]]` link text, so repeating it would be redundant (this is why the
`Concept` fallback dropped its earlier `f"{concept_title}: {summary}"` form).

**Every entry is flattened through `_plain_text_snippet` in `_write_type_index` before being written** — this
is the actual bug fix that makes any of the above safe now that `summary` can span multiple `## `
subsections: naively embedding a multi-line `description`/fallback into `f"- [[{slug}]] — {description}"`
would break `index.md`'s one-bullet-per-page format (this was caught by a real CLI smoke run against a
`Source.summary` with subsections, before this flattening step existed — the then-title-prefixed
`_source_description` produced a `description` containing raw newlines). `_plain_text_snippet` strips
`#`/`## ` heading markers (keeping the heading text), collapses all whitespace/newlines to single spaces, and
truncates with `…` past 160 characters. It applies uniformly — to the deterministic `Source` fallback, the
`Concept` `summary` fallback, and even a syntactically-valid but instruction-ignoring LLM `description` that
happens to contain a newline — so `index.md` stays well-formed no matter what produced the text. When the
flattened result is empty (a fresh `Source` with no `summary` yet), the entry is written as bare `[[slug]]`
with no trailing `— ` at all, rather than a dangling dash.

The root `index.md` is a fixed three-block template — `# Claims` / `# Concepts` / `# Sources`, each linking
to that subdirectory's `index.md` — it never lists individual pages itself, matching OKF's progressive
disclosure principle. No nesting deeper than the type level (an explicit scope limit — OKF allows deeper
nesting, this POC doesn't need it).

## `list_pages()` — cross-type, sorted, flat

```python
def list_pages(self) -> list[str]:
    return sorted(self._page_slugs(_CLAIMS_DIR) + self._page_slugs(_CONCEPTS_DIR) + self._page_slugs(_SOURCES_DIR))
```

A single flat, alphabetically-sorted list of every slug across all three types — this is what
`LLMExtractor.select_pages` iterates to build the "existing pages" prompt context, and what
`DefaultValidator`'s Dangling Links/Unseen Overwrite checks treat as "what currently exists" (see
`extractor.md`, `validator.md`).

## `append_log` — see `error-book.md`

Covered in full there since it's exclusively `ErrorBook`'s output channel — `append_log` just opens `log.md`
in append mode and writes `f"- {event}\n"`; no other logic lives on the `Writer` side of that mechanism.
