# Writer

Module: `adapters/writers/markdown_writer.py::MarkdownWriter`, implementing `ports/writer.py::Writer` — the
only `Writer` backend implemented/validated in this POC (D16 explicitly scopes out alternatives; see
`domain/pipeline.py`'s "Out of scope" note in `TODO.md`). Persists `Claim`/`Concept`/`Document` pages as
OKF-style markdown with YAML frontmatter, and is the *only* place allowed to write into `bundle/` — every
other module reaches the bundle only through this interface (AGENTS.md §4).

```python
class Writer(abc.ABC):
    def write_claim(self, claim: Claim) -> None: ...
    def write_concept(self, concept: Concept) -> None: ...
    def write_document(self, document: Document) -> None: ...
    def read_claim(self, slug: str) -> Claim | None: ...
    def read_concept(self, slug: str) -> Concept | None: ...
    def read_document(self, slug: str) -> Document | None: ...
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
    documents/
        index.md
        <slug>.md ...
```

Every type gets its own subdirectory with its own `index.md`; the root `index.md` only links to the three
subdirectory indices — it doesn't list individual pages itself (OKF's "progressive disclosure" principle).
`bundle_root`'s `claims/`/`concepts/`/`documents/` directories and `log.md` are all created/initialized at
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
claim_text: Water boils at 100C at sea level.
...every other field, dumped via claim.model_dump(mode="json")...
---

# water-boils

Water boils at 100C at sea level.

## Related Pages
- [[water]]

## Related Sources
- doc-1#p0
```

`type` is injected as the first frontmatter key (not a field on the Pydantic models themselves) —
`{"type": "Claim", **claim.model_dump(mode="json")}` — matching OKF's typed-frontmatter requirement.
`read_claim`/`read_concept`/`read_document` parse the frontmatter block back out with `yaml.safe_load` and
reconstruct the model via `Model.model_validate(frontmatter)`; a missing file returns `None`, never raises.

## Body rendering — deterministic, never LLM-generated

Every `write_*` call renders the body from that same call's frontmatter fields, via a static
`_render_*_body` method — `## Related Pages` / `## Related Sources` / `## Key Facts` / `## Produced Claims` /
`## Produced Concepts` sections all come from this, never independently asked of an LLM. This is what keeps
body and frontmatter from ever drifting apart, and avoids an entire class of consistency-check that would
otherwise be needed (D17). A section is omitted entirely (not rendered as an empty heading) when its source
list is empty — e.g. a `Claim` with no `related_concepts` gets no `## Related Pages` heading at all.

| Type | Body sections (in order) |
|---|---|
| `Claim` | title, `claim_text`, `## Related Pages` (from `related_concepts`, if any), `## Related Sources` (from `source_ref`, if non-empty) |
| `Concept` | title, `summary`, `## Key Facts` (from `key_facts`), `## Related Pages` (from `related_pages`), `## Related Sources` (from `related_sources`) |
| `Document` | title, `summary`, `## Produced Claims`, `## Produced Concepts`, `## Related Pages`, `## Source` (always rendered — `source_path`) |

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

    self._maintain_document_backlinks(claim)
```

Three backlinks maintained, all incrementally, all on every `write_claim`:

1. **`Concept.key_facts`**: every `related_concepts` target that already exists gets this claim's slug
   appended (if not already present) and gets re-written. A target that doesn't exist yet is silently
   skipped — that's a dangling link, a `Validator` concern (`validator.md`), not this method's job to fix.
2. **Symmetric `Claim.contradicted_by`**: if claim A lists claim B in `contradicted_by`, and B already
   exists, B gets a matching entry pointing back at A (same `reason`) — so the contradiction shows up on
   *both* pages, not just the one that happened to declare it first.
3. **`Document.produced_claims`/`produced_concepts`** — via `_maintain_document_backlinks`:

```python
def _maintain_document_backlinks(self, claim: Claim) -> None:
    document_slug = claim.source_ref.split("#", 1)[0]
    document = self.read_document(document_slug)
    if document is None:
        return
    if claim.slug not in document.produced_claims:
        document.produced_claims.append(claim.slug)
    for concept_slug in claim.related_concepts:
        if concept_slug not in document.produced_concepts:
            document.produced_concepts.append(concept_slug)
    ...  # write_document_file only if something actually changed
```

The owning `Document` is identified purely by parsing `claim.source_ref`'s leading segment before an
optional `#` — the exact convention `Orchestrator._anchor_source_refs` guarantees every persisted claim's
`source_ref` follows (`<document_slug>#p<passage_index>`, see `pipeline-overview.md`). If that `Document`
hasn't been written yet, this is treated the same as an unresolved `related_concepts` target: silently
skipped, not this `Writer`'s job to fix (in practice this never happens in the current `Orchestrator` flow,
since `_ensure_document_pages` always runs before any Phase 2 write — see `pipeline-overview.md`).

`write_concept` and `write_document` do **not** trigger any backlink maintenance of their own — only
`write_claim` does, since claims are the only type that *points at* the other two.

## Hierarchical `index.md` (D23)

Regenerated in full on **every** `write_claim`/`write_concept`/`write_document` call, via `_regenerate_index`:

```python
def _regenerate_index(self) -> None:
    self._write_type_index(_CLAIMS_DIR, "Claims", self._claim_index_entries())
    self._write_type_index(_CONCEPTS_DIR, "Concepts", self._concept_index_entries())
    self._write_type_index(_DOCUMENTS_DIR, "Documents", self._document_index_entries())
    self._write_root_index()
```

Not incremental — every write re-scans that type's directory (`_page_slugs`, which globs `*.md` and excludes
`index.md` itself) and re-reads every page to build the current entry list. Simple and always-correct at the
cost of doing more I/O than strictly necessary per write; acceptable for this POC's scale.

Each subdirectory's `index.md` fully lists that type's pages, one line each, with a one-line description
sourced from a specific field per type — never separately generated:

| Type | Description source |
|---|---|
| `Claim` | `claim_text` itself (no separate summary field exists) |
| `Concept` | `f"{concept_title}: {summary}"` |
| `Document` | `f"{document_title}: {summary}"` |

The root `index.md` is a fixed three-block template — `# Claims` / `# Concepts` / `# Documents`, each linking
to that subdirectory's `index.md` — it never lists individual pages itself, matching OKF's progressive
disclosure principle. No nesting deeper than the type level (an explicit scope limit — OKF allows deeper
nesting, this POC doesn't need it).

## `list_pages()` — cross-type, sorted, flat

```python
def list_pages(self) -> list[str]:
    return sorted(self._page_slugs(_CLAIMS_DIR) + self._page_slugs(_CONCEPTS_DIR) + self._page_slugs(_DOCUMENTS_DIR))
```

A single flat, alphabetically-sorted list of every slug across all three types — this is what
`LLMExtractor.select_pages` iterates to build the "existing pages" prompt context, and what
`DefaultValidator`'s Dangling Links/Unseen Overwrite checks treat as "what currently exists" (see
`extractor.md`, `validator.md`).

## `append_log` — see `error-book.md`

Covered in full there since it's exclusively `ErrorBook`'s output channel — `append_log` just opens `log.md`
in append mode and writes `f"- {event}\n"`; no other logic lives on the `Writer` side of that mechanism.
