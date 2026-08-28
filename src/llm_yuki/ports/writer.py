"""``Writer``: the output port that persists compiled pages and supports reading them back.

See docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md §2.3 for the full responsibility list: persistence, read-back
(needed by ``SelectPages``/``ContentValidate``), deterministic body-link rendering (§2.3.1), and incremental
backlink maintenance (§2.3.2).
"""

from __future__ import annotations

import abc

from llm_yuki.domain.entities import Claim, Concept, Document


class Writer(abc.ABC):
    """Output port: persists ``Claim``/``Concept``/``Document`` pages and supports reading existing ones back.

    Implementations live under ``llm_yuki.adapters.writers``. Whatever the backing store, the persisted output
    must remain exportable/renderable as an OKF-conformant markdown bundle (proposal ARCHITECTURE.md §2.3,
    "硬性約束").
    """

    @abc.abstractmethod
    def write_claim(self, claim: Claim) -> None:
        """Persist a Claim page.

        Implementations must also perform the backlink maintenance described in proposal ARCHITECTURE.md
        §2.3.2/D21: add ``claim.slug`` to each related Concept's ``key_facts`` and to the source Document's
        ``produced_claims``, add each ``related_concepts`` slug to that Document's ``produced_concepts``, and
        symmetrically update the Claims referenced in ``claim.contradicted_by``.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def write_concept(self, concept: Concept) -> None:
        """Persist a Concept page."""
        raise NotImplementedError

    @abc.abstractmethod
    def write_document(self, document: Document) -> None:
        """Persist a Document page (D21)."""
        raise NotImplementedError

    @abc.abstractmethod
    def read_claim(self, slug: str) -> Claim | None:
        """Read back a previously written Claim, or ``None`` if it does not exist."""
        raise NotImplementedError

    @abc.abstractmethod
    def read_concept(self, slug: str) -> Concept | None:
        """Read back a previously written Concept, or ``None`` if it does not exist."""
        raise NotImplementedError

    @abc.abstractmethod
    def read_document(self, slug: str) -> Document | None:
        """Read back a previously written Document, or ``None`` if it does not exist."""
        raise NotImplementedError

    @abc.abstractmethod
    def list_pages(self) -> list[str]:
        """Return the slugs of all pages currently in the bundle (used for ``index.md`` / orphan checks)."""
        raise NotImplementedError

    @abc.abstractmethod
    def append_log(self, event: str) -> None:
        """Append one line to the append-only ``log.md`` audit trail (proposal ARCHITECTURE.md §4.4).

        Called by ``ErrorBook.update_error_book``/``verify_and_close`` — one line per lifecycle event, not
        called directly by the Orchestrator or any other pipeline stage.
        """
        raise NotImplementedError
