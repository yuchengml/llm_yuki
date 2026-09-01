"""Integration tests for the CLI's full pipeline wiring — real filesystem, no real LLM calls.

Only exercises the no-sources path: with an empty Raw Sources folder, Orchestrator never reaches the
LLM-backed stages (no passages to extract from, and periodic fix isn't due at batch 1), so this proves the
CLI wires every adapter together correctly without needing a live/fake LLM endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_yuki.cli import main

pytestmark = pytest.mark.integration


def test_compile_with_no_sources_wires_pipeline_and_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    source_dir = tmp_path / "raw_sources"
    source_dir.mkdir()
    bundle_dir = tmp_path / "bundle"

    exit_code = main(["compile", str(source_dir), str(bundle_dir)])

    assert exit_code == 0
    assert (bundle_dir / "log.md").exists()  # MarkdownWriter initializes this on construction
    assert (tmp_path / "pipeline-state" / "error_book.yaml").exists()
    stats_files = list((tmp_path / "pipeline-state").glob("stat_*.md"))
    assert len(stats_files) == 1  # D27: one compilation-statistics report per compile invocation


def test_compile_respects_explicit_pipeline_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    source_dir = tmp_path / "raw_sources"
    source_dir.mkdir()
    bundle_dir = tmp_path / "bundle"
    state_dir = tmp_path / "custom-state"

    exit_code = main(["compile", str(source_dir), str(bundle_dir), "--pipeline-state-dir", str(state_dir)])

    assert exit_code == 0
    assert (state_dir / "error_book.yaml").exists()


def test_compile_picks_up_config_from_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The actual bug this test guards against: a `.env` file alone did nothing before — `main()` never
    read it, so LLM config only worked if you separately `export`ed it into the shell yourself."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=test-key\nOPENAI_BASE_URL=https://openrouter.ai/api/v1\nLLM_MODEL=test-model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    source_dir = tmp_path / "raw_sources"
    source_dir.mkdir()
    bundle_dir = tmp_path / "bundle"

    exit_code = main(["compile", str(source_dir), str(bundle_dir)])

    assert exit_code == 0
    assert (bundle_dir / "log.md").exists()


def test_real_env_var_takes_precedence_over_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "real-env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "real-env-model")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dotenv-key\nLLM_MODEL=dotenv-model\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    source_dir = tmp_path / "raw_sources"
    source_dir.mkdir()
    bundle_dir = tmp_path / "bundle"

    exit_code = main(["compile", str(source_dir), str(bundle_dir)])

    assert exit_code == 0
    assert os.environ["OPENAI_API_KEY"] == "real-env-key"
