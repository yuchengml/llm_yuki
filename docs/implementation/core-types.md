# Core Types

Module: `domain/entities.py`. Three Pydantic `BaseModel`s — `Claim`, `Concept`, `Source` — plus a small
`ContradictionRef` helper type. These are the only page types the core pipeline understands; a per-corpus
skill may add its own extension types on top (e.g. `sci-paper:Paper`), but nothing in `domain/`, `ports/`, or
the default `adapters/` implementations knows about anything beyond these three.

Every field below states three things: what it means, **who writes it**, and **who reads it** — because the
whole "deterministic overrides LLM" design rests on some fields being LLM output and others being maintained
entirely by code, and mixing the two up is the easiest way to misunderstand this codebase.

## `Claim`

```python
class Claim(BaseModel):
    slug: str
    claim_text: str
    description: str = ""
    source_ref: str
    confidence: float          # 0.0-1.0
    provenance_state: Literal["extracted", "merged", "inferred", "ambiguous"]
    related_concepts: list[str] = []
    contradicted_by: list[ContradictionRef] = []
```

A sourced, extracted/inferred assertion — the smallest unit the contradiction-detection loop operates on.

| Field | Meaning | Written by | Read by |
|---|---|---|---|
| `slug` | Unique page identifier | `LLMExtractor` (LLM output) | Everything that links to it |
| `claim_text` | A structured assertion — **not** a verbatim copy of the source passage. Content, not metadata: persisted only in the body (never in frontmatter), extending D23 beyond its literal text — see `writer.md` and `TODO.md`'s dated entry | LLM, or `DefaultMerger._merge_claim_pair` (`new or old` on merge) | `Merger.summarize_source` input, `content_validate` prompt, fallback for `claims/index.md`'s entry when `description` is empty |
| `description` | Short one-line summary for `claims/index.md` entries (D23 §5.4, extended beyond the original decision — see `TODO.md`) | LLM; `DefaultMerger._merge_claim_pair` (`new or old` on merge, same as `claim_text`) | `MarkdownWriter._claim_index_entries` — falls back to `claim_text` when empty (e.g. a page written before this field existed) |
| `source_ref` | Pointer into the Raw Source | LLM *initially*, then **unconditionally overwritten** by `Orchestrator._anchor_source_refs` to `<source_slug>#p<passage_index>` | `Writer._maintain_source_backlinks` (parses the leading segment to find the owning `Source`) |
| `confidence` | Factual-certainty score | LLM; on merge, `max(base.confidence, new.confidence)` | Not consumed by any pipeline logic yet — informational |
| `provenance_state` | How the Claim came to exist | LLM sets `"extracted"`/`"inferred"`/`"ambiguous"`; `DefaultMerger` always sets `"merged"` once a claim has been merged with an existing one | `content_validate`'s prompt (only `"extracted"` claims are checked for grounding in the passage) |
| `related_concepts` | Slugs of linked `Concept` pages | LLM; `DefaultFixer.code_auto_fix` strips dangling targets; `DefaultMerger` unions on merge | `Writer._maintain_claim_backlinks` (adds this claim to each target's `key_facts`), body rendering (`## Related Pages`), `DefaultValidator._check_dangling_links` |
| `contradicted_by` | Candidate conflicts with other Claims — **a lint accelerator, not an authoritative judgment** (the Validator still runs its own full sweep) | LLM; `Writer._maintain_claim_backlinks` adds a *symmetric* entry to the referenced Claim; `DefaultFixer` strips dangling targets; `DefaultMerger` unions (deduped by `slug`, first `reason` wins) | `DefaultValidator._gather_siblings` (content-validate prompt context) |

`ContradictionRef` is just `{slug: str, reason: str}`.

## `Concept`

```python
class Concept(BaseModel):
    slug: str
    concept_title: str
    aliases: list[str] = []
    tags: list[str] = []
    summary: str
    description: str = ""
    key_facts: list[str] = []
    related_pages: list[str] = []
    related_sources: list[str] = []
```

A general topic/entity page — the fallback type when no more specific type applies.

| Field | Meaning | Written by | Read by |
|---|---|---|---|
| `slug` | Unique page identifier | LLM | Everything that links to it |
| `concept_title` | Human-readable title | LLM *initially*; **locked** on every subsequent merge (D22 layer 3 — `DefaultMerger._merge_concept_pair` always keeps `base.concept_title`, ignoring whatever the new candidate says) | body's `# <concept_title>` heading, fallback component for `concepts/index.md`'s entry when `description` is empty |
| `summary` | Full write-up — plain prose for a simple Concept, or markdown `## ` subsections when the topic has multiple distinct facets; **not capped to one paragraph**. Content, not metadata: persisted only in the body (never in frontmatter), extending D23 beyond its literal text — see `writer.md` and `TODO.md`'s dated entry | LLM; on merge, D22's three layers decide the final value (see `merger.md`) | body text, fallback component for `concepts/index.md`'s entry when `description` is empty (flattened to one line via `_plain_text_snippet` regardless — see `writer.md`), `LLMExtractor._describe_page` (what `SelectPages` sees) |
| `description` | Short **one-sentence** summary for `concepts/index.md` entries (D23 §5.4, extended beyond the original decision — see `TODO.md`) — distinct from `summary`, which may be a full multi-section write-up. Plain discourse, never a `"concept_title: ..."` composite — the title is already the index entry's own `[[slug]]` link text | LLM; `DefaultMerger._merge_concept_pair` (`new or old` on merge — **not** D22's 3-layer `summary` protection, since this is index metadata, not body content) | `MarkdownWriter._concept_index_entries` — falls back to `summary` alone when empty |
| `aliases`, `tags` | Free-form metadata | LLM; unioned on merge (D22 layer 1) | Not consumed by pipeline logic yet |
| `key_facts` | Slugs of related Claims — **a backlink, not LLM output** | Exclusively `Writer._maintain_claim_backlinks`; the `CompileWikiPages` prompt explicitly tells the LLM *not* to include this field | body's `## Key Facts` section |
| `related_pages` | Wikilinks to other Concept pages | LLM; `DefaultFixer` strips dangling targets; unioned on merge | body's `## Related Pages`, `DefaultValidator._check_dangling_links` |
| `related_sources` | Source/provenance digest links | LLM; unioned on merge | body's `## Related Sources` |

