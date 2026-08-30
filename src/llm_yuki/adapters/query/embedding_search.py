"""``EmbeddingSearch``: the embedding-based ``SearchStrategy`` — deliberately unimplemented (D25 decision 1).

``docs/llm-yuki-v0.1-proposal/README.md`` D25 decided this POC ships only ``StructuredSignalSearch`` (keyword/
structured-signal search) plus one-hop graph expansion as retrieval signals. Embedding-based semantic
retrieval is left as an architecture placeholder — the ``SearchStrategy`` interface accommodates it without
any change to ``QueryEngine``, but no embedding provider is wired up this POC (same "leave room, don't build
it" treatment D16 gives the ``deepagents`` skill-swap point and D22 gives soft-collision dedup).

Lives under ``adapters/`` rather than ``domain/`` because a real implementation would need to call an
embedding API — genuine I/O, same reasoning that puts ``LLMExtractor`` in ``adapters/llm/`` instead of
``domain/pipeline.py``.
"""

from __future__ import annotations

from llm_yuki.domain.query import PageRecord, SearchHit, SearchStrategy


class EmbeddingSearch(SearchStrategy):
    """Stub ``SearchStrategy`` — raises :class:`NotImplementedError` on every call.

    Exists so callers assembling a ``QueryEngine``'s strategy list can see this signal listed (and choose not
    to include it) rather than it silently not existing at all. Do not catch/suppress the exception this
    raises — a caller that wants embedding search must actually implement this class first.
    """

    def search(self, query: str, corpus: list[PageRecord], top_k: int) -> list[SearchHit]:
        """Always raises — see the class docstring."""
        raise NotImplementedError(
            "EmbeddingSearch is an explicit, unimplemented architecture placeholder for this POC "
            "(docs/llm-yuki-v0.1-proposal/README.md D25) — no embedding provider is wired up. "
            "Do not include this strategy in a QueryEngine until a real implementation replaces this stub."
        )
