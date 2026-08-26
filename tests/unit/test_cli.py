"""Unit tests for the CLI argument parsing and startup-time LLM config check — no real network access."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_yuki.cli import build_parser, main

pytestmark = pytest.mark.unit


def test_compile_parses_positional_and_defaults() -> None:
    args = build_parser().parse_args(["compile", "raw_sources", "bundle"])

    assert args.command == "compile"
    assert args.source_dir == Path("raw_sources")
    assert args.bundle_dir == Path("bundle")
    assert args.batch_id == 1
    assert args.pipeline_state_dir is None


def test_compile_accepts_explicit_batch_id() -> None:
    args = build_parser().parse_args(["compile", "raw_sources", "bundle", "--batch-id", "3"])

    assert args.batch_id == 3


def test_compile_accepts_explicit_pipeline_state_dir() -> None:
    args = build_parser().parse_args(["compile", "raw_sources", "bundle", "--pipeline-state-dir", "state"])

    assert args.pipeline_state_dir == Path("state")


def test_no_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_main_compile_fails_fast_without_llm_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    exit_code = main(["compile", "raw_sources", "bundle"])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "OPENAI_API_KEY" in stderr
    assert "OPENAI_BASE_URL" in stderr
    assert "LLM_MODEL" in stderr
