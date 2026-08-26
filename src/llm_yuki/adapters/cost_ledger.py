"""Cost ledger: append-only ``pipeline-state/cost_ledger.jsonl`` recorder (D19).

Independent of the OKF ``bundle/`` output — pipeline meta-state, not domain content, so it does not need to
pass OKF conformance (proposal ARCHITECTURE.md §7.1). Every pipeline stage call records one event here,
including non-LLM steps (e.g. ``CodeAutoFix``, ``StructuralValidate``), which explicitly record 0 tokens
rather than being omitted (§7.2).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class CostEvent(BaseModel):
    """One row of ``cost_ledger.jsonl`` (proposal ARCHITECTURE.md §7.2)."""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    stage: str
    batch_id: int
    tokens_in: int
    tokens_out: int
    wall_clock_ms: float
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class JsonlCostLedger:
    """Appends one JSON line per :class:`CostEvent` to ``pipeline-state/cost_ledger.jsonl``."""

    def __init__(self, pipeline_state_root: Path | str) -> None:
        self._root = Path(pipeline_state_root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "cost_ledger.jsonl"

    def record(self, stage: str, batch_id: int, tokens_in: int, tokens_out: int, wall_clock_ms: float) -> CostEvent:
        """Append one cost event and return it."""
        event = CostEvent(
            stage=stage, batch_id=batch_id, tokens_in=tokens_in, tokens_out=tokens_out, wall_clock_ms=wall_clock_ms
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        return event

    def record_call(self, stage: str, batch_id: int) -> "_TimedCall":
        """Context manager: times a non-LLM call and records it with 0 tokens on exit.

        Usage::

            with cost_ledger.record_call("Validator.StructuralValidate", batch_id):
                issues = validator.structural_validate(update, writer)
        """
        return _TimedCall(self, stage, batch_id)

    def read_events(self) -> list[CostEvent]:
        """Read back all recorded events, in append order. For tests/rollups."""
        if not self._path.exists():
            return []
        with self._path.open(encoding="utf-8") as f:
            return [CostEvent.model_validate(json.loads(line)) for line in f if line.strip()]


class _TimedCall:
    """Internal helper for :meth:`JsonlCostLedger.record_call`."""

    def __init__(self, ledger: JsonlCostLedger, stage: str, batch_id: int) -> None:
        self._ledger = ledger
        self._stage = stage
        self._batch_id = batch_id
        self._start = 0.0

    def __enter__(self) -> "_TimedCall":
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc_info: object) -> None:
        elapsed_ms = (time.monotonic() - self._start) * 1000
        self._ledger.record(self._stage, self._batch_id, tokens_in=0, tokens_out=0, wall_clock_ms=elapsed_ms)
