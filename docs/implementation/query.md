# Query

Module: `domain/query.py`, plus `adapters/query/embedding_search.py` and `adapters/llm/answer_synthesizer.py`/
`adapters/llm/next_action_decider.py`. Implements D25 — the third Karpathy circle (Query), on top of the
`Ingest`/`Compile` (`pipeline-overview.md`) and `Lint` (`error-book.md`) circles already covered elsewhere in
this directory. Unlike those, Query never writes to the bundle: every entry point here only reads through
`Writer` and returns an answer.

## The pieces, top to bottom

```python
def load_corpus(writer: Writer) -> list[PageRecord]: ...

class SearchStrategy(abc.ABC):
    def search(self, query: str, corpus: list[PageRecord], top_k: int) -> list[SearchHit]: ...

class StructuredSignalSearch(SearchStrategy): ...          # domain/query.py — the one non-stub signal
class EmbeddingSearch(SearchStrategy): ...                 # adapters/query/embedding_search.py — NotImplementedError

def reciprocal_rank_fusion(rankings: list[list[SearchHit]], k: float = 60.0) -> list[SearchHit]: ...
def graph_result_quota(limit: int, primary_hits: int) -> int: ...
def expand_via_wikilinks(seed_hits: list[SearchHit], corpus: list[PageRecord], quota: int) -> list[SearchHit]: ...

class AnswerSynthesizer(abc.ABC):
    def synthesize(self, question: str, pages: list[PageRecord], batch_id: int) -> SynthesizedAnswer: ...

class NextActionDecider(abc.ABC):
    def decide(self, question: str, evidence: list[EvidenceItem]) -> QueryAction: ...

class QueryEngine(abc.ABC):
    def answer(self, question: str, writer: Writer, batch_id: int, top_k: int = 8) -> QueryAnswer: ...

class SinglePassQueryEngine(QueryEngine): ...      # search -> fuse -> graph-expand -> read -> synthesize, once
class IterativeAgenticQueryEngine(QueryEngine): ...  # wiki_search/wiki_read loop, T_max/patience termination
```

Everything except `load_corpus` (which reads through the `Writer` port) is pure — no filesystem/network access
— so `SearchStrategy`/fusion/graph-expansion/the two engines' control flow are all unit-tested with plain
fixtures (`tests/unit/test_query_*.py`), the same discipline `passage_splitter.md` documents for the Compile
side.

## `load_corpus` — the one function that touches `Writer`

```python
def load_corpus(writer: Writer) -> list[PageRecord]:
    for slug in writer.list_pages():
        # tries read_concept -> read_claim -> read_source, same pattern as
        # adapters/llm/extractor.py::_describe_page — Writer.list_pages() returns bare slugs, no type tag
        ...
```

Flattens each `Claim`/`Concept`/`Source` into a type-agnostic `PageRecord`:

| `PageRecord` field | `Claim` | `Concept` | `Source` |
|---|---|---|---|
| `title` | `slug` (no separate title field) | `concept_title` | `source_title` |
| `aliases`/`tags` | `[]` | `aliases`/`tags` | `[]` |
| `description` | `description` | `description` | `description` |
| `content` | `claim_text` | `summary` | `summary` |
| `links` | `related_concepts` | `related_pages` + `key_facts` + `related_sources` | `produced_claims` + `produced_concepts` + `related_pages` |

