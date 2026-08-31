r"""Convert MuSiQue questions into this pipeline's Raw Source format (D10) + a QA JSONL for `llm-yuki
evaluate-qa` (D25/D8) — the "MuSiQue subset" experiment, see docs/llm-yuki-v0.1-proposal/README.md D26.

Not part of the llm_yuki package/pipeline (same standalone-utility status as scripts/call_llm.py) — a one-off
data-prep script.

**Data source**: MuSiQue itself (arXiv 2108.00573, CC BY 4.0) has no directly-downloadable official JSONL —
only a Google Drive zip via its own download_data.sh, which this environment's egress policy may block
(Google Drive/HuggingFace were unreachable when this script was written; see D26). Instead this script reads
`OSU-NLP-Group/HippoRAG`'s `reproduce/dataset/musique.json` (MIT-licensed repo, verified by cloning it
directly) — a 1000-question MuSiQue dev subset (`question`/`answer`/`answer_aliases`/`paragraphs`, each
paragraph with `title`/`paragraph_text`/`is_supporting`) that HippoRAG/LightRAG/GraphRAG-Bench-adjacent
literature uses for exactly this kind of evaluation. Verified: deduplicating every paragraph across all 1000
questions yields exactly 11,656 unique (title, paragraph_text) pairs — the same count as that repo's separate
`musique_corpus.json`, confirming the two files describe the same underlying corpus. Downloaded once and
cached under ``--cache-dir`` (default ``.cache/musique/``).

**Two modes** (D26 decision 2):

- Sample mode (default): samples ``--num-questions`` questions (``--seed`` for reproducibility), pools only
  their own paragraphs (supporting + distractor) into Raw Source documents. Bounded LLM compile cost — use
  this to try the pipeline end to end.
- ``--full-corpus``: all 1000 questions, ~11,656 paragraphs — the literature-comparable setup, but expensive
  to compile through an LLM-backed Extractor. Not run by default.

**D26 decision 3** applies regardless of mode: a sample-mode EM/F1 number is not comparable to published
MuSiQue baselines (HippoRAG 2/LightRAG/GraphRAG/the LLM-Wiki paper) — those all report against the full 1000
questions. Only ``--full-corpus`` runs are in the same experimental setting as the literature.

Usage::

    poetry run python scripts/musique_subset_to_raw_sources.py \\
        --num-questions 20 --seed 0 \\
        --out-raw-sources data/raw_sources/musique-sample \\
        --out-qa-jsonl data/musique-sample-qa.jsonl

Then, with LLM configuration set up (see root README.md "Run the CLI")::

    poetry run llm-yuki compile data/raw_sources/musique-sample bundle
    poetry run llm-yuki evaluate-qa bundle data/musique-sample-qa.jsonl --output report.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import urllib.request
from pathlib import Path
from typing import Any

_MUSIQUE_JSON_URL = "https://raw.githubusercontent.com/OSU-NLP-Group/HippoRAG/main/reproduce/dataset/musique.json"
_DEFAULT_CACHE_DIR = Path(".cache/musique")
_DEFAULT_NUM_QUESTIONS = 20
_DEFAULT_SEED = 0


def download_musique_json(cache_dir: Path) -> Path:
    """Download HippoRAG's ``musique.json`` if not already cached under ``cache_dir``, return its path."""
    cache_path = cache_dir / "musique.json"
    if not cache_path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        print(f"downloading {_MUSIQUE_JSON_URL} -> {cache_path}")
        urllib.request.urlretrieve(_MUSIQUE_JSON_URL, cache_path)  # noqa: S310 — fixed, hardcoded https URL
    return cache_path


def load_questions(musique_json_path: Path) -> list[dict[str, Any]]:
    """Load every question from a local ``musique.json`` copy."""
    data: list[dict[str, Any]] = json.loads(musique_json_path.read_text(encoding="utf-8"))
    return data


