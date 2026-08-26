"""Integration tests for TxtFileConnector — exercises the real filesystem."""

from pathlib import Path

import pytest

from llm_yuki.adapters.connectors.txt_file_connector import TxtFileConnector
from llm_yuki.ports.connector import SourceRef

pytestmark = pytest.mark.integration


def _make_document(root: Path, name: str, text: str) -> None:
    doc_dir = root / name
    doc_dir.mkdir(parents=True)
    (doc_dir / "body.txt").write_text(text, encoding="utf-8")


def test_list_sources_returns_one_ref_per_document_folder(tmp_path: Path) -> None:
    _make_document(tmp_path, "doc-a", "Hello")
    _make_document(tmp_path, "doc-b", "World")

    connector = TxtFileConnector(tmp_path)

    refs = {ref.id for ref in connector.list_sources()}
    assert refs == {"doc-a", "doc-b"}


def test_read_source_preserves_image_links_in_text_and_extracts_them(tmp_path: Path) -> None:
    text = "See the results.\n\n![figure 1](images/fig1.png)\n"
    _make_document(tmp_path, "doc-a", text)

    connector = TxtFileConnector(tmp_path)
    document = connector.read_source(SourceRef(id="doc-a"))

    assert document.text == text
    assert document.image_links == ["images/fig1.png"]


def test_read_source_missing_txt_file_raises_file_not_found(tmp_path: Path) -> None:
    (tmp_path / "doc-a").mkdir()

    connector = TxtFileConnector(tmp_path)

    with pytest.raises(FileNotFoundError):
        connector.read_source(SourceRef(id="doc-a"))


def test_read_source_rejects_path_traversal(tmp_path: Path) -> None:
    _make_document(tmp_path, "doc-a", "Hello")

    connector = TxtFileConnector(tmp_path / "doc-a")

    with pytest.raises(ValueError, match="escapes"):
        connector.read_source(SourceRef(id="../"))
