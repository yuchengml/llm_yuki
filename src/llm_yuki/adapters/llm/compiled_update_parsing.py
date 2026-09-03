"""Shared JSON→``CompiledUpdate`` parsing for any LLM-backed stage that returns Claim/Concept candidates.

Used by ``LLMExtractor.compile_wiki_pages`` and ``DefaultFixer.llm_periodic_fix`` — both ask the LLM for the
same ``{"claims": [...], "concepts": [...]}`` shape, so the parsing/validation lives in one place.
"""

from __future__ import annotations

from pydantic import ValidationError

from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.pipeline import CompiledUpdate
from llm_yuki.logging import get_logger

logger = get_logger(__name__)


def parse_compiled_update(payload: dict[str, object], *, context: str) -> CompiledUpdate:
    """Parse a ``{"claims": [...], "concepts": [...]}`` payload into a :class:`CompiledUpdate`.

    Strips any LLM-supplied ``key_facts`` on concepts — that backlink is maintained by the ``Writer``, not
    the LLM (proposal ARCHITECTURE.md §2.3.2), so a value the LLM invented here would just be overwritten
    (or worse, momentarily wrong) rather than trusted.

    Each candidate is validated **independently**: a single malformed Claim/Concept (e.g. a required field
    the LLM omitted) is logged and dropped, not treated as a reason to discard every other candidate in the
    same response — a passage that yields 5 good claims and 1 malformed concept should still contribute
    those 5 claims, not lose everything because of the one bad item (real-world failure that motivated this:
    a single ``Concept`` missing ``concept_title`` was enough to abort an entire batch under the old
    all-or-nothing validation — see ``TODO.md``'s dated note). Only a structurally broken payload
    (``claims``/``concepts`` not even a list) is still fatal — that's not "one bad item," it's not a response
    this function can make sense of at all.
    """
    raw_claims = payload.get("claims", [])
    raw_concepts = payload.get("concepts", [])
    if not isinstance(raw_claims, list) or not isinstance(raw_concepts, list):
        raise LLMOutputError(f"{context}: 'claims' and 'concepts' must both be lists")

    claims: list[Claim] = []
    for item in raw_claims:
        try:
            claims.append(Claim.model_validate(item))
        except ValidationError as exc:
            logger.warning("%s: skipping malformed claim %r: %s", context, item, exc)

    concepts: list[Concept] = []
    for item in raw_concepts:
        try:
            concepts.append(Concept.model_validate(_without_key_facts(item)))
        except ValidationError as exc:
            logger.warning("%s: skipping malformed concept %r: %s", context, item, exc)

    return CompiledUpdate(claims=claims, concepts=concepts)


def _without_key_facts(item: object) -> object:
    if isinstance(item, dict):
        return {k: v for k, v in item.items() if k != "key_facts"}
    return item
