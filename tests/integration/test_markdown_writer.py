"""Integration tests for MarkdownWriter — exercises the real filesystem."""

from pathlib import Path

import pytest

from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.domain.entities import Claim, Concept, ContradictionRef

pytestmark = pytest.mark.integration


def test_write_and_read_concept_round_trips(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    concept = Concept(slug="water", concept_title="Water", summary="A chemical compound.")

    writer.write_concept(concept)
    read_back = writer.read_concept("water")

    assert read_back == concept


def test_write_claim_maintains_related_concept_key_facts(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A chemical compound."))

    claim = Claim(
        slug="claim-1",
        claim_text="Water boils at 100C at sea level.",
        source_ref="doc-1#p3",
        confidence=0.9,
        provenance_state="extracted",
        related_concepts=["water"],
    )
    writer.write_claim(claim)

    concept = writer.read_concept("water")
    assert concept is not None
    assert concept.key_facts == ["claim-1"]


def test_write_claim_maintains_symmetric_contradiction(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    writer.write_claim(
        Claim(
            slug="claim-a",
            claim_text="The meeting was on Monday.",
            source_ref="doc-1#p1",
            confidence=0.6,
            provenance_state="extracted",
        )
    )

    writer.write_claim(
        Claim(
            slug="claim-b",
            claim_text="The meeting was on Tuesday.",
            source_ref="doc-2#p4",
            confidence=0.6,
            provenance_state="extracted",
            contradicted_by=[ContradictionRef(slug="claim-a", reason="conflicting weekday")],
        )
    )

    claim_a = writer.read_claim("claim-a")
    assert claim_a is not None
    assert claim_a.contradicted_by == [ContradictionRef(slug="claim-b", reason="conflicting weekday")]


def test_index_lists_all_pages(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A chemical compound."))
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="...",
            source_ref="doc-1#p1",
            confidence=0.5,
            provenance_state="extracted",
        )
    )

    index_text = (tmp_path / "index.md").read_text(encoding="utf-8")

    assert "[[water]]" in index_text
    assert "[[claim-1]]" in index_text


def test_list_pages_returns_all_slugs(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A chemical compound."))
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="...",
            source_ref="doc-1#p1",
            confidence=0.5,
            provenance_state="extracted",
        )
    )

    assert writer.list_pages() == ["claim-1", "water"]
