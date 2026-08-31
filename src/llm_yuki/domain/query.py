"""Query module (D25, proposal ARCHITECTURE.md §8) — the third Karpathy circle: Query.

Unlike Ingest/Compile (`domain/pipeline.py`) and Lint (`domain/error_book.py`), Query never writes to the
bundle — it only reads existing ``Claim``/``Concept``/``Source`` pages back through the ``Writer`` port and
synthesizes an answer. Domain-agnostic and I/O-free beyond the ``Writer`` port, same rule as the rest of
``domain/`` (AGENTS.md §4).

Two swappable top-level ``QueryEngine``s share the same building blocks:

- :class:`SinglePassQueryEngine` — search → RRF-fuse → one-hop graph-expand → read → synthesize, once.
- :class:`IterativeAgenticQueryEngine` — a ``wiki_search``/``wiki_read`` loop an LLM drives round by round,
  terminating on sufficiency, a tool-call budget (``T_max``), or a patience threshold (``P``) on consecutive
  empty searches — reconstructed from the LLM-Wiki paper's pseudocode
  (``docs/llm-yuki-v0.1-proposal/QUERY-SEARCH-SURVEY.md`` §2).

Embedding-based retrieval is an explicit, undone architecture placeholder this POC (D25) — see
``adapters/query/embedding_search.py::EmbeddingSearch``, which implements :class:`SearchStrategy` but raises
``NotImplementedError``.
"""

from __future__ import annotations

import abc
import math
import re
from dataclasses import dataclass, field
from typing import Literal

from llm_yuki.ports.writer import Writer

PageType = Literal["claim", "concept", "source"]

_DEFAULT_TOP_K = 8
_DEFAULT_SEED_COUNT = 5
_DEFAULT_RRF_K = 60.0
_DEFAULT_T_MAX = 6
_DEFAULT_PATIENCE = 2
_MIN_GRAPH_RATIO = 0.15
_MAX_GRAPH_RATIO = 0.30
_STRUCTURED_FIELD_WEIGHT = 3.0
_CONTENT_FIELD_WEIGHT = 1.0

_CJK_PATTERN = re.compile(r"[一-鿿㐀-䶿]")
_TOKEN_SPLIT_PATTERN = re.compile(r"[\s,.:;!?()\[\]{}\"'`~/\\|，。！？、；：「」『』（）—…·]+")


# -- Corpus snapshot ---------------------------------------------------------


@dataclass(frozen=True)
class PageRecord:
    """A read-only, type-flattened snapshot of one ``Claim``/``Concept``/``Source`` page.

    ``SearchStrategy``/fusion/graph-expansion all operate on a ``list[PageRecord]`` built once by
    :func:`load_corpus`, not on ``Writer`` directly — keeps every downstream step pure and trivially
    unit-testable with plain fixtures, matching ``domain/passage_splitter.py``'s style.
    """

    slug: str
    page_type: PageType
    title: str
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    description: str = ""
    content: str = ""
    links: list[str] = field(default_factory=list)
    """Slugs this page points to via any wikilink field (``related_concepts``/``related_pages``/
    ``key_facts``/``produced_claims``/``produced_concepts``/``related_sources``) — the graph-expansion edges
    (§8.3). Deliberately excludes ``Claim.contradicted_by``: that records a conflict, not a "related page"
    a query should navigate toward."""


def load_corpus(writer: Writer) -> list[PageRecord]:
    """Read every page in the bundle back through ``writer`` and flatten it into a ``PageRecord``.

    The only function in this module that touches the ``Writer`` port — everything downstream (search
    strategies, fusion, graph expansion) is pure, operating on the snapshot this returns. Tries
    ``read_concept``/``read_claim``/``read_source`` per slug in turn (same pattern as
    ``adapters/llm/extractor.py::_describe_page``), since ``Writer.list_pages()`` returns bare slugs with no
    type tag.
    """
    records: list[PageRecord] = []
    for slug in writer.list_pages():
        concept = writer.read_concept(slug)
        if concept is not None:
            records.append(
                PageRecord(
                    slug=concept.slug,
                    page_type="concept",
                    title=concept.concept_title,
                    aliases=concept.aliases,
                    tags=concept.tags,
                    description=concept.description,
                    content=concept.summary,
                    links=[*concept.related_pages, *concept.key_facts, *concept.related_sources],
                )
            )
            continue
        claim = writer.read_claim(slug)
        if claim is not None:
            records.append(
                PageRecord(
                    slug=claim.slug,
                    page_type="claim",
                    title=claim.slug,
                    description=claim.description,
                    content=claim.claim_text,
                    links=list(claim.related_concepts),
                )
            )
            continue
        source = writer.read_source(slug)
        if source is not None:
            records.append(
                PageRecord(
                    slug=source.slug,
                    page_type="source",
                    title=source.source_title,
                    description=source.description,
                    content=source.summary,
                    links=[*source.produced_claims, *source.produced_concepts, *source.related_pages],
                )
            )
    return records


