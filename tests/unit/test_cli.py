"""Unit tests for the CLI argument parsing and startup-time LLM config check — no real network access."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.cli import build_parser, main
from llm_yuki.domain.entities import Concept

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)  # isolate from any real .env a developer might have in the repo root

    exit_code = main(["compile", "raw_sources", "bundle"])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "OPENAI_API_KEY" in stderr
    assert "OPENAI_BASE_URL" in stderr
    assert "LLM_MODEL" in stderr


def test_search_parses_positional_and_defaults() -> None:
    args = build_parser().parse_args(["search", "bundle", "water"])

    assert args.command == "search"
    assert args.bundle_dir == Path("bundle")
    assert args.query == "water"
    assert args.top_k == 8


def test_main_search_runs_without_any_llm_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`search` needs no OPENAI_*/LLM_MODEL config at all — retrieval never calls an LLM (D25)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)

    bundle_dir = tmp_path / "bundle"
    MarkdownWriter(bundle_dir).write_concept(
        Concept(slug="water", concept_title="Water", summary="Water is a chemical compound.")
    )

    exit_code = main(["search", str(bundle_dir), "water"])

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "water" in stdout
    assert "Water is a chemical compound." in stdout


def test_main_search_reports_no_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["search", str(tmp_path / "empty-bundle"), "nothing matches"])

    assert exit_code == 0
    assert "No results." in capsys.readouterr().out


def test_query_parses_positional_and_defaults() -> None:
    args = build_parser().parse_args(["query", "bundle", "What is water?"])

    assert args.command == "query"
    assert args.bundle_dir == Path("bundle")
    assert args.question == "What is water?"
    assert args.method == "single-pass"
    assert args.top_k == 8
    assert args.batch_id == 1
    assert args.t_max == 6
    assert args.patience == 2


def test_query_accepts_agentic_method_and_overrides() -> None:
    args = build_parser().parse_args(
        ["query", "bundle", "q", "--method", "agentic", "--top-k", "3", "--t-max", "10", "--patience", "5"]
    )

    assert args.method == "agentic"
    assert args.top_k == 3
    assert args.t_max == 10
    assert args.patience == 5


def test_query_rejects_unknown_method() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["query", "bundle", "q", "--method", "vector-rag"])


def test_main_query_fails_fast_without_llm_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["query", "bundle", "What is water?"])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "OPENAI_API_KEY" in stderr
    assert "OPENAI_BASE_URL" in stderr
    assert "LLM_MODEL" in stderr


def test_evaluate_qa_parses_positional_and_defaults() -> None:
    args = build_parser().parse_args(["evaluate-qa", "bundle", "qa.jsonl"])

    assert args.command == "evaluate-qa"
    assert args.bundle_dir == Path("bundle")
    assert args.qa_path == Path("qa.jsonl")
    assert args.method == "single-pass"
    assert args.top_k == 8
    assert args.output is None


def test_evaluate_qa_accepts_output_path() -> None:
    args = build_parser().parse_args(["evaluate-qa", "bundle", "qa.jsonl", "--output", "report.json"])

    assert args.output == Path("report.json")


def test_main_evaluate_qa_fails_fast_without_llm_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["evaluate-qa", "bundle", "qa.jsonl"])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "OPENAI_API_KEY" in stderr
