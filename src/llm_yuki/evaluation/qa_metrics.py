"""Exact-match / F1 scoring — the standard SQuAD-style normalization+scoring convention used across the
multi-hop QA literature this project's `M3SciQA`/`MMDocRAG`/`MuSiQue` benchmarks belong to (proposal
`README.md` D5; the LLM-Wiki paper's own F1 numbers on HotpotQA/MuSiQue/2WikiMultiHopQA use the same
normalization, per `QUERY-SEARCH-SURVEY.md` §2). Pure — no I/O, trivially unit-testable.
"""

from __future__ import annotations

import re
import string
from collections import Counter
from collections.abc import Iterable

_ARTICLES = {"a", "an", "the"}


def normalize_answer(text: str) -> str:
    """Lowercase, strip punctuation, drop articles, collapse whitespace — the standard QA-eval normalization."""
    lowered = text.lower()
    without_punctuation = "".join(ch for ch in lowered if ch not in string.punctuation)
    tokens = [token for token in without_punctuation.split() if token not in _ARTICLES]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def exact_match(prediction: str, gold: str) -> bool:
    """Whether ``prediction`` matches ``gold`` after normalization."""
    return normalize_answer(prediction) == normalize_answer(gold)


def f1_score(prediction: str, gold: str) -> float:
    """Token-overlap F1 between ``prediction`` and ``gold``, after normalization."""
    pred_tokens = normalize_answer(prediction).split()
    gold_tokens = normalize_answer(gold).split()
    if not pred_tokens or not gold_tokens:
        return float(pred_tokens == gold_tokens)

    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0

    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def best_exact_match(prediction: str, golds: Iterable[str]) -> bool:
    """Whether ``prediction`` exact-matches any of several acceptable ``golds`` (multi-reference QA)."""
    return any(exact_match(prediction, gold) for gold in golds)


def best_f1(prediction: str, golds: Iterable[str]) -> float:
    """The best F1 across several acceptable ``golds`` (multi-reference QA); ``0.0`` if ``golds`` is empty."""
    return max((f1_score(prediction, gold) for gold in golds), default=0.0)
