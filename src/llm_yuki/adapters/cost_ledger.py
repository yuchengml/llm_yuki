"""Cost ledger: append-only ``pipeline-state/cost_ledger.jsonl`` recorder (D19).

Independent of the OKF ``bundle/`` output — pipeline meta-state, not domain content, so it does not need to
pass OKF conformance (proposal ARCHITECTURE.md §7.1). Every pipeline stage call records one event here,
including non-LLM steps (e.g. ``CodeAutoFix``, ``StructuralValidate``), which explicitly record 0 tokens
rather than being omitted (§7.2). ``record`` is safe to call concurrently from multiple threads (D12 Phase 1
runs several ``Extractor`` calls — and therefore several ``record`` calls — in parallel).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from llm_yuki.logging import get_logger

logger = get_logger(__name__)


class CostEvent(BaseModel):
    """One row of ``cost_ledger.jsonl`` (proposal ARCHITECTURE.md §7.2)."""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    stage: str
    batch_id: int
    tokens_in: int
    tokens_out: int
    wall_clock_ms: float
    round: int | None = Field(
        default=None, description="Batch-round number, for stages that recurse (e.g. Merger.summarize_document, D21)."
    )
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class JsonlCostLedger:
    """Appends one JSON line per :class:`CostEvent` to ``pipeline-state/cost_ledger.jsonl``."""

    def __init__(self, pipeline_state_root: Path | str) -> None:
        self._root = Path(pipeline_state_root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "cost_ledger.jsonl"
        self._lock = threading.Lock()

    def record(
        self,
        stage: str,
        batch_id: int,
        tokens_in: int,
        tokens_out: int,
        wall_clock_ms: float,
        round: int | None = None,
    ) -> CostEvent:
        """Append one cost event and return it. Thread-safe (see module docstring)."""
        event = CostEvent(
            stage=stage,
            batch_id=batch_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            wall_clock_ms=wall_clock_ms,
            round=round,
        )
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        # Single choke point for every stage call (LLM-backed or not) across Extractor/Merger/Validator/
        # Fixer — cheaper than adding a log line to each of those classes individually.
        logger.debug(
            "batch %d: %s — tokens_in=%d tokens_out=%d wall_clock_ms=%.1f%s",
            batch_id,
            stage,
            tokens_in,
            tokens_out,
            wall_clock_ms,
            f" round={round}" if round is not None else "",
        )
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
