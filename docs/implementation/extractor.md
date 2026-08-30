# Extractor

Module: `adapters/llm/extractor.py::LLMExtractor`, implementing `domain/pipeline.py::Extractor`. Runs in D12's
Phase 1 — see `pipeline-overview.md` for how `Orchestrator` calls it (concurrently, one call pair per
passage, read-only against `Writer`).

```python
class LLMExtractor(Extractor):
    def __init__(self, llm_client: OpenAICompatibleClient, cost_ledger: JsonlCostLedger) -> None: ...
    def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]: ...
    def compile_wiki_pages(self, passage: str, selected: list[str], constraints: list[str], batch_id: int) -> CompiledUpdate: ...
```

Domain-agnostic by construction (AGENTS.md §4): both prompts below only ever talk about "a passage," "existing
pages," and "constraints" — never anything corpus-specific. Per-corpus segmentation/type extensions are a
future skill's job (D3), not this class's.

## `select_pages` — Algorithm 1's `SelectPages`

```python
def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]:
    known_slugs = writer.list_pages()
    if not known_slugs:
        return []
    page_index = "\n".join(f"- {slug}: {_describe_page(writer, slug)}" for slug in known_slugs)
    user_prompt = f"Passage:\n{passage}\n\nExisting pages:\n{page_index}"
    content = self._call_llm(stage="Extractor.SelectPages", ...)
    ...
    return [slug for slug in selected if slug in known_set]  # filters out any hallucinated slug
```

- **Skips the LLM call entirely when `writer.list_pages()` is empty** — the very first passage of a fresh
  bundle has nothing to select from, so there's no point spending a call. This is why an e2e test with an
  empty bundle asserts `"Extractor.SelectPages"` never appears in `cost_ledger.jsonl`.
- Every known page gets a one-line description via `_describe_page`, which only knows how to describe a
  `Concept` (`summary` or `concept_title` as fallback) or a `Claim` (`claim_text`) — a `Source` page falls
  through to `"(no description available)"`. In practice this rarely matters: `Source` pages are only ever
  created *after* Phase 1 finishes for a batch (see `pipeline-overview.md`), so they're never in
  `writer.list_pages()` at `select_pages` time for a fresh bundle's first batch — though on a later batch
  against an already-populated bundle, an existing `Source` from a previous ingest could show up here with
  an unhelpful description.
- The LLM's response is parsed as `{"selected": [...]}`; the result is filtered against `known_slugs` so a
  hallucinated slug can never leak into `selected` — `compile_wiki_pages` and `structural_validate`'s Unseen
  Overwrite check both trust this list.

## `compile_wiki_pages` — Algorithm 1's `CompileWikiPages`

```python
def compile_wiki_pages(self, passage, selected, constraints, batch_id) -> CompiledUpdate:
    user_prompt = f"Passage:\n{passage}\n\nSelected existing pages:\n{selected_text}\n\nActive constraints:\n{constraints_text}"
    content = self._call_llm(stage="Extractor.CompileWikiPages", ...)
    payload = parse_json_object(content, context="Extractor.CompileWikiPages")
    return parse_compiled_update(payload, context="Extractor.CompileWikiPages")
```

Sends the passage text, the `selected` slugs from the previous call (as a bare list — the LLM doesn't get
each selected page's full content, only that they exist and are relevant), and `constraints` (the batch's
`active_constraints()` — see `error-book.md`). Response is parsed into a `CompiledUpdate` via
`adapters/llm/compiled_update_parsing.py::parse_compiled_update`, which validates the JSON against the
`Claim`/`Concept` Pydantic schemas and raises `LLMOutputError` on anything that doesn't fit.

## The system prompts, verbatim

**`_SELECT_PAGES_SYSTEM_PROMPT`**: asks for `{"selected": ["slug-1", ...]}`, explicitly instructed to "only
return slugs from the provided list — never invent one" (belt-and-suspenders with the post-filter above).

**`_COMPILE_WIKI_PAGES_SYSTEM_PROMPT`**: specifies the exact JSON schema (`claims`/`concepts` arrays matching
`Claim`/`Concept`'s fields, including `description`), plus six rules:

1. `claim_text` is a structured assertion, not a verbatim copy of the passage.
2. `description` is a short **one-sentence** summary for `index.md` listings (D23 §5.4, extended beyond the
   original decision — see `TODO.md`) — always short, regardless of how long `claim_text`/`summary` is, and
   always plain discourse (never `"<name>: <text>"` — the title/slug is already the index entry's own link
   text). Optional in the sense that a missing/empty value just falls back to `claim_text`/`summary` at
   index-render time (see `writer.md`); Pydantic defaults it to `""` if the LLM omits the key entirely,
   rather than raising.
3. Concept `summary` is **not** limited to one paragraph — the LLM is told to use its own judgment: plain
   prose for a simple Concept, or markdown `## ` subsections (e.g. `## History`, `## Usage`) when the topic
   has multiple distinct facets, without forcing structure onto something that doesn't need it. This is the
   deliberate contrast with rule 2: `description` is always short, `summary` can be as long/structured as the
   topic warrants (extends beyond D23's original decision — see `TODO.md`'s dated entry, and `writer.md` for
   how the Writer keeps a structured `summary` from colliding with its own rendered sections).
4. `source_ref` must point into this passage (a document id, optionally `#locator`) — **this value is
   overwritten unconditionally by `Orchestrator._anchor_source_refs` afterward**, so what the LLM puts here
   barely matters in practice; it exists mainly so `DefaultValidator._check_malformed_refs` still has
   something meaningful to lint before the anchor overwrites it (see `pipeline-overview.md`).
5. Never include a `key_facts` field on concepts — that's `Writer`-maintained, not LLM output (see
   `core-types.md`).
6. Only reference `related_concepts`/`contradicted_by`/`related_pages` slugs that are either defined in this
   same response or already among the provided pages — never invent a slug that resolves nowhere. (Not
   strictly enforced by code the way `select_pages`'s filter is — a violation here surfaces later as a
   `dangling_links` structural issue, see `validator.md`.)

Return `{"claims": [], "concepts": []}` if the passage yields nothing new — an entirely valid, expected
response for a passage with no extractable facts.

## Cost recording

Both calls go through a shared `_call_llm` helper that times the request with `time.monotonic()` and records
one `CostEvent` via `cost_ledger.record(stage, batch_id, tokens_in, tokens_out, wall_clock_ms)` — `stage` is
`"Extractor.SelectPages"` or `"Extractor.CompileWikiPages"`. Since Phase 1 runs these concurrently across
passages, `JsonlCostLedger.record` is thread-safe (see `cli-and-cost-ledger.md`).
