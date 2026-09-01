"""Unit tests for the pure/no-I/O parts of llm_yuki.adapters.stats: grouping and rendering logic.

Bundle-scanning (snapshot_bundle/compute_run_stats) needs a real filesystem (Writer read-back + globbing
bundle_dir) — those live in tests/integration/test_stats_bundle.py per .ai/rules/testing.md.
"""

from __future__ import annotations

from llm_yuki.adapters.cost_ledger import CostEvent
from llm_yuki.adapters.stats import (
    ComponentStats,
    ErrorTypeRunStats,
    LinkFieldStats,
    PageStats,
    RunStats,
    _component_stats,
    _error_stats,
    render_stats_report,
    report_filename,
)
from llm_yuki.domain.error_book import ErrorBook, ErrorBookEntry


def _event(
    stage: str, tokens_in: int = 0, tokens_out: int = 0, wall_clock_ms: float = 10.0, batch_id: int = 1
) -> CostEvent:
    return CostEvent(
        stage=stage, batch_id=batch_id, tokens_in=tokens_in, tokens_out=tokens_out, wall_clock_ms=wall_clock_ms
    )


def _sample_run_stats(**overrides: object) -> RunStats:
    defaults: dict[str, object] = {
        "batch_id": 1,
        "generated_at": "2026-09-01T00:00:00+00:00",
        "e2e_wall_clock_ms": 1000.0,
        "claims": PageStats(total=5, new_this_run=3),
        "concepts": PageStats(total=2, new_this_run=1),
        "sources": PageStats(total=1, new_this_run=1),
        "link_fields": [
            LinkFieldStats(field="Claim.related_concepts", total=3, added_this_run=3),
            LinkFieldStats(field="Claim.source_ref", total=5, added_this_run=3),
        ],
        "components": [
            ComponentStats(
                component="Extractor",
                phase_label="Phase 1 (parallel — SelectPages/CompileWikiPages, D12)",
                call_count=3,
                tokens_in=900,
                tokens_out=300,
                wall_clock_ms=500.0,
                pct_of_e2e=50.0,
            )
        ],
        "llm_call_count": 3,
        "tokens_in_total": 900,
        "tokens_out_total": 300,
        "errors": [],
    }
    defaults.update(overrides)
    return RunStats(**defaults)  # type: ignore[arg-type]


class TestComponentStats:
    def test_groups_by_stage_prefix_before_dot(self) -> None:
        events = [
            _event("Extractor.SelectPages", tokens_in=10, tokens_out=5, wall_clock_ms=1.0),
            _event("Extractor.CompileWikiPages", tokens_in=100, tokens_out=50, wall_clock_ms=2.0),
            _event("Merger.summary_merge", tokens_in=20, tokens_out=10, wall_clock_ms=3.0),
        ]

        stats = _component_stats(events, e2e_wall_clock_ms=10.0)
        by_component = {s.component: s for s in stats}

        assert by_component["Extractor"].call_count == 2
        assert by_component["Extractor"].tokens_in == 110
        assert by_component["Extractor"].tokens_out == 55
        assert by_component["Extractor"].wall_clock_ms == 3.0
        assert by_component["Merger"].call_count == 1

    def test_pct_of_e2e_is_none_when_e2e_is_zero(self) -> None:
        events = [_event("Fixer.LLMPeriodicFix", wall_clock_ms=5.0)]
        stats = _component_stats(events, e2e_wall_clock_ms=0.0)
        assert stats[0].pct_of_e2e is None

    def test_unknown_component_gets_unknown_phase_label(self) -> None:
        events = [_event("SomeNewComponent.do_thing", wall_clock_ms=1.0)]
        stats = _component_stats(events, e2e_wall_clock_ms=10.0)
        assert stats[0].phase_label == "unknown"

    def test_sorted_by_wall_clock_descending(self) -> None:
        events = [
            _event("Fixer.LLMPeriodicFix", wall_clock_ms=1.0),
            _event("Extractor.CompileWikiPages", wall_clock_ms=100.0),
            _event("Merger.summary_merge", wall_clock_ms=10.0),
        ]
        stats = _component_stats(events, e2e_wall_clock_ms=200.0)
        assert [s.component for s in stats] == ["Extractor", "Merger", "Fixer"]