`links` deliberately excludes `Claim.contradicted_by` — that field records a conflict, not a "related page" a
query should navigate toward (see `core-types.md` on why it's a lint-candidate signal, not a wikilink).

## `StructuredSignalSearch` — the retrieval signal this POC actually ships

Matches the LLM-Wiki paper's `wiki_search` description (`QUERY-SEARCH-SURVEY.md` §2): structured fields first,
content only as a fallback.

```python
def search(self, query: str, corpus: list[PageRecord], top_k: int) -> list[SearchHit]:
    terms = _tokenize(query)
    for page in corpus:
        structured_score = _score_terms(terms, [page.title, *page.aliases, *page.tags, page.description])
        if structured_score > 0:
            hits.append(SearchHit(..., score=structured_score * 3.0, matched_field="structured"))
            continue  # a structured match means content is never even scored for this page
        content_score = _score_terms(terms, [page.content])
        if content_score > 0:
            hits.append(SearchHit(..., score=content_score * 1.0, matched_field="content"))
```

- `_tokenize`: lowercase + split on whitespace/punctuation; a CJK run (no natural word boundary) also gets
  every 2-character sliding window added alongside the individual characters and the whole token — borrowed
  from `QUERY-SEARCH-SURVEY.md` §3.1's `tokenizeQuery` (`nashsu/llm_wiki`).
- `_score_terms`: total occurrence count of every term across the joined, lowercased fields — a weighted
  heuristic, not BM25 (no IDF/document-length normalization), same trade-off `nashsu/llm_wiki`'s `score_file`
  makes.
- **`EmbeddingSearch`** (`adapters/query/embedding_search.py`) implements the same `SearchStrategy` interface
  but its `search()` always raises `NotImplementedError` — an explicit, undone architecture placeholder (D25
  decision 1). Do not catch this exception anywhere; a caller that wants embedding search must replace the
  stub with a real implementation first.

## Fusion + one-hop graph expansion

Both borrowed verbatim (formula-wise) from `QUERY-SEARCH-SURVEY.md` §3.2 (`nashsu/llm_wiki`'s
`search.rs`):

- `reciprocal_rank_fusion(rankings, k=60.0)`: standard RRF — `score += 1 / (k + rank)` per ranking a slug
  appears in, summed across rankings. This POC only ever passes it a single-element `rankings` list (just
  `StructuredSignalSearch`'s output), since `EmbeddingSearch` isn't implemented — the fusion step is still
  wired in so adding a second signal later needs no change to either `QueryEngine`.
- `graph_result_quota(limit, primary_hits)`: how many of the final `limit` results one-hop expansion may
  claim, 15%-30% of `limit` depending on primary-signal coverage (sparse coverage -> moves toward 30%). With
  no embedding signal, `primary_hits` is always `StructuredSignalSearch`'s hit count, so coverage is usually
  low and the quota usually sits near the maximum.
- `expand_via_wikilinks(seed_hits, corpus, quota)`: from the top-ranked fused hits, walks one hop along
  `PageRecord.links`, scoring each neighbor `1 / (seed_rank + 1)` (a higher-ranked seed's neighbors score
  higher). A neighbor reached from more than one seed keeps its best score. Skips neighbors already among the
  seeds, and dangling links (a neighbor slug not present in `corpus`) — same "not this function's job"
  treatment `MarkdownWriter._maintain_claim_backlinks` gives a dangling `related_concepts` target.

## `SinglePassQueryEngine` — the baseline

```python
def answer(self, question, writer, batch_id, top_k=8) -> QueryAnswer:
    corpus = load_corpus(writer)
    rankings = [strategy.search(question, corpus, top_k) for strategy in self._strategies]
    fused = reciprocal_rank_fusion(rankings)
    graph_hits = expand_via_wikilinks(fused[:5], corpus, graph_result_quota(top_k, len(fused)))
    hits = _merge_hits(fused, graph_hits)[:top_k]
    pages = [corpus_by_slug[hit.slug] for hit in hits if hit.slug in corpus_by_slug]
    return self._synthesizer.synthesize(question, pages, batch_id)  # wrapped into a QueryAnswer
```

Karpathy-gist-style: `search -> read -> synthesize`, once, no iteration. `method_name = "single_pass"`.
Constructor requires at least one `SearchStrategy` (raises `ValueError` otherwise).

## `IterativeAgenticQueryEngine` — the agentic loop

Reconstructed from `QUERY-SEARCH-SURVEY.md` §2's pseudocode (the LLM-Wiki paper's own algorithm was never
published — this is the survey's own faithful reconstruction from the paper's prose):

```python
while tool_calls < self._t_max and consecutive_empty < self._patience:
    action = self._decider.decide(question, evidence)
    tool_calls += 1
    if action.tool == "stop":
        break
    if action.tool == "wiki_search":
        hits = self._strategy.search(action.query, corpus, top_k)
        consecutive_empty = consecutive_empty + 1 if not hits else 0
        evidence.append(EvidenceItem(kind="search", hits=hits))
        # every hit's page is also added to evidence_pages — a search that never gets an explicit
        # wiki_read still contributes candidate pages to the final synthesis call
    elif action.tool == "wiki_read":
        pages = [corpus_by_slug[slug] for slug in action.slugs if slug in corpus_by_slug]
        evidence.append(EvidenceItem(kind="read", pages=pages))
        # these pages overwrite/confirm their entry in evidence_pages
```

- **Three termination conditions, first one wins**: the decider returns `"stop"`; `tool_calls` reaches
  `t_max` (default 6); or `consecutive_empty` (searches in a row with zero hits) reaches `patience` (default
  2). `tool_calls` increments on every decide() call, including a `wiki_read` or `stop` — not just searches.
- A `wiki_read` targeting a slug that never appeared in an earlier search's evidence is silently dropped (not
  an error) — the prompt (`adapters/llm/next_action_decider.py`) instructs the LLM never to invent one, but
  the engine itself doesn't trust that instruction blindly.
