"""Command-line entrypoint for running the compile pipeline.

Pipeline execution is exposed as a CLI first — no web/API service is planned for this POC (see root
`ARCHITECTURE.md` §5). Wires the `Connector`/`Writer` adapters together with the LLM-backed
`Extractor`/`Validator`/`Fixer` and the deterministic `Merger`/`ErrorBook` into a real `Orchestrator` and
runs one batch. LLM configuration (`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`LLM_MODEL`) is validated *before*
anything else runs, so a missing/misconfigured endpoint fails immediately with a clear message rather than
partway through a batch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llm_yuki.adapters.connectors.txt_file_connector import TxtFileConnector
from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.fixing.default_fixer import DefaultFixer
from llm_yuki.adapters.llm.client import LLMConfigError, OpenAICompatibleClient
from llm_yuki.adapters.llm.extractor import LLMExtractor
from llm_yuki.adapters.merging.default_merger import DefaultMerger
from llm_yuki.adapters.state.error_book_store import YamlErrorBookStore
from llm_yuki.adapters.validation.default_validator import DefaultValidator
from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.domain.pipeline import Orchestrator


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI argument parser."""
    parser = argparse.ArgumentParser(prog="llm-yuki", description="LLM Wiki compile pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile", help="Run one compile batch over a Raw Sources folder.")
    compile_parser.add_argument(
        "source_dir", type=Path, help="Raw Sources root (folder = document, txt + images/ per document)."
    )
    compile_parser.add_argument("bundle_dir", type=Path, help="Output OKF bundle directory.")
    compile_parser.add_argument("--batch-id", type=int, default=1, help="Batch identifier (default: 1).")
    compile_parser.add_argument(
        "--pipeline-state-dir",
        type=Path,
        default=None,
        help="Directory for pipeline-internal state (error_book.yaml, cost_ledger.jsonl). "
        "Defaults to a 'pipeline-state' sibling of bundle_dir.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns the process exit code."""
    args = build_parser().parse_args(argv)

    if args.command == "compile":
        pipeline_state_dir = args.pipeline_state_dir or (args.bundle_dir.parent / "pipeline-state")
        return _run_compile(args.source_dir, args.bundle_dir, pipeline_state_dir, args.batch_id)

    raise AssertionError(f"unhandled command: {args.command}")  # unreachable: argparse enforces required=True


def _run_compile(source_dir: Path, bundle_dir: Path, pipeline_state_dir: Path, batch_id: int) -> int:
    """Wire every pipeline stage into a real ``Orchestrator`` and run one batch."""
    try:
        llm_client = OpenAICompatibleClient.from_env()
    except LLMConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    connector = TxtFileConnector(source_dir)
    writer = MarkdownWriter(bundle_dir)
    cost_ledger = JsonlCostLedger(pipeline_state_dir)
    error_book_store = YamlErrorBookStore(pipeline_state_dir)
    error_book = error_book_store.load()

    orchestrator = Orchestrator(
        connector=connector,
        writer=writer,
        extractor=LLMExtractor(llm_client, cost_ledger),
        merger=DefaultMerger(),
        validator=DefaultValidator(llm_client, cost_ledger),
        fixer=DefaultFixer(llm_client, cost_ledger),
        error_book=error_book,
    )
    orchestrator.run_batch(batch_id)
    error_book_store.save(error_book)
    return 0


if __name__ == "__main__":
    sys.exit(main())
