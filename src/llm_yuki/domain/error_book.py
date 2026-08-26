"""Error Book: the matched five-phase lint lifecycle from docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md §4.

Holds the seven structural/content error types (§4.1), the Discover→Attribute→Constrain→Inject→Verify&Close
lifecycle (§4.2), and the ``pipeline-state/error_book.yaml`` row schema (§4.4). The actual Discover/Attribute
logic (deterministic checks + LLM verification) lives in ``domain.pipeline.Validator``/``Fixer`` — this module
only tracks entry state and lifecycle transitions, and is intentionally left as a stub pending that wiring.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ErrorType = Literal[
    "dangling_links",
    "incomplete_pages",
    "malformed_refs",
    "unseen_overwrite",
    "index_inconsistency",
    "unsupported_facts",
    "cross_page_contradictions",
]
"""The seven error classes from proposal ARCHITECTURE.md §4.1 (first five structural, last two content)."""


class ValidationIssue(BaseModel):
    """One Discover-phase finding, before it is turned into a full ``ErrorBookEntry``."""

    error_type: ErrorType
    phenomenon: str
    affected_refs: list[str] = Field(default_factory=list)


class ErrorBookEntry(BaseModel):
    """One row of ``pipeline-state/error_book.yaml`` (proposal ARCHITECTURE.md §4.4)."""

    id: str
    error_type: ErrorType
    phenomenon: str
    affected_refs: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    constraint_rule: str | None = None
    verification_method: str | None = None
    status: Literal["open", "closed"] = "open"
    discovered_at_batch: int
    closed_at_batch: int | None = None


class ErrorBook(BaseModel):
    """In-memory Error Book (``ℬ`` in Algorithm 1). Persistence to ``error_book.yaml`` is future work.

    The four functions below correspond 1:1 to Algorithm 1's ``UpdateErrorBook``/``ActiveConstraints``/
    ``PeriodicFixDue``/``VerifyAndClose`` (proposal ARCHITECTURE.md §2.2.4, §4.2). All are pending
    implementation — see README.md POC Status and ASSUMPTIONS.md B-2 (contradiction-detection recall risk).
    """

    entries: list[ErrorBookEntry] = Field(default_factory=list)

    def update_error_book(self, issues: list[ValidationIssue], batch_id: int) -> list[ErrorBookEntry]:
        """Algorithm 1 line 8: ``ℬ ← UpdateErrorBook(ℬ, E)`` — Discover + Attribute + Constrain."""
        raise NotImplementedError

    def active_constraints(self) -> list[str]:
        """Algorithm 1 line 9: ``C ← ActiveConstraints(ℬ)`` — Inject: open entries' constraint_rule text."""
        raise NotImplementedError

    def periodic_fix_due(self, batch_id: int) -> bool:
        """Algorithm 1 line 14: whether ``LLMPeriodicFix`` should run for this batch (cadence N, see §4.3)."""
        raise NotImplementedError

    def verify_and_close(self) -> None:
        """Algorithm 1 line 16: ``ℬ ← VerifyAndClose(ℬ, W)`` — re-check open entries, close resolved ones."""
        raise NotImplementedError
