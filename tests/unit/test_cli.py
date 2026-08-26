"""Unit tests for the CLI argument parsing and compile-command scaffold — no filesystem access."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_yuki.cli import build_parser, main

pytestmark = pytest.mark.unit


def test_compile_parses_positional_and_default_batch_id() -> None:
    args = build_parser().parse_args(["compile", "raw_sources", "bundle"])

    assert args.command == "compile"
    assert args.source_dir == Path("raw_sources")
    assert args.bundle_dir == Path("bundle")
    assert args.batch_id == 1


def test_compile_accepts_explicit_batch_id() -> None:
    args = build_parser().parse_args(["compile", "raw_sources", "bundle", "--batch-id", "3"])

    assert args.batch_id == 3


def test_no_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_main_compile_fails_fast_pending_domain_stubs(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["compile", "raw_sources", "bundle"])

    assert exit_code == 1
    assert "not implemented yet" in capsys.readouterr().err
