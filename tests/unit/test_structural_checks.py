"""Unit tests for domain.structural_checks — pure functions, no I/O."""

from __future__ import annotations

import pytest

from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.structural_checks import (
    claim_is_complete,
    concept_is_complete,
    resolve_slug,
    source_ref_well_formed,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("doc-1#p3", True),
        ("doc-1", True),
        ("doc-1/images/fig1.png", True),
        ("", False),
        ("   ", False),
        ("doc 1#p3", False),
        ("doc-1#p3\nextra", False),
    ],
)
def test_source_ref_well_formed(value: str, expected: bool) -> None:
    assert source_ref_well_formed(value) is expected


def test_claim_is_complete_requires_text_and_source_ref() -> None:
    complete = Claim(
        slug="c1",
        claim_text="Water boils at 100C.",
        source_ref="doc-1#p1",
        confidence=0.9,
        provenance_state="extracted",
    )
    assert claim_is_complete(complete) is True

    empty_text = complete.model_copy(update={"claim_text": "  "})
    assert claim_is_complete(empty_text) is False

    empty_ref = complete.model_copy(update={"source_ref": ""})
    assert claim_is_complete(empty_ref) is False


def test_concept_is_complete_requires_title_and_summary() -> None:
    complete = Concept(slug="water", concept_title="Water", summary="A chemical compound.")
    assert concept_is_complete(complete) is True

    assert concept_is_complete(complete.model_copy(update={"concept_title": ""})) is False
    assert concept_is_complete(complete.model_copy(update={"summary": "   "})) is False


def test_resolve_slug() -> None:
    assert resolve_slug("water", {"water", "ice"}) is True
    assert resolve_slug("fire", {"water", "ice"}) is False
