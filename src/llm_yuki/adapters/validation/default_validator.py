"""Concrete ``Validator``: deterministic ``structural_validate`` + LLM-backed ``content_validate``.

Both live in one class because ``Validator`` (domain/pipeline.py) declares both as abstract methods — a
concrete implementation must provide both, even though only ``content_validate`` needs the LLM client
(proposal ARCHITECTURE.md §2.2.3). ``structural_validate`` covers the five structural error types from §4.1;
``content_validate`` covers the two content types via ``llm_client``.
"""

from __future__ import annotations

from llm_yuki.domain.error_book import ValidationIssue
from llm_yuki.domain.pipeline import CompiledUpdate, Validator
from llm_yuki.domain.structural_checks import (
    claim_is_complete,
    concept_is_complete,
    resolve_slug,
    source_ref_well_formed,
)
from llm_yuki.ports.writer import Writer


class DefaultValidator(Validator):
    """``llm_client=None`` disables ``content_validate`` (raises) — structural checks work standalone."""

    def __init__(self, llm_client: object | None = None) -> None:
        self._llm_client = llm_client

    def structural_validate(self, update: CompiledUpdate, selected: list[str], writer: Writer) -> list[ValidationIssue]:
        """The five structural checks from proposal ARCHITECTURE.md §4.1, run against ``update`` and ``writer``."""
        issues: list[ValidationIssue] = []
        issues.extend(self._check_dangling_links(update, writer))
        issues.extend(self._check_incomplete_pages(update))
        issues.extend(self._check_malformed_refs(update))
        issues.extend(self._check_unseen_overwrite(update, selected, writer))
        issues.extend(self._check_index_inconsistency(update, writer))
        return issues

    def content_validate(self, update: CompiledUpdate, writer: Writer, batch_id: int) -> list[ValidationIssue]:
        """LLM-based checks: unsupported facts, cross-page contradictions (proposal §4.1 #6-7)."""
        del batch_id  # unused until this method is implemented (TODO.md §B)
        if self._llm_client is None:
            raise RuntimeError(
                "DefaultValidator.content_validate requires an llm_client (see ARCHITECTURE.md §2.1, TODO.md §B)"
            )
        raise NotImplementedError  # filled in alongside the LLM client wiring (TODO.md §B)

    # -- Dangling Links (§4.1 #1) --------------------------------------------------

    @staticmethod
    def _check_dangling_links(update: CompiledUpdate, writer: Writer) -> list[ValidationIssue]:
        known_slugs = {c.slug for c in update.claims} | {c.slug for c in update.concepts} | set(writer.list_pages())
        issues: list[ValidationIssue] = []
        for claim in update.claims:
            for target in claim.related_concepts:
                if not resolve_slug(target, known_slugs):
                    issues.append(
                        ValidationIssue(
                            error_type="dangling_links",
                            phenomenon=f"{claim.slug}.related_concepts references missing page {target!r}",
                            affected_refs=[target],
                        )
                    )
            for ref in claim.contradicted_by:
                if not resolve_slug(ref.slug, known_slugs):
                    issues.append(
                        ValidationIssue(
                            error_type="dangling_links",
                            phenomenon=f"{claim.slug}.contradicted_by references missing page {ref.slug!r}",
                            affected_refs=[ref.slug],
                        )
                    )
        for concept in update.concepts:
            for target in concept.related_pages:
                if not resolve_slug(target, known_slugs):
                    issues.append(
                        ValidationIssue(
                            error_type="dangling_links",
                            phenomenon=f"{concept.slug}.related_pages references missing page {target!r}",
                            affected_refs=[target],
                        )
                    )
        return issues

    # -- Incomplete Pages (§4.1 #2) -------------------------------------------------

    @staticmethod
    def _check_incomplete_pages(update: CompiledUpdate) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for claim in update.claims:
            if not claim_is_complete(claim):
                issues.append(
                    ValidationIssue(
                        error_type="incomplete_pages",
                        phenomenon=f"Claim {claim.slug!r} is missing claim_text or source_ref",
                        affected_refs=[claim.slug],
                    )
                )
        for concept in update.concepts:
            if not concept_is_complete(concept):
                issues.append(
                    ValidationIssue(
                        error_type="incomplete_pages",
                        phenomenon=f"Concept {concept.slug!r} is missing concept_title or summary",
                        affected_refs=[concept.slug],
                    )
                )
        return issues

    # -- Malformed Refs (§4.1 #3) ----------------------------------------------------

    @staticmethod
    def _check_malformed_refs(update: CompiledUpdate) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for claim in update.claims:
            if not source_ref_well_formed(claim.source_ref):
                issues.append(
                    ValidationIssue(
                        error_type="malformed_refs",
                        phenomenon=f"Claim {claim.slug!r} has a malformed source_ref: {claim.source_ref!r}",
                        affected_refs=[claim.slug],
                    )
                )
        return issues

    # -- Unseen Overwrite (§4.1 #4) --------------------------------------------------

    @staticmethod
    def _check_unseen_overwrite(update: CompiledUpdate, selected: list[str], writer: Writer) -> list[ValidationIssue]:
        selected_set = set(selected)
        existing_slugs = set(writer.list_pages())
        touched_slugs = [c.slug for c in update.claims] + [c.slug for c in update.concepts]
        issues: list[ValidationIssue] = []
        for slug in touched_slugs:
            if slug in existing_slugs and slug not in selected_set:
                issues.append(
                    ValidationIssue(
                        error_type="unseen_overwrite",
                        phenomenon=f"Compiled update modifies existing page {slug!r}, outside SelectPages",
                        affected_refs=[slug],
                    )
                )
        return issues

    # -- Index Inconsistency (§4.1 #5) -----------------------------------------------

    @staticmethod
    def _check_index_inconsistency(update: CompiledUpdate, writer: Writer) -> list[ValidationIssue]:
        """Scoped to same-slug-different-type collisions (Claim vs Concept) — see module docstring."""
        issues: list[ValidationIssue] = []
        claim_slugs = {c.slug for c in update.claims}
        concept_slugs = {c.slug for c in update.concepts}

        for slug in claim_slugs & concept_slugs:
            issues.append(
                ValidationIssue(
                    error_type="index_inconsistency",
                    phenomenon=f"Slug {slug!r} used for both a Claim and a Concept in the same update",
                    affected_refs=[slug],
                )
            )
        for claim in update.claims:
            if writer.read_concept(claim.slug) is not None:
                issues.append(_type_collision_issue(claim.slug, "Claim", "Concept"))
        for concept in update.concepts:
            if writer.read_claim(concept.slug) is not None:
                issues.append(_type_collision_issue(concept.slug, "Concept", "Claim"))
        return issues


def _type_collision_issue(slug: str, new_type: str, existing_type: str) -> ValidationIssue:
    return ValidationIssue(
        error_type="index_inconsistency",
        phenomenon=f"Slug {slug!r} compiled as a {new_type} but already exists as a {existing_type}",
        affected_refs=[slug],
    )
