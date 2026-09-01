"""Integration tests for MarkdownWriter — exercises the real filesystem."""

from pathlib import Path

import pytest

from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.domain.entities import Claim, Concept, ContradictionRef, Source

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


def test_write_and_read_source_round_trips(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    source = Source(
        slug="doc-1",
        source_title="Doc 1",
        source_path="raw_sources/doc-1",
        ingested_at="2026-08-27",
        summary="A short document.",
    )

    writer.write_source(source)
    read_back = writer.read_source("doc-1")

    # description is deterministically overwritten by the Writer on every write (D23 §5.4) — never LLM
    # output, so the round-trip isn't a plain equality check against the as-constructed Source. It's plain
    # discourse (the flattened summary), never a "source_title: ..." composite.
    assert read_back == source.model_copy(update={"description": "A short document."})


def test_write_claim_maintains_source_backlinks(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    writer.write_source(
        Source(
            slug="doc-1",
            source_title="Doc 1",
            source_path="raw_sources/doc-1",
            ingested_at="2026-08-27",
            summary="A short document.",
        )
    )
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A chemical compound."))

    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="Water boils at 100C at sea level.",
            source_ref="doc-1#p3",
            confidence=0.9,
            provenance_state="extracted",
            related_concepts=["water"],
        )
    )

    source = writer.read_source("doc-1")
    assert source is not None
    assert source.produced_claims == ["claim-1"]
    assert source.produced_concepts == ["water"]


def test_write_claim_with_no_matching_source_is_not_dangling(tmp_path: Path) -> None:
    """A Claim's source_ref may name a Source page that hasn't been ingested yet — not this Writer's job to fix."""
    writer = MarkdownWriter(tmp_path)

    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="...",
            source_ref="doc-missing#p1",
            confidence=0.5,
            provenance_state="extracted",
        )
    )

    assert writer.read_source("doc-missing") is None


def test_index_lists_all_pages(tmp_path: Path) -> None:
    """D23: root index.md links to per-type subdirectory indices, which fully list that type's pages."""
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
    writer.write_source(
        Source(
            slug="doc-1",
            source_title="Doc 1",
            source_path="raw_sources/doc-1",
            ingested_at="2026-08-27",
            summary="A short document.",
        )
    )

    root_index = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "claims/index.md" in root_index
    assert "concepts/index.md" in root_index
    assert "sources/index.md" in root_index

    assert "[[water]]" in (tmp_path / "concepts" / "index.md").read_text(encoding="utf-8")
    assert "[[claim-1]]" in (tmp_path / "claims" / "index.md").read_text(encoding="utf-8")
    assert "[[doc-1]]" in (tmp_path / "sources" / "index.md").read_text(encoding="utf-8")


def test_index_entries_use_description_field_when_set(tmp_path: Path) -> None:
    """D23 §5.4: each index.md link is followed by that page's frontmatter description field."""
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(
        Concept(
            slug="water",
            concept_title="Water",
            summary="A long paragraph about the chemical compound water...",
            description="A common chemical compound.",
        )
    )
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="Water boils at 100C at sea level under standard atmospheric pressure.",
            description="Water's boiling point at sea level.",
            source_ref="doc-1#p1",
            confidence=0.5,
            provenance_state="extracted",
        )
    )

    assert "[[water]] — A common chemical compound." in (tmp_path / "concepts" / "index.md").read_text(encoding="utf-8")
    assert "[[claim-1]] — Water's boiling point at sea level." in (tmp_path / "claims" / "index.md").read_text(
        encoding="utf-8"
    )


def test_index_entries_fall_back_when_description_missing(tmp_path: Path) -> None:
    """A page written without a description (e.g. an older bundle) still gets a usable index entry."""
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A chemical compound."))
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="Water boils at 100C.",
            source_ref="doc-1#p1",
            confidence=0.5,
            provenance_state="extracted",
        )
    )

    # falls back to summary alone — no "concept_title: ..." composite (description is plain discourse).
    assert "[[water]] — A chemical compound." in (tmp_path / "concepts" / "index.md").read_text(encoding="utf-8")
    assert "[[claim-1]] — Water boils at 100C." in (tmp_path / "claims" / "index.md").read_text(encoding="utf-8")


