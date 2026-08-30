"""Error Book: the five-phase lint lifecycle from docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md §4.

Holds the seven structural/content error types (§4.1) and the Discover→Attribute→Constrain→Inject→
Verify&Close lifecycle (§4.2). Discover itself happens in ``Validator`` (structural/content checks against
an in-flight ``CompiledUpdate``) and is handed in here as ``ValidationIssue`` objects; this module owns
Attribute→Constrain→Inject (turning a discovered issue into an actionable, then-injectable, constraint) and
Verify&Close (re-checking already-persisted pages later). Pure in-memory logic — no filesystem/network
access; YAML persistence to ``pipeline-state/error_book.yaml`` is a separate adapter
(``adapters.state.error_book_store.YamlErrorBookStore``), per the Ports & Adapters split (AGENTS.md §4).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from llm_yuki.domain.structural_checks import claim_is_complete, concept_is_complete, source_ref_well_formed
from llm_yuki.logging import get_logger
from llm_yuki.ports.writer import Writer

logger = get_logger(__name__)
"""Operational/console logging only — distinct from log.md (writer.append_log calls below), see logging.py."""

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

_STRUCTURAL_TYPES: frozenset[ErrorType] = frozenset(
    {"dangling_links", "incomplete_pages", "malformed_refs", "unseen_overwrite", "index_inconsistency"}
)

_ROOT_CAUSE_TEMPLATES: dict[ErrorType, str] = {
    "dangling_links": "A page referenced via a link/related_concepts/contradicted_by entry was never written.",
    "incomplete_pages": "A page is missing required content (claim_text/source_ref, or concept_title/summary).",
    "malformed_refs": "A source_ref does not match the expected reference shape (see structural_checks).",
    "unseen_overwrite": "CompileWikiPages modified a page outside this passage's SelectPages selection.",
    "index_inconsistency": "The same slug was used for two different core-type pages (Claim/Concept/Source).",
    "unsupported_facts": "A Claim's claim_text is not grounded in the source_ref it cites.",
    "cross_page_contradictions": "Related pages assert mutually inconsistent facts.",
}
"""Attribute-phase root-cause templates, one per error type (proposal ARCHITECTURE.md §4.1/§4.2).

