"""``Writer``: the output port that persists compiled pages and supports reading them back.

See docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md §2.3 for the full responsibility list: persistence, read-back
(needed by ``SelectPages``/``ContentValidate``), deterministic body-link rendering (§2.3.1), and incremental
backlink maintenance (§2.3.2).
"""

from __future__ import annotations

import abc

from llm_yuki.domain.entities import Claim, Concept


class Writer(abc.ABC):
    """Output port: persists ``Claim``/``Concept`` pages and supports reading existing ones back.

    Implementations live under ``llm_yuki.adapters.writers``. Whatever the backing store, the persisted output
    must remain exportable/renderable as an OKF-conformant markdown bundle (proposal ARCHITECTURE.md §2.3,
    "硬性約束").
    """

    @abc.abstractmethod
    def write_claim(self, claim: Claim) -> None:
        """Persist a Claim page.

        Implementations must also perform the backlink maintenance described in proposal ARCHITECTURE.md
        §2.3.2: add ``claim.slug`` to each related Concept's ``key_facts``, and symmetrically update the
        Claims referenced in ``claim.contradicted_by``.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def write_concept(self, concept: Concept) -> None:
        """Persist a Concept page."""
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
    def list_pages(self) -> list[str]:
        """Return the slugs of all pages currently in the bundle (used for ``index.md`` / orphan checks)."""
        raise NotImplementedError