# -- Search strategies --------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """One ranked result — a page slug, its score, and which signal produced it (for debugging/logging)."""

    slug: str
    score: float
    matched_field: str


class SearchStrategy(abc.ABC):
    """A retrieval signal: scores a corpus snapshot against a query, returns a ranked ``top_k``.

    Pure — no ``Writer``/network access here; a strategy that genuinely needs I/O (e.g. an embedding API
    call) belongs in ``adapters/`` instead (see ``adapters/query/embedding_search.py``).
    """

    @abc.abstractmethod
    def search(self, query: str, corpus: list[PageRecord], top_k: int) -> list[SearchHit]:
        """Return up to ``top_k`` hits from ``corpus``, best first."""
        raise NotImplementedError


class StructuredSignalSearch(SearchStrategy):
    """Structured-metadata-first keyword search — the one non-stub signal this POC ships (D25 decision 1).

    Matches the LLM-Wiki paper's description of ``wiki_search``: "prioritizing structured signals such as
    page names, aliases, tags, and descriptions before falling back to page content." A page whose structured
    fields (``title``/``aliases``/``tags``/``description``) match at all is scored from those alone; only a
    page with *no* structured match falls back to scoring its ``content`` (at a lower weight). Deliberately
    not BM25 — no IDF/document-length normalization, just weighted term-occurrence counting (same trade-off
    ``nashsu/llm_wiki``'s ``score_file`` makes — simpler than BM25, good enough for this POC).
    """

    def search(self, query: str, corpus: list[PageRecord], top_k: int) -> list[SearchHit]:
        """Score every page in ``corpus`` against ``query``'s tokens, return the best ``top_k``."""
        terms = _tokenize(query)
        if not terms:
            return []

        hits: list[SearchHit] = []
        for page in corpus:
            structured_score = _score_terms(terms, [page.title, *page.aliases, *page.tags, page.description])
            if structured_score > 0:
                hits.append(
                    SearchHit(
                        slug=page.slug, score=structured_score * _STRUCTURED_FIELD_WEIGHT, matched_field="structured"
                    )
                )
                continue
            content_score = _score_terms(terms, [page.content])
            if content_score > 0:
                hits.append(
                    SearchHit(slug=page.slug, score=content_score * _CONTENT_FIELD_WEIGHT, matched_field="content")
                )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]


def _tokenize(text: str) -> list[str]:
    """Lowercase + split on whitespace/punctuation; CJK runs also get bigrammed (no natural word boundary).

    Borrowed from ``QUERY-SEARCH-SURVEY.md`` §3.1's ``tokenizeQuery`` (``nashsu/llm_wiki``,
    ``src/lib/search.ts``) — every 2-character sliding window of a CJK token is kept alongside the individual
    characters and the whole token, deduplicated while preserving first-seen order.
    """
    raw_tokens = [token for token in _TOKEN_SPLIT_PATTERN.split(text.lower()) if token]
    tokens: list[str] = []
    for token in raw_tokens:
        if _CJK_PATTERN.search(token) and len(token) > 2:
            chars = list(token)
            tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
            tokens.extend(chars)
            tokens.append(token)
        else:
            tokens.append(token)
    return list(dict.fromkeys(tokens))


def _score_terms(terms: list[str], fields: list[str]) -> float:
    """Weighted-heuristic score: total occurrence count of every term across ``fields``, joined and lowercased."""
    haystack = " ".join(f for f in fields if f).lower()
    if not haystack:
        return 0.0
    return float(sum(haystack.count(term) for term in terms))


