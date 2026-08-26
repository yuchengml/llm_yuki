"""Unit tests for llm_yuki.domain.entities — no filesystem access."""

import pytest
from pydantic import ValidationError

from llm_yuki.domain.entities import Claim, Concept, ContradictionRef

pytestmark = pytest.mark.unit


def test_claim_valid_construction_succeeds() -> None:
    claim = Claim(
        slug="claim-1",
        claim_text="Water boils at 100C at sea level.",
        source_ref="doc-1#p3",
        confidence=0.9,
        provenance_state="extracted",
    )

    assert claim.related_concepts == []
    assert claim.contradicted_by == []


def test_claim_confidence_out_of_range_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        Claim(
            slug="claim-1",
            claim_text="...",
            source_ref="doc-1#p3",
            confidence=1.5,
            provenance_state="extracted",
        )


def test_claim_invalid_provenance_state_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        Claim(
            slug="claim-1",
            claim_text="...",
            source_ref="doc-1#p3",
            confidence=0.5,
            provenance_state="guessed",  # type: ignore[arg-type]
        )


def test_claim_contradicted_by_holds_slug_and_reason() -> None:
    claim = Claim(
        slug="claim-1",
        claim_text="...",
        source_ref="doc-1#p3",
        confidence=0.5,
        provenance_state="ambiguous",
        contradicted_by=[ContradictionRef(slug="claim-2", reason="conflicting dates")],
    )

    assert claim.contradicted_by[0].slug == "claim-2"
    assert claim.contradicted_by[0].reason == "conflicting dates"


def test_concept_defaults_to_empty_collections() -> None:
    concept = Concept(slug="concept-1", concept_title="Water", summary="A chemical compound.")

    assert concept.aliases == []
    assert concept.key_facts == []
    assert concept.related_pages == []
