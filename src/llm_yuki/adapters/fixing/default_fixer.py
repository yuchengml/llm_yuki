"""Concrete ``Fixer``: deterministic ``code_auto_fix`` + LLM-backed ``llm_periodic_fix``.

``code_auto_fix`` only ever takes safe, conservative actions on structural issues (Algorithm 1 line 10,
proposal ARCHITECTURE.md §4.1): strip a dangling reference rather than invent a target; sanitize an obviously
fixable ``source_ref`` (stray whitespace) rather than guess the right value; drop a candidate that would
overwrite a page outside this passage's selection, or collide slugs across types, rather than corrupt the
namespace. Anything it can't safely resolve is left for ``ErrorBook``/``ActiveConstraints`` to carry forward
as a constraint for the next round — ``code_auto_fix`` never invents content.
"""

from __future__ import annotations

import re

from llm_yuki.domain.entities import Claim, Concept
from llm_yuki.domain.error_book import ErrorBook, ValidationIssue
from llm_yuki.domain.pipeline import CompiledUpdate, Fixer
from llm_yuki.domain.structural_checks import source_ref_well_formed
from llm_yuki.ports.writer import Writer

_DROP_TYPES = frozenset({"unseen_overwrite", "index_inconsistency"})
_WHITESPACE = re.compile(r"\s+")


class DefaultFixer(Fixer):
    """``llm_client=None`` disables ``llm_periodic_fix`` (raises) — ``code_auto_fix`` works standalone."""

    def __init__(self, llm_client: object | None = None) -> None:
        self._llm_client = llm_client

    def code_auto_fix(self, update: CompiledUpdate, structural_issues: list[ValidationIssue]) -> CompiledUpdate:
        """``U ← CodeAutoFix(U, E_s)``: deterministic repair of structural issues, applied immediately."""
        dropped = _slugs_of_type(structural_issues, _DROP_TYPES)
        dangling_targets = _slugs_of_type(structural_issues, {"dangling_links"})
        malformed_slugs = _slugs_of_type(structural_issues, {"malformed_refs"})

        claims = [
            _sanitize_claim(claim, dangling_targets, malformed_slugs)
            for claim in update.claims
            if claim.slug not in dropped
        ]
        concepts = [
            _sanitize_concept(concept, dangling_targets) for concept in update.concepts if concept.slug not in dropped
        ]
        return CompiledUpdate(claims=claims, concepts=concepts)

    def llm_periodic_fix(self, error_book: ErrorBook, writer: Writer, batch_id: int) -> None:
        """``W ← LLMPeriodicFix(W, ℬ)``: LLM-driven repair of content issues, run every N batches (§4.3)."""
        del batch_id  # unused until this method is implemented (TODO.md §B)
        if self._llm_client is None:
            raise RuntimeError(
                "DefaultFixer.llm_periodic_fix requires an llm_client (see ARCHITECTURE.md §2.1, TODO.md §B)"
            )
        raise NotImplementedError  # filled in alongside the LLM client wiring (TODO.md §B)


def _slugs_of_type(issues: list[ValidationIssue], error_types: frozenset[str] | set[str]) -> set[str]:
    return {ref for issue in issues if issue.error_type in error_types for ref in issue.affected_refs}


def _normalize_source_ref(source_ref: str) -> str:
    """Best-effort sanitize: trim, collapse internal whitespace to ``-``. Not a full grammar fix."""
    return _WHITESPACE.sub("-", source_ref.strip())


def _sanitize_claim(claim: Claim, dangling_targets: set[str], malformed_slugs: set[str]) -> Claim:
    related_concepts = [slug for slug in claim.related_concepts if slug not in dangling_targets]
    contradicted_by = [ref for ref in claim.contradicted_by if ref.slug not in dangling_targets]

    source_ref = claim.source_ref
    if claim.slug in malformed_slugs:
        candidate = _normalize_source_ref(claim.source_ref)
        if source_ref_well_formed(candidate):
            source_ref = candidate

    if (
        related_concepts == claim.related_concepts
        and contradicted_by == claim.contradicted_by
        and source_ref == claim.source_ref
    ):
        return claim
    return claim.model_copy(
        update={"related_concepts": related_concepts, "contradicted_by": contradicted_by, "source_ref": source_ref}
    )


def _sanitize_concept(concept: Concept, dangling_targets: set[str]) -> Concept:
    related_pages = [slug for slug in concept.related_pages if slug not in dangling_targets]
    if related_pages == concept.related_pages:
        return concept
    return concept.model_copy(update={"related_pages": related_pages})
