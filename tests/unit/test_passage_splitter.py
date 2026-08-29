"""Unit tests for the default natural-paragraph passage splitter (D11) — pure, no I/O."""

from __future__ import annotations

import pytest

from llm_yuki.domain.passage_splitter import split_into_natural_paragraphs

pytestmark = pytest.mark.unit


def test_splits_on_a_single_blank_line() -> None:
    text = "First paragraph.\n\nSecond paragraph."

    assert split_into_natural_paragraphs(text) == ["First paragraph.", "Second paragraph."]


def test_collapses_multiple_blank_lines_into_one_break() -> None:
    text = "First paragraph.\n\n\n\nSecond paragraph."

    assert split_into_natural_paragraphs(text) == ["First paragraph.", "Second paragraph."]


def test_text_with_no_blank_line_is_a_single_passage() -> None:
    """D11: not a fixed-length chunker — no blank lines means the whole document is one natural unit."""
    text = "Just one paragraph, no breaks, even across\na single embedded newline."

    assert split_into_natural_paragraphs(text) == [text]


def test_trims_surrounding_whitespace_from_each_paragraph() -> None:
    text = "  First paragraph.  \n\n  Second paragraph.  "

    assert split_into_natural_paragraphs(text) == ["First paragraph.", "Second paragraph."]


def test_drops_empty_paragraphs_from_leading_trailing_or_repeated_breaks() -> None:
    text = "\n\nFirst paragraph.\n\n\nSecond paragraph.\n\n"

    assert split_into_natural_paragraphs(text) == ["First paragraph.", "Second paragraph."]


def test_empty_text_returns_no_passages() -> None:
    assert split_into_natural_paragraphs("") == []


def test_whitespace_only_text_returns_no_passages() -> None:
    assert split_into_natural_paragraphs("   \n\n   ") == []


def test_three_paragraphs_preserve_order() -> None:
    text = "Alpha.\n\nBeta.\n\nGamma."

    assert split_into_natural_paragraphs(text) == ["Alpha.", "Beta.", "Gamma."]