def test_source_description_is_deterministic_not_llm_input(tmp_path: Path) -> None:
    """Source.description (D23 §5.4) is always Writer-generated from summary — any value passed in is
    overwritten, unlike Claim/Concept.description which is LLM output. Plain discourse, never a
    "source_title: ..." composite — the title is already the index entry's own [[slug]] link text."""
    writer = MarkdownWriter(tmp_path)
    writer.write_source(
        Source(
            slug="doc-1",
            source_title="Doc 1",
            source_path="raw_sources/doc-1",
            ingested_at="2026-08-27",
            summary="",
            description="this LLM-supplied value must be ignored",
        )
    )

    source = writer.read_source("doc-1")
    assert source is not None
    assert source.description == ""  # no summary yet — nothing to describe

    writer.write_source(source.model_copy(update={"summary": "A short document."}))
    assert writer.read_source("doc-1").description == "A short document."  # type: ignore[union-attr]


def test_index_entry_omits_dash_when_description_empty(tmp_path: Path) -> None:
    """A fresh Source (placeholder page, summary not generated yet — see pipeline-overview.md) has no
    description at all. Its index.md entry must not carry a dangling "— " with nothing after it."""
    writer = MarkdownWriter(tmp_path)
    writer.write_source(
        Source(
            slug="doc-1", source_title="Doc 1", source_path="raw_sources/doc-1", ingested_at="2026-08-27", summary=""
        )
    )

    index_lines = (tmp_path / "sources" / "index.md").read_text(encoding="utf-8").splitlines()
    assert "- [[doc-1]]" in index_lines
    assert not any(line.startswith("- [[doc-1]] —") for line in index_lines)


def test_source_description_flattens_multi_section_summary(tmp_path: Path) -> None:
    """summary is not capped to one paragraph — it may use '## ' subsections (see entities.py). description
    must still collapse to a single flattened line; otherwise a multi-line description would break the
    one-bullet-per-page index.md format (this was a real bug caught by a manual CLI smoke run)."""
    writer = MarkdownWriter(tmp_path)
    structured_summary = "## Overview\nThis document describes the Eiffel Tower.\n\n## Details\nCompleted in 1889."
    writer.write_source(
        Source(
            slug="doc-1",
            source_title="Doc 1",
            source_path="raw_sources/doc-1",
            ingested_at="2026-08-27",
            summary=structured_summary,
        )
    )

    source = writer.read_source("doc-1")
    assert source is not None
    assert "\n" not in source.description
    assert source.description == "Overview This document describes the Eiffel Tower. Details Completed in 1889."

    index_lines = (tmp_path / "sources" / "index.md").read_text(encoding="utf-8").splitlines()
    assert "- [[doc-1]] — Overview This document describes the Eiffel Tower. Details Completed in 1889." in index_lines


def test_index_entry_flattens_a_multiline_description_regardless_of_source(tmp_path: Path) -> None:
    """Defense in depth: even an LLM-supplied Claim/Concept.description that ignores the "one sentence"
    instruction and returns embedded newlines must not break index.md's one-bullet-per-page format."""
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(
        Concept(
            slug="water",
            concept_title="Water",
            summary="A chemical compound.",
            description="Line one.\nLine two, which should not have been here.",
        )
    )

    index_lines = (tmp_path / "concepts" / "index.md").read_text(encoding="utf-8").splitlines()
    assert "- [[water]] — Line one. Line two, which should not have been here." in index_lines


