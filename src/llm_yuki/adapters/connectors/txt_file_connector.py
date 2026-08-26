"""Default/first Connector (decision D10): reads the "folder = document, txt + images/" Raw Source format.

See docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md §1.1 and README.md D10 / D10 二次更正.
"""

from __future__ import annotations

import re
from pathlib import Path

from llm_yuki.ports.connector import Connector, Document, SourceRef

_IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


class TxtFileConnector(Connector):
    """Reads Raw Sources where each immediate subdirectory of ``root`` is one document.

    Each document directory must contain exactly one ``.txt`` body file. An optional ``images/``
    subdirectory may hold referenced images; their *content* is never read here — only the markdown image
    links already present in the text are extracted, per D10's "link preserved, content not interpreted"
    decision.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def list_sources(self) -> list[SourceRef]:
        """Return one SourceRef per immediate subdirectory of the Raw Sources root."""
        if not self._root.is_dir():
            return []
        return [SourceRef(id=child.name) for child in sorted(self._root.iterdir()) if child.is_dir()]

    def read_source(self, ref: SourceRef) -> Document:
        """Read a document's ``.txt`` body, preserving any markdown image links found in it."""
        doc_dir = self._resolve_doc_dir(ref)

        txt_files = sorted(doc_dir.glob("*.txt"))
        if not txt_files:
            raise FileNotFoundError(f"Raw Source document {doc_dir} has no .txt body file")
        if len(txt_files) > 1:
            raise ValueError(f"Raw Source document {doc_dir} has {len(txt_files)} .txt files; expected exactly one")

        text = txt_files[0].read_text(encoding="utf-8")
        image_links = _IMAGE_LINK_PATTERN.findall(text)
        return Document(ref=ref, text=text, image_links=image_links)

    def _resolve_doc_dir(self, ref: SourceRef) -> Path:
        root_resolved = self._root.resolve()
        doc_dir = (self._root / ref.id).resolve()
        if doc_dir != root_resolved and root_resolved not in doc_dir.parents:
            raise ValueError(f"Source ref {ref.id!r} escapes the Raw Sources root")
        if not doc_dir.is_dir():
            raise FileNotFoundError(f"No such Raw Source document: {doc_dir}")
        return doc_dir
