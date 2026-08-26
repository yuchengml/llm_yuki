"""``Connector``: the input port that turns Raw Sources into passages the Orchestrator can process.

See docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md §1.1 and §2.1 for the Raw Source format (folder = document,
``txt`` body + ``images/``) and the minimal interface this port must expose.
"""

from __future__ import annotations

import abc

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """Identifies one Raw Source document within a batch."""

    id: str = Field(description="Stable identifier for this source, e.g. its folder name.")


class Document(BaseModel):
    """A Raw Source document as read by a Connector.

    ``text`` keeps any markdown image links (``![alt](images/fig1.png)``) inline, unresolved — per D10's
    two-part decision, image *links* are preserved as structured references but image *content* is never
    interpreted (no OCR, no vision model) in this POC.
    """

    ref: SourceRef
    text: str
    image_links: list[str] = Field(
        default_factory=list, description="Image links found in `text`, extracted for convenience."
    )


class Connector(abc.ABC):
    """Input port: lists and reads Raw Source documents for a compile batch.

    Implementations live under ``llm_yuki.adapters.connectors`` and may perform arbitrary I/O (filesystem,
    network, third-party APIs). ``domain`` code must only depend on this interface.
    """

    @abc.abstractmethod
    def list_sources(self) -> list[SourceRef]:
        """Return the set of sources available for this compile batch."""
        raise NotImplementedError

    @abc.abstractmethod
    def read_source(self, ref: SourceRef) -> Document:
        """Read one source's body text, preserving any image links found in it."""
        raise NotImplementedError