class TestErrorStats:
    def test_discovered_and_closed_scoped_to_batch(self) -> None:
        book = ErrorBook(
            entries=[
                ErrorBookEntry(
                    id="e1",
                    error_type="unsupported_facts",
                    phenomenon="x",
                    status="closed",
                    discovered_at_batch=1,
                    closed_at_batch=2,
                ),
                ErrorBookEntry(
                    id="e2",
                    error_type="unsupported_facts",
                    phenomenon="y",
                    status="open",
                    discovered_at_batch=2,
                    closed_at_batch=None,
                ),
                ErrorBookEntry(
                    id="e3",
                    error_type="dangling_links",
                    phenomenon="z",
                    status="open",
                    discovered_at_batch=1,
                    closed_at_batch=None,
                ),
            ]
        )

        stats_batch1 = {s.error_type: s for s in _error_stats(book, batch_id=1)}
        stats_batch2 = {s.error_type: s for s in _error_stats(book, batch_id=2)}

        assert stats_batch1["unsupported_facts"].discovered_this_run == 1
        assert stats_batch1["unsupported_facts"].closed_this_run == 0
        assert stats_batch1["unsupported_facts"].open_total == 1  # e2 still open, counted regardless of batch

        assert stats_batch2["unsupported_facts"].discovered_this_run == 1  # e2
        assert stats_batch2["unsupported_facts"].closed_this_run == 1  # e1 closed at batch 2

        assert stats_batch1["dangling_links"].discovered_this_run == 1
        assert stats_batch1["dangling_links"].open_total == 1

    def test_empty_error_book_yields_no_stats(self) -> None:
        assert _error_stats(ErrorBook(), batch_id=1) == []


class TestRenderStatsReport:
    def test_contains_every_section_heading(self) -> None:
        md = render_stats_report(_sample_run_stats())

        assert "# Compilation Statistics — batch 1" in md
        assert "## 1. Summary" in md
        assert "## 2. Knowledge Graph Growth" in md
        assert "## 3. Links" in md
        assert "## 4. LLM Usage" in md
        assert "## 5. Timing by Component" in md

    def test_omits_error_section_when_no_errors(self) -> None:
        md = render_stats_report(_sample_run_stats(errors=[]))
        assert "Error Book Cross-Reference" not in md

    def test_includes_error_section_when_errors_present(self) -> None:
        stats = _sample_run_stats(
            errors=[
                ErrorTypeRunStats(
                    error_type="unsupported_facts", discovered_this_run=2, closed_this_run=1, open_total=1
                )
            ]
        )
        md = render_stats_report(stats)
        assert "## 6. Error Book Cross-Reference" in md
        assert "unsupported_facts" in md

    def test_numbers_from_stats_appear_in_output(self) -> None:
        md = render_stats_report(_sample_run_stats())
        assert "1,200" in md  # tokens_in_total + tokens_out_total
        assert "3" in md  # claims.new_this_run / llm_call_count

    def test_notes_extractor_parallelism_when_extractor_present(self) -> None:
        md = render_stats_report(_sample_run_stats())
        assert "can legitimately exceed 100%" in md

    def test_no_components_renders_placeholder(self) -> None:
        md = render_stats_report(_sample_run_stats(components=[]))
        assert "No cost-ledger events recorded for this batch." in md


class TestReportFilename:
    def test_format_is_stat_timestamp_batch(self) -> None:
        stats = _sample_run_stats(generated_at="2026-09-01T12:34:56+00:00", batch_id=7)
        assert report_filename(stats) == "stat_20260901T123456Z_batch7.md"