# -- Fusion + graph expansion --------------------------------------------------


def reciprocal_rank_fusion(rankings: list[list[SearchHit]], k: float = _DEFAULT_RRF_K) -> list[SearchHit]:
    """Merge several ranked lists into one via Reciprocal Rank Fusion: ``score += 1 / (k + rank)``.

    Borrowed verbatim from ``QUERY-SEARCH-SURVEY.md`` §3.2(b)'s ``apply_rrf_scores`` (``nashsu/llm_wiki``).
    Each strategy's ranking contributes independently — a slug appearing in more than one ranking accumulates
    more than one term. ``matched_field`` on the fused hit is whichever ranking first mentioned that slug.
    """
    scores: dict[str, float] = {}
    matched_field: dict[str, str] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.slug] = scores.get(hit.slug, 0.0) + 1.0 / (k + rank)
            matched_field.setdefault(hit.slug, hit.matched_field)

    fused = [SearchHit(slug=slug, score=score, matched_field=matched_field[slug]) for slug, score in scores.items()]
    fused.sort(key=lambda hit: hit.score, reverse=True)
    return fused


def graph_result_quota(limit: int, primary_hits: int) -> int:
    """How many of the final ``limit`` results one-hop graph expansion may claim (15%-30% of ``limit``).

    Borrowed from ``QUERY-SEARCH-SURVEY.md`` §3.2(c)'s ``graph_result_quota`` (``nashsu/llm_wiki``): a full
    primary-signal window leaves the minimum graph share; sparse primary retrieval moves progressively toward
    the maximum. This POC has no embedding signal (D25), so ``primary_hits`` is always
    ``StructuredSignalSearch``'s hit count alone — coverage is typically low, so the quota usually sits near
    the maximum.
    """
    if limit < 2:
        return 0
    coverage = min(primary_hits, limit) / limit
    ratio = _MAX_GRAPH_RATIO - (_MAX_GRAPH_RATIO - _MIN_GRAPH_RATIO) * coverage
    quota = math.ceil(limit * ratio)
    return max(1, min(quota, limit - 1))


def expand_via_wikilinks(seed_hits: list[SearchHit], corpus: list[PageRecord], quota: int) -> list[SearchHit]:
    """One-hop wikilink expansion from ``seed_hits``, capped at ``quota`` results.

    Each seed's neighbors (``PageRecord.links``) are scored ``1 / (seed_rank + 1)`` — a higher-ranked seed's
    neighbors score higher (``QUERY-SEARCH-SURVEY.md`` §3.2(c)'s ``blend_graph_results``). A neighbor reached
    from more than one seed keeps its best score. Neighbors already among the seeds, or not present in
    ``corpus`` (a dangling link — a structural-validation concern, not this function's), are skipped.
    """
    if quota <= 0 or not seed_hits:
        return []

    corpus_by_slug = {page.slug: page for page in corpus}
    seed_slugs = {hit.slug for hit in seed_hits}
    scored: dict[str, float] = {}
    for rank, hit in enumerate(seed_hits, start=1):
        seed_page = corpus_by_slug.get(hit.slug)
        if seed_page is None:
            continue
        weight = 1.0 / (rank + 1)
        for neighbor_slug in seed_page.links:
            if neighbor_slug in seed_slugs or neighbor_slug not in corpus_by_slug:
                continue
            scored[neighbor_slug] = max(scored.get(neighbor_slug, 0.0), weight)

    expanded = [SearchHit(slug=slug, score=score, matched_field="graph") for slug, score in scored.items()]
    expanded.sort(key=lambda hit: hit.score, reverse=True)
    return expanded[:quota]


def _merge_hits(*rankings: list[SearchHit]) -> list[SearchHit]:
    """Combine several hit lists, keeping each slug's best score, sorted best first."""
    best: dict[str, SearchHit] = {}
    for ranking in rankings:
        for hit in ranking:
            existing = best.get(hit.slug)
            if existing is None or hit.score > existing.score:
                best[hit.slug] = hit
    merged = list(best.values())
    merged.sort(key=lambda hit: hit.score, reverse=True)
    return merged


