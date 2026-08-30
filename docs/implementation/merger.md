# Merger

Module: `adapters/merging/default_merger.py::DefaultMerger`, implementing `domain/pipeline.py::Merger`. Runs
in D12's Phase 2 — sequentially, one passage at a time (see `pipeline-overview.md`). Does **not** persist
anything itself; deciding final content is this class's job, writing it is `Writer`'s (`writer.md`).

```python
class DefaultMerger(Merger):
    def __init__(self, llm_client: OpenAICompatibleClient | None = None, cost_ledger: JsonlCostLedger | None = None) -> None: ...
    def merge(self, update: CompiledUpdate, writer: Writer, batch_id: int) -> CompiledUpdate: ...
    def summarize_source(self, source_slug: str, claim_texts: list[str], writer: Writer, batch_id: int) -> str: ...
```

`llm_client=None` disables the two LLM-backed behaviors below (D22 layer 2, and `summarize_source`) without
breaking `merge()` itself — see each section for exactly what degrades.

## Dedup: slug-exact, two passes

`merge()` does two sequential dedup passes, for claims and concepts independently:

1. **Within this update.** If the same batch/passage's `CompileWikiPages` call somehow produced two
   candidates with the same slug, they're merged into one *before* touching the `Writer` at all
   (`_merge_claims`/`_merge_concepts`'s `by_slug` dict).
2. **Against the `Writer`.** For each (now-deduped) candidate, `writer.read_claim(slug)`/`read_concept(slug)`
   checks whether a page with that slug already exists (written by an earlier passage in this same
   sequential Phase 2 loop, or from a previous batch entirely). If so, merge against it; if not, the
   candidate passes through unchanged.

**Dedup is slug-exact only.** Two candidates describing the same real-world entity under two different slugs
never get merged — that needs fuzzy/semantic matching (D22's "soft-collision dedup," explicitly deferred, see
below). This is a deliberate, documented scope limit, not an oversight.

## Claim merging — always deterministic

```python
@staticmethod
def _merge_claim_pair(base: Claim, new: Claim) -> Claim:
    return base.model_copy(update={
        "claim_text": new.claim_text or base.claim_text,
        "description": new.description or base.description,
        "source_ref": new.source_ref or base.source_ref,
        "confidence": max(base.confidence, new.confidence),
        "provenance_state": "merged",
        "related_concepts": _union(base.related_concepts, new.related_concepts),
        "contradicted_by": _union_contradictions(base.contradicted_by, new.contradicted_by),
    })
```

No LLM involvement at all for `Claim`s: `claim_text`/`description`/`source_ref` fall back to the new value if
present else the old; `confidence` takes the max; `provenance_state` always becomes `"merged"`;
`related_concepts` and `contradicted_by` are order-preserving unions (`contradicted_by` deduped by `.slug`,
first `reason` wins).

## Concept merging — D22's three-layer protection

```python
def _merge_concept_pair(self, base: Concept, new: Concept, batch_id: int) -> Concept:
    return base.model_copy(update={
        "concept_title": base.concept_title,                              # layer 3
        "aliases": _union(base.aliases, new.aliases),                     # layer 1
        "tags": _union(base.tags, new.tags),                              # layer 1
        "summary": self._merge_summary(base.summary, new.summary, batch_id),  # layers 1-2
        "description": new.description or base.description,              # simple fallback, not layered
        "key_facts": _union(base.key_facts, new.key_facts),               # layer 1 (rarely non-empty here — see writer.md)
        "related_pages": _union(base.related_pages, new.related_pages),   # layer 1
        "related_sources": _union(base.related_sources, new.related_sources),  # layer 1
    })
```

### Layer 1 — deterministic, always applied

Every array field (`aliases`, `tags`, `key_facts`, `related_pages`, `related_sources`) is a straightforward
order-preserving set union (`_union`: keep everything from `base`, append anything from `new` not already
present). No LLM call, no conflict possible — a union can't lose information.

`description` (D23 §5.4, extended beyond the original decision — see `TODO.md`) is not an array field, but
also stays outside D22's layered treatment: plain `new or old`, same as `Claim.claim_text`/`source_ref`. It's
index metadata, not body content — a stale or lost `description` just makes one `index.md` line less sharp,
not a real content-loss risk the way losing part of `summary` would be, so it doesn't earn the LLM-merge +
70%-rejection machinery layer 2 gives `summary`.

### Layer 2 — LLM merge + rejection, only on a *real* conflict

`summary` is the one field with genuine merge ambiguity: two candidate paragraphs describing the same
`Concept` might overlap, extend each other, or actually disagree. `_merge_summary`:

```python
def _merge_summary(self, old: str, new: str, batch_id: int) -> str:
    layer_1_result = new or old
    if not _has_real_conflict(old, new) or self._llm_client is None or self._cost_ledger is None:
        return layer_1_result
    merged = self._call_llm_merge(old, new, batch_id, self._llm_client, self._cost_ledger)
    threshold = 0.7 * max(len(old), len(new))
    if len(merged) < threshold:
        return old  # suspected content loss: reject, keep the old summary
    return merged
```

- **`_has_real_conflict(old, new)`** returns `False` (no LLM call needed) when either is empty, they're
  identical, or one is a substring of the other — a substring relationship is treated as pure
  concatenation/extension, which layer 1's `new or old` already handles correctly without an LLM call.
- **Only when there's a real conflict *and* an `llm_client` is configured** does this call the LLM (system
  prompt: merge the two summaries into one coherent summary, preserving every distinct fact from both — not
  capped to one paragraph; if either side already uses markdown `## ` subsections, the prompt asks the LLM to
  preserve/merge that structure rather than flattening it back into prose, see `entities.py`/`writer.md`).
  Cost recorded as stage `"Merger.summary_merge"`.
