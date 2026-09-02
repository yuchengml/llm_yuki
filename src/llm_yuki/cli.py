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
import json
import sys
import time
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from llm_yuki.adapters.connectors.txt_file_connector import TxtFileConnector
from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.fixing.default_fixer import DefaultFixer
from llm_yuki.adapters.llm.answer_synthesizer import LLMAnswerSynthesizer
from llm_yuki.adapters.llm.client import LLMConfigError, OpenAICompatibleClient
from llm_yuki.adapters.llm.extractor import LLMExtractor
from llm_yuki.adapters.llm.next_action_decider import LLMActionDecider
from llm_yuki.adapters.merging.default_merger import DefaultMerger
from llm_yuki.adapters.state.error_book_store import YamlErrorBookStore
from llm_yuki.adapters.stats import compute_run_stats, snapshot_bundle, write_stats_report
from llm_yuki.adapters.validation.default_validator import DefaultValidator
from llm_yuki.adapters.writers.markdown_writer import MarkdownWriter
from llm_yuki.domain.pipeline import Orchestrator
from llm_yuki.domain.query import (
    IterativeAgenticQueryEngine,
    QueryEngine,
    SinglePassQueryEngine,
    StructuredSignalSearch,
    load_corpus,
    retrieve,
)
from llm_yuki.evaluation.qa_runner import load_qa_examples, run_qa_evaluation
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
        help="Size of the shared Phase 1 extraction thread pool (SelectPages/CompileWikiPages calls), drawn "
        "from whichever sources are currently open — may exceed --max-concurrent-documents so several "
        "workers can race through one document's passages (D12). Default: 4.",
    )
    compile_parser.add_argument(
        "--max-concurrent-documents",
        type=int,
        default=4,
        help="Max number of source documents 'open' (passages submitted to the pool) at once during Phase "
        "1; the next queued document opens as soon as an open one's passages all finish. Default: 4.",
    )

    search_parser = subparsers.add_parser(
        "search",
        help="Run retrieval only (StructuredSignalSearch + RRF fusion + graph expansion) against an OKF "
        "bundle, no LLM/synthesis, no OPENAI_* config needed (D25).",
    )
    search_parser.add_argument("bundle_dir", type=Path, help="OKF bundle directory to read (never written to).")
    search_parser.add_argument("query", type=str, help="The search query.")
    search_parser.add_argument("--top-k", type=int, default=8, help="Max results to return. Default: 8.")

    query_parser = subparsers.add_parser("query", help="Answer one question against an existing OKF bundle (D25).")
    query_parser.add_argument("bundle_dir", type=Path, help="OKF bundle directory to read (never written to).")
    query_parser.add_argument("question", type=str, help="The question to answer.")
    query_parser.add_argument(
        "--method",
        choices=("single-pass", "agentic"),
        default="single-pass",
        help="'single-pass': search->fuse->graph-expand->read->synthesize, once (default). "
        "'agentic': iterative wiki_search/wiki_read loop with T_max/patience termination (D25).",
    )
    query_parser.add_argument("--top-k", type=int, default=8, help="Max pages considered for the answer. Default: 8.")
    query_parser.add_argument("--batch-id", type=int, default=1, help="Batch identifier for cost-ledger recording.")
    query_parser.add_argument(
        "--pipeline-state-dir",
        type=Path,
        default=None,
        help="Directory for pipeline-internal state (cost_ledger.jsonl). Defaults to a 'pipeline-state' "
        "sibling of bundle_dir.",
    )
    query_parser.add_argument(
        "--t-max", type=int, default=6, help="Agentic method only: max tool calls before stopping. Default: 6."
    )
    query_parser.add_argument(
        "--patience",
        type=int,
        default=2,
        help="Agentic method only: consecutive empty searches before stopping. Default: 2.",
    )

    eval_parser = subparsers.add_parser(
        "evaluate-qa", help="Run a QueryEngine over a QA JSONL against an existing OKF bundle and report EM/F1 (D8)."
    )
    eval_parser.add_argument("bundle_dir", type=Path, help="OKF bundle directory to read (never written to).")
    eval_parser.add_argument(
        "qa_path", type=Path, help="QA pairs JSONL — one {'question': ..., 'answers'|'answer': ...} per line."
    )
    eval_parser.add_argument("--method", choices=("single-pass", "agentic"), default="single-pass")
    eval_parser.add_argument("--top-k", type=int, default=8)
    eval_parser.add_argument("--batch-id", type=int, default=1)
    eval_parser.add_argument("--pipeline-state-dir", type=Path, default=None)
    eval_parser.add_argument("--t-max", type=int, default=6)
    eval_parser.add_argument("--patience", type=int, default=2)
    eval_parser.add_argument(
        "--output", type=Path, default=None, help="Optional path to write the full JSON report (EM/F1 + every example)."
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
        return _run_compile(
            args.source_dir,
            args.bundle_dir,
            pipeline_state_dir,
            args.batch_id,
            args.max_workers,
            args.max_concurrent_documents,
        )

    if args.command == "search":
        return _run_search(args)

    if args.command == "query":
        pipeline_state_dir = args.pipeline_state_dir or (args.bundle_dir.parent / "pipeline-state")
        return _run_query(args, pipeline_state_dir)

    if args.command == "evaluate-qa":
        pipeline_state_dir = args.pipeline_state_dir or (args.bundle_dir.parent / "pipeline-state")
        return _run_evaluate_qa(args, pipeline_state_dir)

    raise AssertionError(f"unhandled command: {args.command}")  # unreachable: argparse enforces required=True


def _run_compile(
    source_dir: Path,
    bundle_dir: Path,
    pipeline_state_dir: Path,
    batch_id: int,
    max_workers: int,
    max_concurrent_documents: int,
) -> int:
    """Wire every pipeline stage into a real ``Orchestrator`` and run one batch."""
    try:
        llm_client = OpenAICompatibleClient.from_env()
    except LLMConfigError as exc:
        logger.error("LLM configuration error: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    logger.info(
        "starting compile: source_dir=%s bundle_dir=%s batch_id=%d max_workers=%d max_concurrent_documents=%d",
        source_dir,
        bundle_dir,
        batch_id,
        max_workers,
        max_concurrent_documents,
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
        max_concurrent_documents=max_concurrent_documents,
    )

    # Snapshot before / stopwatch around run_batch: compilation statistics (D27) need "what changed in this
    # run" and a true end-to-end wall-clock figure, neither of which the Orchestrator itself tracks (it stays
    # domain-pure — no stats/telemetry concern threaded into it, same reasoning as cost_ledger's D19 split).
    before_snapshot = snapshot_bundle(bundle_dir, writer)
    started = time.monotonic()
    orchestrator.run_batch(batch_id)
    e2e_wall_clock_ms = (time.monotonic() - started) * 1000

    error_book_store.save(error_book)

    run_stats = compute_run_stats(
        batch_id=batch_id,
        bundle_dir=bundle_dir,
        writer=writer,
        cost_ledger=cost_ledger,
        error_book=error_book,
        e2e_wall_clock_ms=e2e_wall_clock_ms,
        before=before_snapshot,
    )
    stats_path = write_stats_report(run_stats, pipeline_state_dir)
    logger.info("compile finished: batch_id=%d, stats report: %s", batch_id, stats_path)
    return 0


def _run_search(args: argparse.Namespace) -> int:
    """Run retrieval only — no LLM client, no ``OPENAI_*`` config needed at all (D25)."""
    logger.info("starting search: bundle_dir=%s top_k=%d", args.bundle_dir, args.top_k)

    writer = MarkdownWriter(args.bundle_dir)
    corpus = load_corpus(writer)
    corpus_by_slug = {page.slug: page for page in corpus}
    hits = retrieve(args.query, corpus, strategies=[StructuredSignalSearch()], top_k=args.top_k)

    if not hits:
        print("No results.")
        return 0

    for rank, hit in enumerate(hits, start=1):
        page = corpus_by_slug.get(hit.slug)
        title = page.title if page is not None else "?"
        page_type = page.page_type if page is not None else "?"
        snippet = _snippet(page.content) if page is not None else ""
        print(f"{rank}. [{page_type}] {hit.slug} — {title}  (score={hit.score:.4f}, via={hit.matched_field})")
        if snippet:
            print(f"   {snippet}")

    logger.info("search finished: query=%r results=%d", args.query, len(hits))
    return 0


def _snippet(text: str, max_chars: int = 160) -> str:
    """Flatten ``text`` to a single-line preview, truncated with an ellipsis if too long."""
    flattened = " ".join(text.split())
    if len(flattened) <= max_chars:
        return flattened
    return flattened[:max_chars].rsplit(" ", 1)[0] + "…"


def _build_query_engine(
    args: argparse.Namespace, llm_client: OpenAICompatibleClient, cost_ledger: JsonlCostLedger
) -> QueryEngine:
    """Assemble the ``QueryEngine`` (D25) named by ``args.method`` — shared by ``query`` and ``evaluate-qa``."""
    if args.method == "single-pass":
        return SinglePassQueryEngine(
            strategies=[StructuredSignalSearch()],
            synthesizer=LLMAnswerSynthesizer(llm_client, cost_ledger),
        )
    return IterativeAgenticQueryEngine(
        strategy=StructuredSignalSearch(),
        decider=LLMActionDecider(llm_client, cost_ledger, args.batch_id),
        synthesizer=LLMAnswerSynthesizer(llm_client, cost_ledger),
        t_max=args.t_max,
        patience=args.patience,
    )


def _run_query(args: argparse.Namespace, pipeline_state_dir: Path) -> int:
    """Wire a ``QueryEngine`` (D25) together and answer one question, read-only against ``bundle_dir``."""
    try:
        llm_client = OpenAICompatibleClient.from_env()
    except LLMConfigError as exc:
        logger.error("LLM configuration error: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    logger.info(
        "starting query: bundle_dir=%s method=%s top_k=%d batch_id=%d",
        args.bundle_dir,
        args.method,
        args.top_k,
        args.batch_id,
    )

    writer = MarkdownWriter(args.bundle_dir)
    cost_ledger = JsonlCostLedger(pipeline_state_dir)
    engine = _build_query_engine(args, llm_client, cost_ledger)

    result = engine.answer(args.question, writer, args.batch_id, top_k=args.top_k)
    print(result.answer)
    print()
    print(f"Cited pages: {', '.join(result.cited_slugs) if result.cited_slugs else '(none)'}")
    logger.info("query finished: method=%s cited=%d page(s)", result.method, len(result.cited_slugs))
    return 0


def _run_evaluate_qa(args: argparse.Namespace, pipeline_state_dir: Path) -> int:
    """Run a ``QueryEngine`` (D25) over ``qa_path``'s QA pairs against ``bundle_dir`` and report EM/F1 (D8)."""
    try:
        llm_client = OpenAICompatibleClient.from_env()
    except LLMConfigError as exc:
        logger.error("LLM configuration error: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    examples = load_qa_examples(args.qa_path)
    logger.info(
        "starting evaluate-qa: bundle_dir=%s qa_path=%s method=%s examples=%d",
        args.bundle_dir,
        args.qa_path,
        args.method,
        len(examples),
    )

    writer = MarkdownWriter(args.bundle_dir)
    cost_ledger = JsonlCostLedger(pipeline_state_dir)
    engine = _build_query_engine(args, llm_client, cost_ledger)

    report = run_qa_evaluation(examples, engine, writer, batch_id=args.batch_id, top_k=args.top_k)
    print(f"method={report.method} count={report.count} exact_match={report.exact_match:.4f} f1={report.f1:.4f}")
    if args.output is not None:
        args.output.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Full report written to {args.output}")
    logger.info("evaluate-qa finished: exact_match=%.4f f1=%.4f", report.exact_match, report.f1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