- `evidence_pages` (a `dict[str, PageRecord]`, insertion order preserved by Python's dict) accumulates from
  *both* search hits and explicit reads — even a transcript that only ever calls `wiki_search` and never
  `wiki_read` still has something to synthesize from.
- `method_name = "iterative_agentic"`. `T_max`/`patience` are constructor arguments (`--t-max`/`--patience` on
  the CLI) — this POC doesn't lock in specific numbers (D25 "明確排除"); tune them once real `M3SciQA`/
  `MMDocRAG` data is run through this engine.

## `AnswerSynthesizer` / `NextActionDecider` — the two LLM-backed steps

Both `adapters/llm/answer_synthesizer.py::LLMAnswerSynthesizer` and
`adapters/llm/next_action_decider.py::LLMActionDecider` are the same shape as `LLMExtractor`
(`extractor.md`): a system prompt, a JSON response parsed via `adapters/llm/json_utils.py::parse_json_object`,
`LLMOutputError` on any schema mismatch, and cost recorded via `JsonlCostLedger` (stages
`"AnswerSynthesizer.Synthesize"` / `"NextActionDecider.Decide"`).

- **`LLMAnswerSynthesizer.synthesize`**: skips the LLM call entirely when `pages` is empty (same
  "nothing to select from, don't spend a call" precedent as `LLMExtractor.select_pages` on an empty bundle),
  returning a canned "no pages were found" answer instead. Otherwise sends every page's slug/title/content and
  parses `{"answer": "...", "cited_slugs": [...]}`. **`cited_slugs` is filtered to only the slugs actually
  present in `pages`** — a hallucinated citation is dropped, not treated as fatal, the same defensive-filtering
  precedent `LLMExtractor.select_pages` uses for a hallucinated slug.
- **`LLMActionDecider.decide`**: sends the question plus every prior round's evidence (`_format_evidence` —
  search rounds render as `slug (score=...)` pairs, read rounds as `slug: <first 200 chars of content>`), and
  parses one of three JSON shapes (`wiki_search`/`wiki_read`/`stop`). An empty/whitespace-only `query` on a
  `wiki_search` action, or a non-list `slugs` on `wiki_read`, or any other `tool` value, raises
  `LLMOutputError` — these are treated as fatal (unlike a hallucinated citation above), since there's no safe
  default action to fall back to mid-loop.

## `QueryAnswer` and citations

```python
@dataclass(frozen=True)
class QueryAnswer:
    question: str
    answer: str
    cited_slugs: list[str]
    method: str  # "single_pass" | "iterative_agentic"
```

Citations are mandatory by construction here — both engines always route through an `AnswerSynthesizer`, whose
prompt requires `cited_slugs`, unlike `nashsu/llm_wiki` which leaves citing up to the agent's own judgment
(D25 decision 3).

## CLI

`llm-yuki query <bundle_dir> "<question>" [--method single-pass|agentic] [--top-k N] [--batch-id N]
[--pipeline-state-dir DIR] [--t-max N] [--patience N]` — see `cli-and-cost-ledger.md`'s sibling command
(`compile`) for the shared `.env`/LLM-config-fail-fast behavior; `query` follows the identical pattern
(`src/llm_yuki/cli.py::_run_query`). Read-only against `bundle_dir` — never calls a `Writer.write_*` method
(D25 decision 4: query results are not filed back into the wiki this POC).

## Explicitly out of scope this POC (D25)

- A real `EmbeddingSearch` implementation — see the section above.
- Writing query results/synthesized answers back into the bundle as new pages.
- Locking in specific `T_max`/`patience` numbers, or a formal query-latency SLA.
- Throughput/latency comparison between the two `QueryEngine`s — both exist to each be validated against
  `M3SciQA`/`MMDocRAG` (D8), not to be benchmarked against each other.