- **Rejection**: if the merged result is shorter than 70% of `max(len(old), len(new))`, it's treated as
  suspected content loss and discarded — the function returns the **old** summary (not `new`), on the theory
  that the previously-persisted value has already survived whatever validation got it written, while a
  drastically-shortened merge output is more likely to have silently dropped facts than to be a genuinely
  better summary. The 70% threshold is borrowed verbatim from `llm_wiki`'s `BODY_SHRINK_THRESHOLD` — not
  recalibrated against this project's own data (tracked as a known gap). Kept unchanged (character-length
  percentage, not e.g. a subsection-count check) even after `summary` stopped being capped to one paragraph —
  a deliberate scope decision, see `TODO.md`'s dated entry.
- **`llm_client=None` degrades gracefully, not to an error.** `merge()` is called unconditionally on every
  passage (unlike `Fixer.llm_periodic_fix`, which only runs every N batches and can afford to require an LLM
  client), so layer 2 being unavailable just means it's skipped — the function falls back to layer 1's
  `new or old`, i.e. exactly the pre-D22 behavior. This is a deliberate design choice, not a stopgap: it's
  what lets `DefaultMerger()` (no LLM client at all) still work standalone in tests.

### Layer 3 — locked fields, always applied

`concept_title` is **hardcoded to `base.concept_title`** in the `model_copy` call above — regardless of what
layer 2 (or anything else) produces, a `Concept`'s title can never change once it's first written. (The
proposal's D22 also names `type` and `created` as locked fields; this codebase doesn't have those as separate
domain fields — `type` lives only in OKF frontmatter, rendered by `Writer`, and there's no `created` field on
`Concept` at all — so `concept_title` is the only field this layer actually applies to here.)

## `Source.summary`: recursive batch-reduce (D21 §1.5)

```python
def summarize_source(self, source_slug: str, claim_texts: list[str], writer: Writer, batch_id: int) -> str:
    if not claim_texts:
        return ""
    if self._llm_client is None or self._cost_ledger is None:
        raise RuntimeError(...)
    return self._batch_reduce(claim_texts, batch_id, round_number=0)
```