def test_claim_body_renders_related_pages_and_sources_from_frontmatter(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    claim = Claim(
        slug="claim-1",
        claim_text="Water boils at 100C at sea level.",
        source_ref="doc-1#p3",
        confidence=0.9,
        provenance_state="extracted",
        related_concepts=["water"],
    )

    writer.write_claim(claim)

    body = (tmp_path / "claims" / "claim-1.md").read_text(encoding="utf-8")
    assert "## Related Pages" in body
    assert "- [[water]]" in body
    assert "## Related Sources" in body
    assert "- doc-1#p3" in body
    # Not independently LLM-generated: the body's link section is a deterministic rendering of the
    # frontmatter (D17 direction A) — every related_concepts/source_ref entry that round-trips through
    # frontmatter must appear in body verbatim, so the two can never drift apart.
    read_back = writer.read_claim("claim-1")
    assert read_back is not None
    assert read_back.related_concepts == ["water"]


def test_concept_body_renders_key_facts_and_related_pages_from_frontmatter(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(Concept(slug="ice", concept_title="Ice", summary="Frozen water."))
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="Water boils at 100C.",
            source_ref="doc-1#p1",
            confidence=0.9,
            provenance_state="extracted",
            related_concepts=["ice"],
        )
    )

    body = (tmp_path / "concepts" / "ice.md").read_text(encoding="utf-8")
    assert "## Key Facts" in body
    assert "- [[claim-1]]" in body  # key_facts backlink (§2.3.2), rendered the same deterministic way


def test_body_omits_sections_with_no_content(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A compound."))

    body = (tmp_path / "concepts" / "water.md").read_text(encoding="utf-8")
    assert "## Key Facts" not in body
    assert "## Related Pages" not in body
    assert "## Related Sources" not in body


def test_content_fields_live_only_in_body_not_frontmatter(tmp_path: Path) -> None:
    """claim_text/summary are content, not metadata — never duplicated into the YAML frontmatter block
    (extends D23 beyond its literal text, see TODO.md)."""
    writer = MarkdownWriter(tmp_path)
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A chemical compound."))
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="Water boils at 100C at sea level.",
            source_ref="doc-1#p1",
            confidence=0.5,
            provenance_state="extracted",
        )
    )
    writer.write_source(
        Source(
            slug="doc-1",
            source_title="Doc 1",
            source_path="raw_sources/doc-1",
            ingested_at="2026-08-27",
            summary="A short document.",
        )
    )

    claim_text = (tmp_path / "claims" / "claim-1.md").read_text(encoding="utf-8")
    frontmatter_block, _, body = claim_text.partition("\n---\n")
    assert "claim_text:" not in frontmatter_block
    assert "Water boils at 100C at sea level." in body

    concept_text = (tmp_path / "concepts" / "water.md").read_text(encoding="utf-8")
    frontmatter_block, _, body = concept_text.partition("\n---\n")
    assert "summary:" not in frontmatter_block
    assert "A chemical compound." in body

    source_text = (tmp_path / "sources" / "doc-1.md").read_text(encoding="utf-8")
    frontmatter_block, _, body = source_text.partition("\n---\n")
    assert "summary:" not in frontmatter_block
    assert "A short document." in body
    # description is metadata (a short blurb), unlike summary — it does stay in frontmatter.
    assert "description:" in frontmatter_block


def test_content_recovers_correctly_around_multiline_paragraphs_and_no_sections(tmp_path: Path) -> None:
    """_extract_content must round-trip content that spans multiple lines/paragraphs, and content with no
    '## ...' section following it at all (nothing to bound the scan on the end side)."""
    writer = MarkdownWriter(tmp_path)
    multiline_summary = "First sentence about water.\n\nSecond paragraph, still about water."
    writer.write_concept(Concept(slug="water", concept_title="Water", summary=multiline_summary))

    read_back = writer.read_concept("water")
    assert read_back is not None
    assert read_back.summary == multiline_summary


def test_content_with_own_markdown_subsections_round_trips(tmp_path: Path) -> None:
    """summary is not capped to one paragraph — it may itself use '## ' subsections (e.g. History/Usage).
    _extract_content must not confuse those with the Writer's own '## Key Facts'/etc. sections; the sentinel
    boundary is what makes this possible (a plain first-'## '-wins scan would truncate here)."""
    writer = MarkdownWriter(tmp_path)
    structured_summary = "## History\nBuilt in 1889.\n\n## Usage\nA tourist attraction and radio mast."
    writer.write_concept(Concept(slug="water", concept_title="Water", summary=structured_summary))
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="Water boils at 100C.",
            source_ref="doc-1#p1",
            confidence=0.5,
            provenance_state="extracted",
            related_concepts=["water"],
        )
    )

    read_back = writer.read_concept("water")
    assert read_back is not None
    assert read_back.summary == structured_summary
    assert read_back.key_facts == ["claim-1"]  # the Writer's own section is still intact and correctly parsed


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
