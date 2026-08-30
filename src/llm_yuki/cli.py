"""Command-line entrypoint for running the compile pipeline.

Pipeline execution is exposed as a CLI first — no web/API service is planned for this POC (see root
`ARCHITECTURE.md` §5). Wires the `Connector`/`Writer` adapters together with the LLM-backed
`Extractor`/`Validator`/`Fixer` and the deterministic `Merger`/`ErrorBook` into a real `Orchestrator` and
runs one batch. LLM configuration (`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`LLM_MODEL`) is validated *before*
anything else runs, so a missing/misconfigured endpoint fails immediately with a clear message rather than
partway through a batch. A `.env` file (see `.env.example`) is loaded automatically from the current or a
parent directory — real environment variables always take precedence over it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

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
from llm_yuki.logging import configure_logging, get_logger

logger = get_logger(__name__)


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
    compile_parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Max concurrent Phase 1 (SelectPages/CompileWikiPages) extraction calls (D12). Default: 4.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns the process exit code."""
    configure_logging()
    # Search from the current working directory upward (usecwd=True) — not from this file's location,
    # which is python-dotenv's default and would search the package's install path instead of wherever
    # the user actually ran the command from.
    load_dotenv(find_dotenv(usecwd=True))
    args = build_parser().parse_args(argv)

    if args.command == "compile":
        pipeline_state_dir = args.pipeline_state_dir or (args.bundle_dir.parent / "pipeline-state")
        return _run_compile(args.source_dir, args.bundle_dir, pipeline_state_dir, args.batch_id, args.max_workers)

    raise AssertionError(f"unhandled command: {args.command}")  # unreachable: argparse enforces required=True


def _run_compile(source_dir: Path, bundle_dir: Path, pipeline_state_dir: Path, batch_id: int, max_workers: int) -> int:
    """Wire every pipeline stage into a real ``Orchestrator`` and run one batch."""
    try:
        llm_client = OpenAICompatibleClient.from_env()
    except LLMConfigError as exc:
        logger.error("LLM configuration error: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    logger.info(
        "starting compile: source_dir=%s bundle_dir=%s batch_id=%d max_workers=%d",
        source_dir,
        bundle_dir,
        batch_id,
        max_workers,
    )

    connector = TxtFileConnector(source_dir)
    writer = MarkdownWriter(bundle_dir)
    cost_ledger = JsonlCostLedger(pipeline_state_dir)
    error_book_store = YamlErrorBookStore(pipeline_state_dir)
    error_book = error_book_store.load()

    orchestrator = Orchestrator(
        connector=connector,
        writer=writer,
        extractor=LLMExtractor(llm_client, cost_ledger),
        merger=DefaultMerger(llm_client, cost_ledger),
        validator=DefaultValidator(llm_client, cost_ledger),
        fixer=DefaultFixer(llm_client, cost_ledger),
        error_book=error_book,
        max_workers=max_workers,
    )
    orchestrator.run_batch(batch_id)
    error_book_store.save(error_book)
    logger.info("compile finished: batch_id=%d", batch_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
