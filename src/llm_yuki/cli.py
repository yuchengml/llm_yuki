"""Command-line entrypoint for running the compile pipeline.

Pipeline execution is exposed as a CLI first — no web/API service is planned for this POC (see root
`ARCHITECTURE.md` §5). This wires the already-implemented `Connector`/`Writer` adapters, but
`Extractor`/`Merger`/`Validator`/`ErrorBook`/`Fixer` are still interface stubs (see `TODO.md` section B) —
`Orchestrator` cannot be constructed without concrete implementations of those, so `compile` fails fast with
a clear error instead of silently doing nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


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

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns the process exit code."""
    args = build_parser().parse_args(argv)

    if args.command == "compile":
        return _run_compile(args.source_dir, args.bundle_dir, args.batch_id)

    raise AssertionError(f"unhandled command: {args.command}")  # unreachable: argparse enforces required=True


def _run_compile(source_dir: Path, bundle_dir: Path, batch_id: int) -> int:
    """Wire Connector/Writer into the Orchestrator and run one batch.

    Not yet functional: `Extractor`/`Merger`/`Validator`/`ErrorBook`/`Fixer` have no concrete implementation
    (`TODO.md` section B), and `Orchestrator` requires all five. Fails immediately rather than partially
    running the pipeline or silently no-op-ing.
    """
    del source_dir, bundle_dir, batch_id  # not yet used — see docstring
    print(
        "error: compile pipeline logic (Extractor/Merger/Validator/ErrorBook/Fixer) is not implemented yet — "
        "see TODO.md section B for the remaining work.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
