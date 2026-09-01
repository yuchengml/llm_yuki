"""Integration tests for llm_yuki.adapters.stats — real filesystem (MarkdownWriter bundle + cost ledger)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.stats import compute_run_stats, snapshot_bundle, write_stats_report
from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.domain.entities import Claim, Concept, Source
from llm_yuki.domain.error_book import ErrorBook, ErrorBookEntry

pytestmark = pytest.mark.integration


def test_snapshot_bundle_counts_pages_and_link_fields(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    writer.write_source(
        Source(slug="doc-1", source_title="Doc 1", source_path="doc-1", ingested_at="2026-09-01", summary="")
    )
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A chemical compound."))
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="Water boils at 100C.",
            source_ref="doc-1#p1",
            confidence=0.9,
            provenance_state="extracted",
            related_concepts=["water"],
        )
    )

    snapshot = snapshot_bundle(tmp_path, writer)

    assert snapshot.claim_slugs == {"claim-1"}
    assert snapshot.concept_slugs == {"water"}
    assert snapshot.source_slugs == {"doc-1"}
    assert snapshot.link_field_totals["Claim.related_concepts"] == 1
    assert snapshot.link_field_totals["Claim.source_ref"] == 1
    assert snapshot.link_field_totals["Concept.key_facts"] == 1  # backlink maintained by write_claim
    assert snapshot.link_field_totals["Source.produced_claims"] == 1


def test_snapshot_bundle_empty_bundle_is_all_zero(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    snapshot = snapshot_bundle(tmp_path, writer)

    assert snapshot.claim_slugs == frozenset()
    assert all(count == 0 for count in snapshot.link_field_totals.values())


def test_compute_run_stats_diffs_before_and_after(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    cost_ledger = JsonlCostLedger(tmp_path / "pipeline-state")
    error_book = ErrorBook()

    # Pre-existing page from an earlier run — must show up in totals but not "new_this_run".
    writer.write_concept(Concept(slug="pre-existing", concept_title="Pre-existing", summary="Already here."))
    before = snapshot_bundle(tmp_path, writer)

    # This run's work.
    writer.write_concept(Concept(slug="water", concept_title="Water", summary="A chemical compound."))
    writer.write_claim(
        Claim(
            slug="claim-1",
            claim_text="Water boils at 100C.",
            source_ref="doc-1#p1",
            confidence=0.9,
            provenance_state="extracted",
            related_concepts=["water"],
        )
    )
    cost_ledger.record("Extractor.CompileWikiPages", batch_id=1, tokens_in=100, tokens_out=40, wall_clock_ms=250.0)
    cost_ledger.record("Validator.StructuralValidate", batch_id=1, tokens_in=0, tokens_out=0, wall_clock_ms=5.0)

    stats = compute_run_stats(
        batch_id=1,
        bundle_dir=tmp_path,
        writer=writer,
        cost_ledger=cost_ledger,
        error_book=error_book,
        e2e_wall_clock_ms=1000.0,
        before=before,
    )

    assert stats.concepts.total == 2
    assert stats.concepts.new_this_run == 1
    assert stats.claims.total == 1
    assert stats.claims.new_this_run == 1
    assert stats.llm_call_count == 1  # only the tokenful Extractor call, not the 0-token StructuralValidate
    assert stats.tokens_in_total == 100
    assert stats.tokens_out_total == 40

    related_concepts = next(f for f in stats.link_fields if f.field == "Claim.related_concepts")
    assert related_concepts.total == 1
    assert related_concepts.added_this_run == 1


def test_compute_run_stats_only_includes_events_for_this_batch(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    cost_ledger = JsonlCostLedger(tmp_path / "pipeline-state")
    before = snapshot_bundle(tmp_path, writer)

    cost_ledger.record("Extractor.CompileWikiPages", batch_id=1, tokens_in=10, tokens_out=5, wall_clock_ms=1.0)
    cost_ledger.record("Extractor.CompileWikiPages", batch_id=2, tokens_in=999, tokens_out=999, wall_clock_ms=1.0)

    stats = compute_run_stats(
        batch_id=1,
        bundle_dir=tmp_path,
        writer=writer,
        cost_ledger=cost_ledger,
        error_book=ErrorBook(),
        e2e_wall_clock_ms=10.0,
        before=before,
    )

    assert stats.tokens_in_total == 10
    assert stats.llm_call_count == 1


def test_compute_run_stats_cross_references_error_book(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    before = snapshot_bundle(tmp_path, writer)
    error_book = ErrorBook(
        entries=[
            ErrorBookEntry(
                id="e1",
                error_type="unsupported_facts",
                phenomenon="claim not grounded",
                status="open",
                discovered_at_batch=1,
            )
        ]
    )

    stats = compute_run_stats(
        batch_id=1,
        bundle_dir=tmp_path,
        writer=writer,
        cost_ledger=JsonlCostLedger(tmp_path / "pipeline-state"),
        error_book=error_book,
        e2e_wall_clock_ms=10.0,
        before=before,
    )

    assert len(stats.errors) == 1
    assert stats.errors[0].error_type == "unsupported_facts"
    assert stats.errors[0].discovered_this_run == 1
    assert stats.errors[0].open_total == 1


def test_write_stats_report_creates_file_under_pipeline_state(tmp_path: Path) -> None:
    writer = MarkdownWriter(tmp_path)
    before = snapshot_bundle(tmp_path, writer)
    stats = compute_run_stats(
        batch_id=1,
        bundle_dir=tmp_path,
        writer=writer,
        cost_ledger=JsonlCostLedger(tmp_path / "pipeline-state"),
        error_book=ErrorBook(),
        e2e_wall_clock_ms=10.0,
        before=before,
    )

    pipeline_state_dir = tmp_path / "pipeline-state"
    path = write_stats_report(stats, pipeline_state_dir)

    assert path.exists()
    assert path.parent == pipeline_state_dir
    assert path.name.startswith("stat_")
    assert "Compilation Statistics" in path.read_text(encoding="utf-8")