def retrieve(
    query: str,
    corpus: list[PageRecord],
    strategies: list[SearchStrategy],
    top_k: int = _DEFAULT_TOP_K,
    seed_count: int = _DEFAULT_SEED_COUNT,
) -> list[SearchHit]:
    """The retrieval half of :class:`SinglePassQueryEngine`, without the LLM synthesis step.

    Runs every strategy, fuses via :func:`reciprocal_rank_fusion`, expands one hop via
    :func:`expand_via_wikilinks` from the top-ranked seeds, merges both result sets, and returns the best
    ``top_k`` — no ``AnswerSynthesizer`` involved, so this needs no LLM client at all. Exists as a standalone,
    public function (not just inlined in ``SinglePassQueryEngine.answer``) so retrieval can be run and
    inspected on its own — e.g. the ``llm-yuki search`` CLI subcommand, or a unit test that only cares about
    ranking, not synthesis.
    """
    rankings = [strategy.search(query, corpus, top_k) for strategy in strategies]
    fused = reciprocal_rank_fusion(rankings)
    graph_hits = expand_via_wikilinks(fused[:seed_count], corpus, graph_result_quota(top_k, len(fused)))
    return _merge_hits(fused, graph_hits)[:top_k]


# -- Answer synthesis -----------------------------------------------------------


@dataclass(frozen=True)
class SynthesizedAnswer:
    """An ``AnswerSynthesizer``'s raw output — wrapped into a :class:`QueryAnswer` by the calling engine."""

    answer: str
    cited_slugs: list[str]


class AnswerSynthesizer(abc.ABC):
    """Turns a question + the pages a ``QueryEngine`` gathered into a cited answer.

    Citations are mandatory (D25 decision 3) — unlike ``nashsu/llm_wiki``, which leaves citing up to the
    agent's own judgment, every :class:`SynthesizedAnswer` here must name which page slugs it drew on.
    """

    @abc.abstractmethod
    def synthesize(self, question: str, pages: list[PageRecord], batch_id: int) -> SynthesizedAnswer:
        """Synthesize an answer to ``question`` grounded in ``pages``.

        ``batch_id`` identifies this call for cost-ledger recording (D19), same convention as
        ``domain/pipeline.py``'s ``Extractor``/``Validator``/``Fixer`` — it plays no role in synthesis itself.
        """
        raise NotImplementedError


# -- Agentic iteration ----------------------------------------------------------


@dataclass(frozen=True)
class EvidenceItem:
    """One round's outcome in :class:`IterativeAgenticQueryEngine`'s loop — a search's hits or a read's pages."""

    kind: Literal["search", "read"]
    hits: list[SearchHit] = field(default_factory=list)
    pages: list[PageRecord] = field(default_factory=list)


@dataclass(frozen=True)
class QueryAction:
    """A :class:`NextActionDecider`'s decision for one round of the agentic loop."""

    tool: Literal["wiki_search", "wiki_read", "stop"]
    query: str = ""
    slugs: list[str] = field(default_factory=list)


class NextActionDecider(abc.ABC):
    """Decides the agentic loop's next move, given the question and evidence gathered so far."""

    @abc.abstractmethod
    def decide(self, question: str, evidence: list[EvidenceItem]) -> QueryAction:
        """Return the next action: search again, read specific pages, or stop (evidence is sufficient)."""
        raise NotImplementedError


# -- Query engines ----------------------------------------------------------------


@dataclass(frozen=True)
class QueryAnswer:
    """The final result of a ``QueryEngine.answer`` call."""

    question: str
    answer: str
    cited_slugs: list[str]
    method: str


class QueryEngine(abc.ABC):
    """A swappable top-level query "search method" (D25 decision 2) — read-only against ``Writer``."""

    method_name: str

    @abc.abstractmethod
    def answer(self, question: str, writer: Writer, batch_id: int, top_k: int = _DEFAULT_TOP_K) -> QueryAnswer:
        """Answer ``question`` against the bundle ``writer`` reads from. Never writes."""
        raise NotImplementedError