Deterministic and type-level, not instance-specific — a reasonable baseline for structural errors, whose
cause *is* the type. The two content error types (``unsupported_facts``/``cross_page_contradictions``) would
benefit from an LLM-driven, instance-specific root-cause analysis; that refinement is future work (see
``TODO.md`` §B) and out of scope for this deterministic implementation.
"""


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
    """In-memory Error Book (``ℬ`` in Algorithm 1).

    The four methods below correspond 1:1 to Algorithm 1's ``UpdateErrorBook``/``ActiveConstraints``/
    ``PeriodicFixDue``/``VerifyAndClose`` (proposal ARCHITECTURE.md §2.2.4, §4.2).
    """

    entries: list[ErrorBookEntry] = Field(default_factory=list)
    periodic_fix_interval: int = Field(
        default=5,
        description=(
            "Batch cadence N for LLMPeriodicFix (proposal §4.3). Left undecided at the architecture level, "
            "deferred to scaffolding-stage tuning; 5 is a starting default, not a validated threshold."
        ),
    )
    _last_periodic_fix_batch: int | None = None

    def update_error_book(
        self, issues: list[ValidationIssue], batch_id: int, writer: Writer
    ) -> list[ErrorBookEntry]:
        """Algorithm 1 line 8: ``ℬ ← UpdateErrorBook(ℬ, E)`` — Attribute + Constrain (Discover already ran).

        Deduplicates against existing *open* entries of the same ``error_type``/``phenomenon``: a repeat
        occurrence merges its ``affected_refs`` into the existing entry rather than creating a new one, so
        the same recurring mistake doesn't flood the book with duplicate rows. Writes one ``log.md`` audit
        line per issue via ``writer.append_log`` (proposal ARCHITECTURE.md §4.4, "每次 UpdateErrorBook/
        VerifyAndClose 都要同步寫一筆事件進 log.md").
        """
        touched: list[ErrorBookEntry] = []
        for issue in issues:
            existing = self._find_open_entry(issue.error_type, issue.phenomenon)
            if existing is not None:
                for ref in issue.affected_refs:
                    if ref not in existing.affected_refs:
                        existing.affected_refs.append(ref)
                touched.append(existing)
                writer.append_log(
                    f"batch {batch_id}: UpdateErrorBook recurrence of {existing.error_type} entry "
                    f"{existing.id} — {existing.phenomenon} (refs: {', '.join(issue.affected_refs) or 'none'})"
                )
                logger.info("batch %d: recurrence of %s entry %s", batch_id, existing.error_type, existing.id)
                continue

            root_cause = _ROOT_CAUSE_TEMPLATES[issue.error_type]
            entry = ErrorBookEntry(
                id=uuid.uuid4().hex,
                error_type=issue.error_type,
                phenomenon=issue.phenomenon,
                affected_refs=list(issue.affected_refs),
                root_cause=root_cause,
                constraint_rule=f"Avoid recreating this issue: {root_cause}",
                discovered_at_batch=batch_id,
            )
            self.entries.append(entry)
            touched.append(entry)
            writer.append_log(
                f"batch {batch_id}: UpdateErrorBook opened {entry.error_type} entry {entry.id} — "
                f"{entry.phenomenon} (refs: {', '.join(entry.affected_refs) or 'none'})"
            )
            logger.warning("batch %d: opened %s entry %s — %s", batch_id, entry.error_type, entry.id, entry.phenomenon)
        return touched

    def active_constraints(self) -> list[str]:
        """Algorithm 1 line 9: ``C ← ActiveConstraints(ℬ)`` — Inject: open entries' constraint_rule text."""
        return [entry.constraint_rule for entry in self.entries if entry.status == "open" and entry.constraint_rule]

    def periodic_fix_due(self, batch_id: int) -> bool:
        """Algorithm 1 line 14: whether ``LLMPeriodicFix`` should run for this batch (cadence N, §4.3).

        Fires every ``periodic_fix_interval`` batches, and never twice for the same ``batch_id`` (guards
        against a batch being re-processed, e.g. after a retry).
        """
        if self.periodic_fix_interval <= 0:
            return False
        due = batch_id > 0 and batch_id % self.periodic_fix_interval == 0
        return due and batch_id != self._last_periodic_fix_batch

    def verify_and_close(self, writer: Writer, batch_id: int) -> list[ErrorBookEntry]:
        """Algorithm 1 line 16: ``ℬ ← VerifyAndClose(ℬ, W)`` — re-check open entries, close resolved ones.

        Deterministically re-verifiable here: ``dangling_links`` (does the target now exist),
        ``incomplete_pages``/``malformed_refs`` (does the page now pass the same check). ``unseen_overwrite``
        and ``index_inconsistency`` are structural-validate-time-only conditions with nothing meaningful to
        re-check post-write, so entries of those types are left open for manual/other resolution. The two
        content error types need an LLM-driven re-verification this deterministic pass can't perform (see
        ``TODO.md`` §B) — also left open.
        """
        self._last_periodic_fix_batch = batch_id
        closed: list[ErrorBookEntry] = []
        for entry in self.entries:
            if entry.status != "open":
                continue
            if self._is_resolved(entry, writer):
                entry.status = "closed"
                entry.closed_at_batch = batch_id
                entry.verification_method = f"re-checked at batch {batch_id} against current Writer state"
                closed.append(entry)
                writer.append_log(
                    f"batch {batch_id}: VerifyAndClose closed {entry.error_type} entry {entry.id} — "
                    f"{entry.phenomenon}"
                )
                logger.info("batch %d: closed %s entry %s", batch_id, entry.error_type, entry.id)
        return closed

    def _find_open_entry(self, error_type: ErrorType, phenomenon: str) -> ErrorBookEntry | None:
        for entry in self.entries:
            if entry.status == "open" and entry.error_type == error_type and entry.phenomenon == phenomenon:
                return entry
        return None

    @staticmethod
    def _is_resolved(entry: ErrorBookEntry, writer: Writer) -> bool:
        if entry.error_type == "dangling_links":
            existing_slugs = set(writer.list_pages())
            return all(ref in existing_slugs for ref in entry.affected_refs)
        if entry.error_type == "incomplete_pages":
            return all(ErrorBook._page_now_complete(writer, ref) for ref in entry.affected_refs)
        if entry.error_type == "malformed_refs":
            return all(ErrorBook._source_ref_now_well_formed(writer, ref) for ref in entry.affected_refs)
        return False

    @staticmethod
    def _page_now_complete(writer: Writer, slug: str) -> bool:
        claim = writer.read_claim(slug)
        if claim is not None:
            return claim_is_complete(claim)
        concept = writer.read_concept(slug)
        return concept is not None and concept_is_complete(concept)

    @staticmethod
    def _source_ref_now_well_formed(writer: Writer, slug: str) -> bool:
        claim = writer.read_claim(slug)
        return claim is not None and source_ref_well_formed(claim.source_ref)
