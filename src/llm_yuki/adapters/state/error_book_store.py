"""Persists an ``ErrorBook`` to ``pipeline-state/error_book.yaml`` (proposal ARCHITECTURE.md §4.4).

Kept out of ``domain/`` because it does filesystem I/O — ``ErrorBook`` itself stays a pure in-memory model
(AGENTS.md §4); this adapter is the only place that reads/writes it to disk.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from llm_yuki.domain.error_book import ErrorBook
from llm_yuki.logging import get_logger

logger = get_logger(__name__)


class YamlErrorBookStore:
    """Loads/saves an ``ErrorBook`` as YAML under ``<pipeline_state_root>/error_book.yaml``."""

    def __init__(self, pipeline_state_root: Path | str) -> None:
        self._path = Path(pipeline_state_root) / "error_book.yaml"

    def load(self) -> ErrorBook:
        """Load the persisted Error Book, or a fresh empty one if none exists yet."""
        if not self._path.exists():
            logger.debug("no error_book.yaml at %s — starting fresh", self._path)
            return ErrorBook()
        data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        book = ErrorBook.model_validate(data)
        logger.info("loaded error book: %d entries from %s", len(book.entries), self._path)
        return book

    def save(self, error_book: ErrorBook) -> None:
        """Persist the current Error Book state, overwriting the previous snapshot."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(error_book.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
        self._path.write_text(payload, encoding="utf-8")
        logger.debug("saved error book: %d entries to %s", len(error_book.entries), self._path)
