"""Shared JSON→``CompiledUpdate`` parsing for any LLM-backed stage that returns Claim/Concept candidates.

Used by ``LLMExtractor.compile_wiki_pages`` and ``DefaultFixer.llm_periodic_fix`` — both ask the LLM for the
same ``{"claims": [...], "concepts": [...]}`` shape, so the parsing/validation lives in one place.
"""

from __future__ import annotations

from pydantic import ValidationError

from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.pipeline import CompiledUpdate


def parse_compiled_update(payload: dict[str, object], *, context: str) -> CompiledUpdate:
    """Parse a ``{"claims": [...], "concepts": [...]}`` payload into a :class:`CompiledUpdate`.

    Strips any LLM-supplied ``key_facts`` on concepts — that backlink is maintained by the ``Writer``, not
    the LLM (proposal ARCHITECTURE.md §2.3.2), so a value the LLM invented here would just be overwritten
    (or worse, momentarily wrong) rather than trusted.
    """
    raw_claims = payload.get("claims", [])
    raw_concepts = payload.get("concepts", [])
    if not isinstance(raw_claims, list) or not isinstance(raw_concepts, list):
        raise LLMOutputError(f"{context}: 'claims' and 'concepts' must both be lists")

    try:
        claims = [Claim.model_validate(item) for item in raw_claims]
        concepts = [Concept.model_validate(_without_key_facts(item)) for item in raw_concepts]
    except ValidationError as exc:
        raise LLMOutputError(f"{context}: response did not match Claim/Concept schema: {exc}") from exc

    return CompiledUpdate(claims=claims, concepts=concepts)


def _without_key_facts(item: object) -> object:
    if isinstance(item, dict):
        return {k: v for k, v in item.items() if k != "key_facts"}
    return item
