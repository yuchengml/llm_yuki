"""Unit tests for ``domain/query.py::load_corpus`` — the only I/O-touching function in the module."""

from __future__ import annotations

import pytest

from llm_yuki.domain.entities import Claim, Concept, ContradictionRef, Source
from llm_yuki.domain.query import load_corpus
from llm_yuki.ports.writer import Writer

pytestmark = pytest.mark.unit


class _FakeWriter(Writer):
    def __init__(self) -> None:
        self.claims: dict[str, Claim] = {}
        self.concepts: dict[str, Concept] = {}
        self.sources: dict[str, Source] = {}

    def write_claim(self, claim: Claim) -> None:
        self.claims[claim.slug] = claim

    def write_concept(self, concept: Concept) -> None:
        self.concepts[concept.slug] = concept

    def write_source(self, source: Source) -> None:
        self.sources[source.slug] = source

    def read_claim(self, slug: str) -> Claim | None:
        return self.claims.get(slug)

    def read_concept(self, slug: str) -> Concept | None:
        return self.concepts.get(slug)

    def read_source(self, slug: str) -> Source | None:
        return self.sources.get(slug)

    def list_pages(self) -> list[str]:
        return [*self.claims, *self.concepts, *self.sources]

    def append_log(self, event: str) -> None:
        pass


def test_load_corpus_empty_bundle_returns_empty_list() -> None:
    assert load_corpus(_FakeWriter()) == []


def test_load_corpus_flattens_concept_fields() -> None:
    writer = _FakeWriter()
    writer.write_concept(
        Concept(
            slug="water",
            concept_title="Water",
            aliases=["H2O"],
            tags=["chemistry"],
            description="A compound.",
            summary="Water is a chemical compound of hydrogen and oxygen.",
            key_facts=["water-boils"],
            related_pages=["hydrogen"],
            related_sources=["doc-1"],
        )
    )

    [record] = load_corpus(writer)

    assert record.slug == "water"
    assert record.page_type == "concept"
    assert record.title == "Water"
    assert record.aliases == ["H2O"]
    assert record.tags == ["chemistry"]
    assert record.description == "A compound."
    assert record.content == "Water is a chemical compound of hydrogen and oxygen."
    # links = related_pages + key_facts + related_sources
    assert set(record.links) == {"hydrogen", "water-boils", "doc-1"}


def test_load_corpus_flattens_claim_fields_and_excludes_contradicted_by() -> None:
    writer = _FakeWriter()
    writer.write_claim(
        Claim(
            slug="water-boils",
            claim_text="Water boils at 100C at sea level.",
            description="Boiling point of water.",
            source_ref="doc-1#p0",
            confidence=0.9,
            provenance_state="extracted",
            related_concepts=["water"],
            contradicted_by=[ContradictionRef(slug="water-boils-90c", reason="altitude")],
        )
    )

    [record] = load_corpus(writer)

    assert record.page_type == "claim"
    assert record.title == "water-boils"  # Claim has no separate title field — falls back to slug
    assert record.content == "Water boils at 100C at sea level."
    assert record.links == ["water"]  # contradicted_by is deliberately excluded, see PageRecord.links docstring


def test_load_corpus_flattens_source_fields() -> None:
    writer = _FakeWriter()
    writer.write_source(
        Source(
            slug="doc-1",
            source_title="Doc 1",
            source_path="raw_sources/doc-1",
            ingested_at="2026-08-30",
            summary="Covers water's boiling and freezing points.",
            produced_claims=["water-boils"],
            produced_concepts=["water"],
            related_pages=["doc-2"],
        )
    )

    [record] = load_corpus(writer)

    assert record.page_type == "source"
    assert record.title == "Doc 1"
    assert record.content == "Covers water's boiling and freezing points."
    assert set(record.links) == {"water-boils", "water", "doc-2"}


def test_load_corpus_returns_one_record_per_slug_across_types() -> None:
    writer = _FakeWriter()
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="x"))
    writer.write_claim(
        Claim(
            slug="water-boils",
            claim_text="x",
            source_ref="doc-1",
            confidence=0.5,
            provenance_state="extracted",
        )
    )
    writer.write_source(
        Source(slug="doc-1", source_title="Doc 1", source_path="p", ingested_at="2026-08-30", summary="x")
    )

    records = load_corpus(writer)

    assert {r.slug for r in records} == {"water", "water-boils", "doc-1"}
    assert {r.page_type for r in records} == {"concept", "claim", "source"}