class SinglePassQueryEngine(QueryEngine):
    """Karpathy-gist-style baseline: search → fuse → graph-expand → read → synthesize, once.

    Runs every configured :class:`SearchStrategy`, fuses their rankings via :func:`reciprocal_rank_fusion`,
    expands one hop via :func:`expand_via_wikilinks` from the top-ranked seeds, merges both result sets, and
    hands the resulting pages to an :class:`AnswerSynthesizer`. No iteration — proposal ARCHITECTURE.md §8.4.
    """

    method_name = "single_pass"

    def __init__(
        self,
        strategies: list[SearchStrategy],
        synthesizer: AnswerSynthesizer,
        seed_count: int = _DEFAULT_SEED_COUNT,
    ) -> None:
        if not strategies:
            raise ValueError("SinglePassQueryEngine requires at least one SearchStrategy.")
        self._strategies = strategies
        self._synthesizer = synthesizer
        self._seed_count = seed_count

    def answer(self, question: str, writer: Writer, batch_id: int, top_k: int = _DEFAULT_TOP_K) -> QueryAnswer:
        """Run the single-pass pipeline described in the class docstring."""
        corpus = load_corpus(writer)
        hits = retrieve(question, corpus, self._strategies, top_k=top_k, seed_count=self._seed_count)

        corpus_by_slug = {page.slug: page for page in corpus}
        pages = [corpus_by_slug[hit.slug] for hit in hits if hit.slug in corpus_by_slug]
        synthesized = self._synthesizer.synthesize(question, pages, batch_id)
        return QueryAnswer(
            question=question, answer=synthesized.answer, cited_slugs=synthesized.cited_slugs, method=self.method_name
        )


class IterativeAgenticQueryEngine(QueryEngine):
    """LLM-Wiki-paper-style agentic loop: LLM decides ``wiki_search``/``wiki_read``/stop, round by round.

    Reconstructed from ``QUERY-SEARCH-SURVEY.md`` §2's pseudocode. Terminates on any of three conditions
    (whichever comes first): the ``NextActionDecider`` returns ``stop``, ``T_max`` tool calls are spent, or
    ``patience`` consecutive empty searches occur. Every page seen — whether from a search hit or an explicit
    read — becomes candidate evidence for the final synthesis call. Proposal ARCHITECTURE.md §8.5.
    """

    method_name = "iterative_agentic"

    def __init__(
        self,
        strategy: SearchStrategy,
        decider: NextActionDecider,
        synthesizer: AnswerSynthesizer,
        t_max: int = _DEFAULT_T_MAX,
        patience: int = _DEFAULT_PATIENCE,
    ) -> None:
        self._strategy = strategy
        self._decider = decider
        self._synthesizer = synthesizer
        self._t_max = t_max
        self._patience = patience

    def answer(self, question: str, writer: Writer, batch_id: int, top_k: int = _DEFAULT_TOP_K) -> QueryAnswer:
        """Run the agentic loop described in the class docstring, then synthesize."""
        corpus = load_corpus(writer)
        corpus_by_slug = {page.slug: page for page in corpus}
        evidence: list[EvidenceItem] = []
        evidence_pages: dict[str, PageRecord] = {}
        consecutive_empty = 0
        tool_calls = 0

        while tool_calls < self._t_max and consecutive_empty < self._patience:
            action = self._decider.decide(question, evidence)
            tool_calls += 1

            if action.tool == "stop":
                break
            if action.tool == "wiki_search":
                hits = self._strategy.search(action.query, corpus, top_k)
                consecutive_empty = consecutive_empty + 1 if not hits else 0
                evidence.append(EvidenceItem(kind="search", hits=hits))
                for hit in hits:
                    page = corpus_by_slug.get(hit.slug)
                    if page is not None:
                        evidence_pages.setdefault(page.slug, page)
            elif action.tool == "wiki_read":
                pages = [corpus_by_slug[slug] for slug in action.slugs if slug in corpus_by_slug]
                evidence.append(EvidenceItem(kind="read", pages=pages))
                for page in pages:
                    evidence_pages[page.slug] = page

        pages_for_synthesis = list(evidence_pages.values())[:top_k]
        synthesized = self._synthesizer.synthesize(question, pages_for_synthesis, batch_id)
        return QueryAnswer(
            question=question, answer=synthesized.answer, cited_slugs=synthesized.cited_slugs, method=self.method_name
        )
