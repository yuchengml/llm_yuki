"""Unit tests for the SQuAD-style EM/F1 scoring functions (`evaluation/qa_metrics.py`) — pure, no I/O."""

from __future__ import annotations

import pytest

from llm_yuki.evaluation.qa_metrics import best_exact_match, best_f1, exact_match, f1_score, normalize_answer

pytestmark = pytest.mark.unit


def test_normalize_answer_lowercases_strips_punctuation_and_articles() -> None:
    assert normalize_answer("The Water, boils!") == "water boils"


def test_normalize_answer_collapses_whitespace() -> None:
    assert normalize_answer("water   boils") == "water boils"


def test_exact_match_ignores_case_punctuation_and_articles() -> None:
    assert exact_match("The water boils.", "water boils") is True


def test_exact_match_false_on_different_content() -> None:
    assert exact_match("water freezes", "water boils") is False


def test_f1_score_perfect_match_is_one() -> None:
    assert f1_score("water boils", "water boils") == 1.0


def test_f1_score_partial_overlap() -> None:
    # prediction has 2 tokens, gold has 3, 2 shared -> precision=1.0, recall=2/3, F1=0.8
    assert f1_score("water boils", "water boils quickly") == pytest.approx(0.8)


def test_f1_score_no_overlap_is_zero() -> None:
    assert f1_score("fire burns", "water boils") == 0.0


def test_f1_score_both_empty_after_normalization_is_one() -> None:
    assert f1_score("the a an", "the") == 1.0  # both normalize to "" -> treated as a match


def test_f1_score_one_empty_after_normalization_is_zero() -> None:
    assert f1_score("the", "water") == 0.0


def test_best_exact_match_true_if_any_gold_matches() -> None:
    assert best_exact_match("100C", ["boiling point", "100C", "212F"]) is True


def test_best_exact_match_false_if_no_gold_matches() -> None:
    assert best_exact_match("0C", ["100C", "212F"]) is False


def test_best_f1_picks_the_highest_scoring_gold() -> None:
    assert best_f1("water boils", ["fire burns", "water boils quickly"]) == pytest.approx(0.8)


def test_best_f1_empty_golds_is_zero() -> None:
    assert best_f1("water boils", []) == 0.0
