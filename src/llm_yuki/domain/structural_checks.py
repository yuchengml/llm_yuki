"""Pure, deterministic structural rules shared by two callers that check them at different times.

``adapters.validation.default_validator.DefaultValidator.structural_validate`` checks an in-flight
``CompiledUpdate`` before it is written; ``domain.error_book.ErrorBook.verify_and_close`` re-checks
already-persisted pages later. Both need the same rule (e.g. "is this ``source_ref`` well-formed"), so it is
defined once, here, with no I/O — this module only ever receives already-loaded ``Claim``/``Concept`` values.

Covers three of the seven error types from proposal ARCHITECTURE.md §4.1: Incomplete Pages, Malformed Refs,
and (via ``resolve_slug``) Dangling Links. Unseen Overwrite and Index Inconsistency are only meaningful at
structural-validate time (before a page is written) and are implemented directly in ``DefaultValidator``.
"""

from __future__ import annotations

import re

from llm_yuki.domain.entities import Claim, Concept

_SOURCE_REF_PATTERN = re.compile(r"^[\w./-]+(#[\w./-]+)?$")
"""Loose shape: a document/passage identifier, optionally followed by ``#locator`` (proposal §1.2)."""


def source_ref_well_formed(source_ref: str) -> bool:
    """Whether a ``source_ref`` string looks like a valid pointer into a Raw Source.

    Not a strict grammar — the proposal leaves the exact format open (§1.2 "出處指標") — just enough to
    catch the obvious failure modes: empty, whitespace-only, or containing characters no reference format
    would use.
    """
    stripped = source_ref.strip()
    return bool(stripped) and bool(_SOURCE_REF_PATTERN.match(stripped))


def claim_is_complete(claim: Claim) -> bool:
    """Whether a ``Claim`` has the content a page needs (proposal ARCHITECTURE.md §4.1, Incomplete Pages)."""
    return bool(claim.claim_text.strip()) and bool(claim.source_ref.strip())


def concept_is_complete(concept: Concept) -> bool:
    """Whether a ``Concept`` has the content a page needs."""
    return bool(concept.concept_title.strip()) and bool(concept.summary.strip())


def resolve_slug(slug: str, known_slugs: set[str]) -> bool:
    """Whether ``slug`` resolves against a set of known page slugs (Dangling Links, proposal §4.1 #1)."""
    return slug in known_slugs
