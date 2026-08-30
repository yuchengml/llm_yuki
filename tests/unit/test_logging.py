"""Unit tests for llm_yuki.logging — log format definition + get_logger()/configure_logging()."""

from __future__ import annotations

import logging

import pytest

import llm_yuki.logging as llm_yuki_logging
from llm_yuki.logging import configure_logging, get_logger

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_logging_state() -> None:
    """Configuring the ``llm_yuki`` logger is a module-global, process-wide side effect (by design — see
    logging.py's docstring on the standard "libraries don't configure logging" convention). Reset it before
    and after every test here so these tests are independent of each other and of any other test/module
    (e.g. tests/unit/test_cli.py, which exercises ``main()`` and therefore calls ``configure_logging`` too).
    """
    root = logging.getLogger("llm_yuki")
    original_handlers = list(root.handlers)
    original_level = root.level
    original_propagate = root.propagate
    original_configured = llm_yuki_logging._configured

    root.handlers.clear()
    llm_yuki_logging._configured = False
    yield

    root.handlers.clear()
    root.handlers.extend(original_handlers)
    root.setLevel(original_level)
    root.propagate = original_propagate
    llm_yuki_logging._configured = original_configured


def test_get_logger_returns_logger_with_given_name() -> None:
    logger = get_logger("llm_yuki.domain.pipeline")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "llm_yuki.domain.pipeline"


def test_get_logger_does_not_configure_handlers() -> None:
    """Calling get_logger alone (the intended library-code usage) must not attach a handler — only an
    entrypoint's explicit configure_logging() call should."""
    get_logger("llm_yuki.domain.pipeline")
    assert logging.getLogger("llm_yuki").handlers == []


def test_configure_logging_attaches_exactly_one_handler() -> None:
    configure_logging()
    root = logging.getLogger("llm_yuki")
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)


def test_configure_logging_is_idempotent_about_handler_count() -> None:
    """Calling configure_logging more than once (e.g. re-running main() in-process, as tests do) must not
    duplicate log lines by attaching a second handler."""
    configure_logging()
    configure_logging()
    configure_logging(level="DEBUG")
    assert len(logging.getLogger("llm_yuki").handlers) == 1


def test_configure_logging_explicit_level_wins_over_default() -> None:
    configure_logging(level=logging.DEBUG)
    assert logging.getLogger("llm_yuki").level == logging.DEBUG


def test_configure_logging_reads_env_var_when_no_explicit_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_YUKI_LOG_LEVEL", "WARNING")
    configure_logging()
    assert logging.getLogger("llm_yuki").level == logging.WARNING


def test_configure_logging_defaults_to_info_with_no_level_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_YUKI_LOG_LEVEL", raising=False)
    configure_logging()
    assert logging.getLogger("llm_yuki").level == logging.INFO


def test_child_logger_propagates_up_to_configured_root() -> None:
    """A module calling get_logger(__name__) under the llm_yuki namespace must have its records reach the
    handler configure_logging attached to the llm_yuki root — this is what makes the whole scheme work."""
    configure_logging(level=logging.DEBUG)
    child = get_logger("llm_yuki.domain.pipeline")

    records: list[logging.LogRecord] = []
    logging.getLogger("llm_yuki").handlers[0].emit = lambda record: records.append(record)  # type: ignore[method-assign]

    child.info("hello from a child logger")

    assert len(records) == 1
    assert records[0].getMessage() == "hello from a child logger"
