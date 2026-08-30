"""Unit tests for search strategies, fusion, and graph expansion (`domain/query.py`) — all pure, no I/O."""

from __future__ import annotations

import pytest

from llm_yuki.domain.query import (
    PageRecord,
    SearchHit,
    StructuredSignalSearch,
    expand_via_wikilinks,
    graph_result_quota,
    reciprocal_rank_fusion,
)

pytestmark = pytest.mark.unit


# -- StructuredSignalSearch ---------------------------------------------------------


def _page(slug: str, **kwargs: object) -> PageRecord:
    defaults: dict[str, object] = {"page_type": "concept", "title": slug}
    defaults.update(kwargs)
    return PageRecord(slug=slug, **defaults)  # type: ignore[arg-type]


def test_structured_signal_search_empty_query_returns_no_hits() -> None:
    corpus = [_page("water", title="Water")]

    assert StructuredSignalSearch().search("", corpus, top_k=5) == []


def test_structured_signal_search_matches_title_over_unrelated_pages() -> None:
    corpus = [_page("water", title="Water"), _page("fire", title="Fire")]

    hits = StructuredSignalSearch().search("water", corpus, top_k=5)

    assert [hit.slug for hit in hits] == ["water"]
    assert hits[0].matched_field == "structured"


def test_structured_signal_search_prefers_structured_match_over_content_only_match() -> None:
    # "water" appears in fire's content but only as a stray mention; water's title matches directly.
    corpus = [
        _page("water", title="Water"),
        _page("fire", title="Fire", content="Fire needs water to be extinguished."),
    ]

    hits = StructuredSignalSearch().search("water", corpus, top_k=5)

    assert hits[0].slug == "water"
    assert hits[0].matched_field == "structured"
    assert hits[1].slug == "fire"
    assert hits[1].matched_field == "content"
    assert hits[0].score > hits[1].score


def test_structured_signal_search_falls_back_to_content_when_no_structured_match() -> None:
    corpus = [_page("claim-1", page_type="claim", title="claim-1", content="Water boils at 100C.")]

    hits = StructuredSignalSearch().search("boils", corpus, top_k=5)

    assert hits[0].slug == "claim-1"
    assert hits[0].matched_field == "content"


def test_structured_signal_search_respects_top_k() -> None:
    corpus = [_page(f"water-{i}", title=f"Water {i}") for i in range(5)]

    hits = StructuredSignalSearch().search("water", corpus, top_k=2)

    assert len(hits) == 2


def test_structured_signal_search_matches_aliases_and_tags() -> None:
    corpus = [_page("h2o", title="Dihydrogen Monoxide", aliases=["H2O"], tags=["chemistry"])]

    assert [h.slug for h in StructuredSignalSearch().search("H2O", corpus, top_k=5)] == ["h2o"]
    assert [h.slug for h in StructuredSignalSearch().search("chemistry", corpus, top_k=5)] == ["h2o"]


def test_structured_signal_search_handles_cjk_query() -> None:
    corpus = [_page("water-zh", title="水", description="水是一種化合物")]

    hits = StructuredSignalSearch().search("化合物", corpus, top_k=5)

    assert [h.slug for h in hits] == ["water-zh"]


# -- reciprocal_rank_fusion ---------------------------------------------------------


def test_rrf_preserves_order_for_a_single_ranking() -> None:
    ranking = [
        SearchHit(slug="a", score=1.0, matched_field="structured"),
        SearchHit(slug="b", score=0.5, matched_field="structured"),
    ]

    fused = reciprocal_rank_fusion([ranking])

    assert [hit.slug for hit in fused] == ["a", "b"]


def test_rrf_boosts_slug_present_in_multiple_rankings() -> None:
    ranking_1 = [SearchHit(slug="a", score=1.0, matched_field="s"), SearchHit(slug="b", score=0.9, matched_field="s")]
    ranking_2 = [SearchHit(slug="b", score=1.0, matched_field="s"), SearchHit(slug="c", score=0.9, matched_field="s")]

    fused = reciprocal_rank_fusion([ranking_1, ranking_2])

    # "b" is ranked in both lists, so it should out-score "a"/"c", each ranked in only one.
    assert fused[0].slug == "b"


def test_rrf_empty_rankings_returns_empty() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[]]) == []


# -- graph_result_quota ---------------------------------------------------------


def test_graph_result_quota_zero_below_limit_two() -> None:
    assert graph_result_quota(limit=1, primary_hits=0) == 0
    assert graph_result_quota(limit=0, primary_hits=0) == 0


def test_graph_result_quota_moves_toward_max_when_primary_coverage_is_sparse() -> None:
    sparse = graph_result_quota(limit=10, primary_hits=0)
    full = graph_result_quota(limit=10, primary_hits=10)

    assert sparse >= full
    assert 1 <= full <= 9
    assert 1 <= sparse <= 9


# -- expand_via_wikilinks ---------------------------------------------------------


def test_expand_via_wikilinks_returns_empty_without_seeds_or_quota() -> None:
    corpus = [_page("a", links=["b"])]

    assert expand_via_wikilinks([], corpus, quota=5) == []
    assert expand_via_wikilinks([SearchHit(slug="a", score=1.0, matched_field="s")], corpus, quota=0) == []


def test_expand_via_wikilinks_finds_one_hop_neighbors() -> None:
    corpus = [_page("a", links=["b", "c"]), _page("b"), _page("c")]
    seeds = [SearchHit(slug="a", score=1.0, matched_field="structured")]

    expanded = expand_via_wikilinks(seeds, corpus, quota=5)

    assert {hit.slug for hit in expanded} == {"b", "c"}
    assert all(hit.matched_field == "graph" for hit in expanded)


def test_expand_via_wikilinks_excludes_seeds_and_dangling_links() -> None:
    corpus = [_page("a", links=["a", "b", "ghost"]), _page("b")]  # "ghost" doesn't exist in corpus
    seeds = [SearchHit(slug="a", score=1.0, matched_field="structured")]

    expanded = expand_via_wikilinks(seeds, corpus, quota=5)

    assert {hit.slug for hit in expanded} == {"b"}


def test_expand_via_wikilinks_respects_quota() -> None:
    corpus = [_page("a", links=["b", "c", "d"]), _page("b"), _page("c"), _page("d")]
    seeds = [SearchHit(slug="a", score=1.0, matched_field="structured")]

    expanded = expand_via_wikilinks(seeds, corpus, quota=2)

    assert len(expanded) == 2