## `Source`

```python
class Source(BaseModel):
    slug: str
    source_title: str
    source_path: str
    ingested_at: str
    summary: str
    description: str = ""
    produced_claims: list[str] = []
    produced_concepts: list[str] = []
    related_pages: list[str] = []
```

A per-Raw-Source navigation page (D21, reversing an earlier D20 decision not to have one; named `Source` to
match the naming `nashsu/llm_wiki` itself uses — implemented first under the name `Document` and renamed
later, see `TODO.md`) — **not** a replacement for `Claim.source_ref` (which still points *out* of the wiki to
the Raw Source itself, per D17); this is an *additional* in-wiki entry point summarizing everything a source
produced. One `Source` exists per `SourceRef.id` the `Connector` returns, regardless of how many
natural-paragraph passages that source was split into (D11/D12).

| Field | Meaning | Written by | Read by |
|---|---|---|---|
| `slug` | Unique page identifier — the source's `SourceRef.id` | `Orchestrator._ensure_source_pages` | `_anchor_source_refs`'s target format, `Writer._maintain_source_backlinks`'s lookup key |
| `source_title` | Human-readable title (source document title or filename) | `Orchestrator` — currently just set to `slug` (the `Connector` doesn't expose a friendlier title) | body's `# <source_title>` heading, input to `description` |
| `source_path` | Location of the corresponding Raw Source folder | `Orchestrator` — also currently just `slug`, since a `Connector` is not guaranteed to be filesystem-backed and `slug` is the only portable identifier it always exposes | body's `## Source` section |
| `ingested_at` | Date first compiled into the wiki | `Orchestrator._ensure_source_pages`, `datetime.now(UTC).date().isoformat()` at creation time — never updated again | Informational; not consumed by pipeline logic |
| `summary` | Full write-up generated by recursive batch-reduce over Claims — plain prose or markdown `## ` subsections, **not capped to one paragraph** — **never LLM output directly** (the LLM writes the prose, but which Claims to summarize / how many rounds / when it's final are all decided by code, see `merger.md`/`pipeline-overview.md`). Content, not metadata: persisted only in the body (never in frontmatter), extending D23 beyond its literal text — see `writer.md` and `TODO.md`'s dated entry | Starts `""` at creation; `Orchestrator._finalize_source_summaries` calls `Merger.summarize_source` once every passage of this source has been through Phase 2, and overwrites this field with the result | body text, input to `description` (flattened to one line via `_plain_text_snippet` — see `writer.md`), `LLMExtractor._describe_page` (if `Source` is ever surfaced to `SelectPages` — see `pipeline-overview.md` for why it currently isn't) |
| `description` | Short one-line summary for `sources/index.md` entries (D23 §5.4, extended beyond the original decision — see `TODO.md`) — **never LLM output, unlike `Claim`/`Concept.description`**. Plain discourse, never a `"source_title: ..."` composite — the title is already the index entry's own `[[slug]]` link text; empty (not the title) while `summary` is still empty | Exclusively `MarkdownWriter._write_source_file`, which unconditionally overwrites it to `_plain_text_snippet(summary)` (or `""` while `summary` is still empty) on **every** write — any value passed in (e.g. a stale one, or one an LLM-generated `Source` construction attempt supplied) is discarded, same "deterministic overrides LLM" treatment as `source_ref` anchoring (D17/D18/D22). `_plain_text_snippet` flattens `summary`'s possible `## ` subsections into one line — needed once `summary` stopped being capped to one paragraph, see `writer.md` | `MarkdownWriter._source_index_entries` |
| `produced_claims` | Slugs of Claims this source produced — **a backlink, not LLM output** | Exclusively `Writer._maintain_source_backlinks`, on every `write_claim` call whose `source_ref` resolves to this source | `_finalize_source_summaries` (the claim texts fed into `summarize_source`), body's `## Produced Claims` |
| `produced_concepts` | Slugs of Concepts this source touched — same mechanism | Exclusively `Writer._maintain_source_backlinks` (added when a claim from this source has that concept in `related_concepts`) | body's `## Produced Concepts` |
| `related_pages` | Wikilinks to other pages | Never set by any current code path — the field exists for schema symmetry with `Claim`/`Concept` but nothing populates it yet | body's `## Related Pages` (renders empty today) |

## What's *not* an LLM-editable field, anywhere

Four "deterministic overrides LLM" backlink/rendering mechanisms recur across all three types, and are worth
naming once instead of per-field:

- **Backlinks are Writer-only.** `Concept.key_facts`, `Source.produced_claims`, `Source.produced_concepts`
  are never present in an LLM prompt's expected output schema (the `CompileWikiPages`/`LLMPeriodicFix` system
  prompts explicitly say "do not include a `key_facts` field") — they only ever come from `Writer`'s
  incremental maintenance on write. See `writer.md`.
- **Locked fields survive merge unconditionally.** `Concept.concept_title` is the one field D22's layer 3
  locks — it can never change once a `Concept` first exists, no matter what a later merge candidate says.
- **Body sections are rendered, never generated.** Every `## Related Pages` / `## Related Sources` / `## Key
  Facts` / `## Produced Claims` / `## Produced Concepts` section in a page's markdown body is derived
  deterministically from that same page's frontmatter by `MarkdownWriter`, not asked of the LLM separately —
  see `writer.md`. This is what keeps body and frontmatter from ever drifting apart.
- **`Source.description` is always Writer-computed.** Unlike `Claim.description`/`Concept.description` (LLM
  output, merged `new or old`), `Source.description` is recomputed from `summary` alone on every single
  write, overwriting whatever value was passed in — the same treatment `_anchor_source_refs` gives
  `Claim.source_ref`. This follows from `Source.summary` itself already being deterministic (D21 §1.5,
  `Merger.summarize_source`, never direct LLM output) — there is no LLM-authored value to preserve.
- **`description` is always plain discourse, never a `"<name>: ..."` composite.** True for all three types —
  the page's title/slug is already the index entry's own `[[slug]]` link text, so repeating it inside
  `description` would be redundant. `_source_description` doesn't prepend `source_title`; the `Concept`
  index-entry fallback doesn't prepend `concept_title` either. Extends beyond D23's literal text, see
  `TODO.md`'s dated entry.
