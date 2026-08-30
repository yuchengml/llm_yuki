"""Integration test for the deliberately-unimplemented ``EmbeddingSearch`` stub (D25 decision 1)."""

from __future__ import annotations

import pytest

from llm_yuki.adapters.query.embedding_search import EmbeddingSearch

pytestmark = pytest.mark.integration


def test_embedding_search_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="D25"):
        EmbeddingSearch().search("water", corpus=[], top_k=5)