Unlike `merge()`, this **does** require an `llm_client` (raises `RuntimeError` otherwise) — it's never called
with an empty `claim_texts` list from `Orchestrator` in a way that would matter, and when it is genuinely
needed, there's no deterministic fallback that makes sense for "write a summary paragraph."

Called once per source, after *every* passage of that source has been through Phase 2 — see
`pipeline-overview.md` for exactly when and why. `claim_texts` is the full list of `claim_text` values for
every `Claim` currently in that `Source`'s `produced_claims` backlink (re-read from `Writer`, not tracked
in-memory — see `core-types.md`).

### The algorithm

```python
def _batch_reduce(self, texts: list[str], batch_id: int, round_number: int) -> str:
    if len(texts) == 1 or _fits_budget(texts):
        return self._summarize_batch(texts, batch_id, round_number)
    batch_summaries = [self._summarize_batch(batch, batch_id, round_number) for batch in _split_into_batches(texts)]
    return self._batch_reduce(batch_summaries, batch_id, round_number + 1)
```

- **Budget check**: `_fits_budget(texts)` is `sum(len(t) for t in texts) <= 6000` (`_SOURCE_BUDGET_CHARS`)
  — a fixed character count, not a token count, borrowed in spirit (not exact mechanism) from `llm_wiki`'s
  `context-budget.ts` fixed-ratio-quota approach. Not recalibrated against real corpus data.
- **Fits**: one LLM call summarizes the whole list directly into the final `Source.summary`.
- **Doesn't fit**: `_split_into_batches` greedily groups `texts` into budget-sized chunks (preserving order),
  each chunk gets its own summarization call, and the *resulting summaries* become the new `texts` for a
  recursive call at `round_number + 1` — i.e. batch summaries get summarized again, recursively, until the
  list of texts fits in one call.
- **No round cap.** Deliberately unbounded — an explicit scope decision (D21), tracked as a risk (a document
  producing an extreme number of Claims could spike latency/cost or recurse for a long time; not yet
  validated against real data).

`summary` is not capped to one paragraph (extends beyond D23, see `TODO.md`'s dated entry) — the same system
prompt (`_SUMMARIZE_SOURCE_SYSTEM_PROMPT`) is used for every round, and covers both cases it's asked to
handle: round 0 (summarizing raw `claim_text`s) may structure the result with markdown `## ` subsections when
the source covers multiple distinct facets; a later round (summarizing a batch's *already-structured*
summaries) is asked to merge matching/related subsections rather than flattening everything back into plain
prose — effectively an "outline merge," a step up in complexity from round 0's plain summarization. The
budget check (`_fits_budget`) is unaffected either way — it bounds the *input* `texts` list, not `summary`'s
output length, so `_SOURCE_BUDGET_CHARS` needs no change; only the final `Source.summary` is expected to grow
noticeably longer than before for a source with many Claims across several facets.

Every call — whether summarizing raw claim texts or batch summaries — goes through the same
`_summarize_batch`, recording cost as stage `"Merger.summarize_source"` with a `round` field set to
`round_number` (`0` for the first pass over raw claims, `1`+ for each subsequent reduction round). This is
the one place in the codebase that uses `CostEvent.round` — see `cli-and-cost-ledger.md`.

## What's explicitly *not* implemented: soft-collision dedup

D22 also describes an LLM-based pass that would detect "these differently-named candidates are probably the
same real-world entity" (modeled on `llm_wiki`'s `dedup.ts`) — this is a deliberate, permanent architecture
placeholder, not a gap to fill in later by accident. `DefaultMerger`'s slug-exact dedup and the
`summarize_source`/three-layer-merge methods above were written without assuming slugs are the only way two
pages could refer to the same entity, so adding this later wouldn't require re-architecting `Merger`'s
interface — but this POC ships without it, same treatment as the `deepagents` skill-swap extension point
(both explicitly out of scope, see root `TODO.md`).
