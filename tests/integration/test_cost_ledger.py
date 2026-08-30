"""Integration tests for JsonlCostLedger — exercises the real filesystem."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_yuki.adapters.cost_ledger import JsonlCostLedger

pytestmark = pytest.mark.integration


def test_record_appends_one_json_line(tmp_path: Path) -> None:
    ledger = JsonlCostLedger(tmp_path)

    ledger.record("Extractor.compile", batch_id=1, tokens_in=100, tokens_out=50, wall_clock_ms=250.0)

    events = ledger.read_events()
    assert len(events) == 1
    assert events[0].stage == "Extractor.compile"
    assert events[0].batch_id == 1
    assert events[0].tokens_in == 100
    assert events[0].tokens_out == 50
    assert events[0].wall_clock_ms == 250.0


def test_non_llm_steps_record_zero_tokens_not_omitted(tmp_path: Path) -> None:
    ledger = JsonlCostLedger(tmp_path)

    ledger.record("Fixer.CodeAutoFix", batch_id=1, tokens_in=0, tokens_out=0, wall_clock_ms=1.0)

    events = ledger.read_events()
    assert events[0].tokens_in == 0
    assert events[0].tokens_out == 0


def test_multiple_records_append_in_order(tmp_path: Path) -> None:
    ledger = JsonlCostLedger(tmp_path)

    ledger.record("stage-a", batch_id=1, tokens_in=1, tokens_out=1, wall_clock_ms=1.0)
    ledger.record("stage-b", batch_id=1, tokens_in=2, tokens_out=2, wall_clock_ms=2.0)

    events = ledger.read_events()
    assert [e.stage for e in events] == ["stage-a", "stage-b"]


def test_record_call_times_the_block_and_records_zero_tokens(tmp_path: Path) -> None:
    ledger = JsonlCostLedger(tmp_path)

    with ledger.record_call("Validator.StructuralValidate", batch_id=2):
        pass

    events = ledger.read_events()
    assert len(events) == 1
    assert events[0].stage == "Validator.StructuralValidate"
    assert events[0].batch_id == 2
    assert events[0].tokens_in == 0
    assert events[0].tokens_out == 0
    assert events[0].wall_clock_ms >= 0.0


def test_read_events_empty_when_no_file_yet(tmp_path: Path) -> None:
    ledger = JsonlCostLedger(tmp_path / "pipeline-state")

    assert ledger.read_events() == []


def test_events_are_json_lines_on_disk(tmp_path: Path) -> None:
    ledger = JsonlCostLedger(tmp_path)
    ledger.record("stage-a", batch_id=1, tokens_in=1, tokens_out=1, wall_clock_ms=1.0)

    raw = (tmp_path / "cost_ledger.jsonl").read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    assert len(lines) == 1