def sample_questions(questions: list[dict[str, Any]], num_questions: int, seed: int) -> list[dict[str, Any]]:
    """Deterministically sample ``num_questions`` questions from ``questions``."""
    rng = random.Random(seed)
    return rng.sample(questions, min(num_questions, len(questions)))


def _slugify(text: str, max_len: int = 60) -> str:
    """Filesystem-safe slug: lowercase, non-alphanumeric runs collapsed to single hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "untitled"


def write_raw_sources(questions: list[dict[str, Any]], out_dir: Path) -> int:
    """Pool every sampled question's paragraphs (deduped) into D10 Raw Source folders under ``out_dir``.

    Each unique ``(title, paragraph_text)`` pair becomes one folder (``<index>-<slugified title>/body.txt``,
    matching ``TxtFileConnector``'s "folder = document, one .txt body file" format) — a paragraph shared by
    more than one sampled question is written once. Returns the number of documents written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str]] = set()
    written = 0
    for question in questions:
        for paragraph in question["paragraphs"]:
            key = (paragraph["title"], paragraph["paragraph_text"])
            if key in seen:
                continue
            seen.add(key)
            slug = f"{written:05d}-{_slugify(paragraph['title'])}"
            doc_dir = out_dir / slug
            doc_dir.mkdir(parents=True, exist_ok=True)
            (doc_dir / "body.txt").write_text(
                f"# {paragraph['title']}\n\n{paragraph['paragraph_text']}\n", encoding="utf-8"
            )
            written += 1
    return written


def write_qa_jsonl(questions: list[dict[str, Any]], out_path: Path) -> None:
    """Write ``evaluate-qa``'s JSONL format: one ``{"id", "question", "answers"}`` object per line."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for question in questions:
        answers = [question["answer"], *question.get("answer_aliases", [])]
        lines.append(json.dumps({"id": question["id"], "question": question["question"], "answers": answers}))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--num-questions",
        type=int,
        default=_DEFAULT_NUM_QUESTIONS,
        help=f"Questions to sample (ignored with --full-corpus). Default: {_DEFAULT_NUM_QUESTIONS}.",
    )
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED, help=f"Random seed. Default: {_DEFAULT_SEED}.")
    parser.add_argument(
        "--full-corpus",
        action="store_true",
        help="Use all 1000 questions (~11,656 paragraphs) instead of sampling — the literature-comparable "
        "setup (D26 decision 2), but expensive to compile. Off by default.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=_DEFAULT_CACHE_DIR,
        help=f"Download cache directory. Default: {_DEFAULT_CACHE_DIR}.",
    )
    parser.add_argument(
        "--musique-json",
        type=Path,
        default=None,
        help="Path to an already-downloaded musique.json (skips the download).",
    )
    parser.add_argument("--out-raw-sources", type=Path, required=True, help="Output Raw Sources root (D10 format).")
    parser.add_argument("--out-qa-jsonl", type=Path, required=True, help="Output QA JSONL path (evaluate-qa format).")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Script entrypoint. Returns the process exit code."""
    args = build_parser().parse_args(argv)

    musique_json_path = args.musique_json or download_musique_json(args.cache_dir)
    all_questions = load_questions(musique_json_path)
    print(f"loaded {len(all_questions)} question(s) from {musique_json_path}")

    if args.full_corpus:
        questions = all_questions
        print("--full-corpus: using all questions (literature-comparable setup, D26 decision 2)")
    else:
        questions = sample_questions(all_questions, args.num_questions, args.seed)
        print(f"sampled {len(questions)} question(s) (seed={args.seed})")
        print("not comparable to literature numbers in this mode — see D26 decision 3")

    num_documents = write_raw_sources(questions, args.out_raw_sources)
    write_qa_jsonl(questions, args.out_qa_jsonl)

    print(f"wrote {num_documents} Raw Source document(s) to {args.out_raw_sources}")
    print(f"wrote {len(questions)} QA pair(s) to {args.out_qa_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
