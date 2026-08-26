"""Concrete ``Validator``: deterministic ``structural_validate`` + LLM-backed ``content_validate``.

Both live in one class because ``Validator`` (domain/pipeline.py) declares both as abstract methods — a
concrete implementation must provide both, even though only ``content_validate`` needs the LLM client
(proposal ARCHITECTURE.md §2.2.3). ``structural_validate`` covers the five structural error types from §4.1;
``content_validate`` covers the two content types via ``llm_client``, one call per compiled passage covering
every candidate claim at once (cost per D19).
"""

from __future__ import annotations

import time

from pydantic import ValidationError

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import OpenAICompatibleClient
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.adapters.llm.json_utils import parse_json_object
from llm_yuki.domain.entities import Claim
from llm_yuki.domain.error_book import ValidationIssue
from llm_yuki.domain.pipeline import CompiledUpdate, Validator
from llm_yuki.domain.structural_checks import (
    claim_is_complete,
    concept_is_complete,
    resolve_slug,
    source_ref_well_formed,
)
from llm_yuki.ports.writer import Writer

_CONTENT_VALIDATE_SYSTEM_PROMPT = """\
You are the ContentValidate step of a wiki-compilation pipeline lint pass. For each candidate Claim, given \
the source passage it was extracted from and a list of sibling claims already in the wiki (claims that \
share a related Concept, or that this claim's extractor already flagged as a possible contradiction), check \
for two kinds of genuine content error:

1. unsupported_facts: the claim_text is not actually grounded in / supported by the passage — this matters \
most when provenance_state is "extracted" (claimed to be taken directly from the source).
2. cross_page_contradictions: the claim_text genuinely conflicts with one of its listed sibling claims \
(e.g. contradicting dates, values, or relationships) — not merely related or overlapping topics.

Only report an issue you are confident is genuine; do not flag something as unsupported or contradictory \
just because it is imprecise or you are unsure. Respond with a JSON object:
{"issues": [{"error_type": "unsupported_facts"|"cross_page_contradictions", "phenomenon": "...", \
"affected_refs": ["claim-slug", ...]}]}
Return {"issues": []} if there are no genuine issues."""


class DefaultValidator(Validator):
    """``llm_client=None`` disables ``content_validate`` (raises) — structural checks work standalone."""

    def __init__(
        self, llm_client: OpenAICompatibleClient | None = None, cost_ledger: JsonlCostLedger | None = None
    ) -> None:
        self._llm_client = llm_client
        self._cost_ledger = cost_ledger

    def structural_validate(self, update: CompiledUpdate, selected: list[str], writer: Writer) -> list[ValidationIssue]:
        """The five structural checks from proposal ARCHITECTURE.md §4.1, run against ``update`` and ``writer``."""
        issues: list[ValidationIssue] = []
        issues.extend(self._check_dangling_links(update, writer))
        issues.extend(self._check_incomplete_pages(update))
        issues.extend(self._check_malformed_refs(update))
        issues.extend(self._check_unseen_overwrite(update, selected, writer))
        issues.extend(self._check_index_inconsistency(update, writer))
        return issues

    def content_validate(
        self, update: CompiledUpdate, passage: str, writer: Writer, batch_id: int
    ) -> list[ValidationIssue]:
        """LLM-based checks: unsupported facts, cross-page contradictions (proposal §4.1 #6-7)."""
        if self._llm_client is None or self._cost_ledger is None:
            raise RuntimeError(
                "DefaultValidator.content_validate requires llm_client and cost_ledger "
                "(see ARCHITECTURE.md §2.1, TODO.md §B)"
            )
        if not update.claims:
            return []

        claims_text = "\n\n".join(self._describe_claim(claim, update, writer) for claim in update.claims)
        user_prompt = f"Passage:\n{passage}\n\nCandidate claims:\n{claims_text}"

        start = time.monotonic()
        response = self._llm_client.complete(
            [
                {"role": "system", "content": _CONTENT_VALIDATE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format_json=True,
        )
        wall_clock_ms = (time.monotonic() - start) * 1000
        self._cost_ledger.record(
            "Validator.ContentValidate",
            batch_id,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            wall_clock_ms=wall_clock_ms,
        )

        payload = parse_json_object(response.content, context="Validator.ContentValidate")
        raw_issues = payload.get("issues", [])
        if not isinstance(raw_issues, list):
            raise LLMOutputError(f"Validator.ContentValidate: 'issues' must be a list, got {raw_issues!r}")
        try:
            return [ValidationIssue.model_validate(item) for item in raw_issues]
        except ValidationError as exc:
            raise LLMOutputError(
                f"Validator.ContentValidate: response did not match ValidationIssue schema: {exc}"
            ) from exc

    # -- content_validate helpers -----------------------------------------------------

    @staticmethod
    def _describe_claim(claim: Claim, update: CompiledUpdate, writer: Writer) -> str:
        siblings = DefaultValidator._gather_siblings(claim, update, writer)
        siblings_text = "(none)" if not siblings else "\n".join(f"  - {s.slug}: {s.claim_text}" for s in siblings)
        return (
            f"- slug: {claim.slug}\n"
            f"  claim_text: {claim.claim_text}\n"
            f"  provenance_state: {claim.provenance_state}\n"
            f"  sibling claims:\n{siblings_text}"
        )

    @staticmethod
    def _gather_siblings(claim: Claim, update: CompiledUpdate, writer: Writer, limit: int = 8) -> list[Claim]:
        """Sibling claims worth cross-checking: contradicted_by candidates + concept.key_facts co-members."""
        sibling_slugs: list[str] = []
        for ref in claim.contradicted_by:
            if ref.slug not in sibling_slugs:
                sibling_slugs.append(ref.slug)
        for concept_slug in claim.related_concepts:
            concept = writer.read_concept(concept_slug)
            if concept is None:
                continue
            for sibling_slug in concept.key_facts:
                if sibling_slug != claim.slug and sibling_slug not in sibling_slugs:
                    sibling_slugs.append(sibling_slug)

        siblings: list[Claim] = []
        for slug in sibling_slugs[:limit]:
            sibling = writer.read_claim(slug) or next((c for c in update.claims if c.slug == slug), None)
            if sibling is not None:
                siblings.append(sibling)
        return siblings

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
