"""Operational logging setup: log format + ``get_logger()`` (D19-adjacent, but distinct from D14/§4.4).

This is diagnostic/console logging for watching a `llm-yuki compile` run happen in real time — timestamped
lines on stderr via Python's standard ``logging`` module. It is **not** the same thing as ``log.md``
(``Writer.append_log``, written by ``ErrorBook.update_error_book``/``verify_and_close`` per proposal
ARCHITECTURE.md §4.4): that is a durable, OKF-adjacent domain audit trail of lint events, read back for D7's
precision/recall validation. This module produces nothing durable and nothing any pipeline logic reads back —
purely operator-facing visibility. The two are complementary, never a substitute for one another.

Using the standard ``logging`` module from ``domain/`` does not violate the "no filesystem/network I/O"
module-boundary rule (``.ai/rules/python.md``): that rule targets I/O that needs to go through ``ports/`` to
keep the domain swappable/testable (the actual business dependencies — ``Connector``/``Writer``); stderr
logging is neither filesystem nor network I/O, requires no port, and is inert (no output at all) unless
something has called :func:`configure_logging`, so it never affects test behavior or determinism.

Usage — one call per module, at import time, module-level::

    from llm_yuki.logging import get_logger

    logger = get_logger(__name__)

    def some_function() -> None:
        logger.info("did the thing: %s", detail)

``configure_logging()`` should be called exactly once, as early as possible in a real entrypoint (``cli.py``)
— library/domain code only ever calls :func:`get_logger`, never configures handlers itself, per the standard
"libraries don't configure logging" convention. Without a `configure_logging()` call, everything below the
`logging` module's own last-resort WARNING-level fallback stays invisible — that's the intended behavior in
tests, so log noise never depends on test run order.
"""

from __future__ import annotations

import logging
import os
import sys

_LOGGER_NAME = "llm_yuki"
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
_LEVEL_ENV = "LLM_YUKI_LOG_LEVEL"

_configured = False


def configure_logging(level: int | str | None = None) -> None:
    """Attach a single stderr handler to the ``llm_yuki`` logger namespace and set its level.

    Safe to call more than once — the handler is only ever attached the first time; a later call just
    updates the level, so re-running it (e.g. to honor a ``--verbose`` flag parsed after import time) works
    as expected without duplicating log lines.

    ``level`` resolution order: the explicit argument, else the ``LLM_YUKI_LOG_LEVEL`` environment variable
    (a level name like ``"DEBUG"``, matching how the rest of the CLI reads config from the environment — see
    ``cli.py``), else ``INFO``.
    """
    global _configured
    resolved = level if level is not None else os.environ.get(_LEVEL_ENV, "INFO")

    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(resolved)
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(handler)
        root.propagate = False
        _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger for ``name`` (conventionally ``__name__``, e.g. ``"llm_yuki.domain.pipeline"``).

    No prefixing needed: every module inside the package already has a dotted ``__name__`` starting with
    ``llm_yuki``, so passing it straight to ``logging.getLogger`` naturally nests under the ``llm_yuki``
    logger namespace that :func:`configure_logging` attaches its handler to (Python's ``logging`` module
    resolves the parent-child hierarchy by name, e.g. ``llm_yuki.domain.pipeline`` propagates up to
    ``llm_yuki``).

    Does not itself call :func:`configure_logging` — a module that only calls this at import time (the
    intended usage) stays silent until some entrypoint configures logging, matching the standard "libraries
    don't configure logging for themselves" convention. Safe to call at module scope in any layer, including
    ``domain/`` (see module docstring).
    """
    return logging.getLogger(name)
