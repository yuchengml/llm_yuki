"""Deterministic ``Merger``: dedupe candidates by slug, decide final content (proposal ARCHITECTURE.md §2.2.2).

Does not persist — that is the ``Writer``'s job (2.2.2, "不負責實際持久化"). Dedup is slug-exact: two
candidates (or a candidate and an already-persisted page) merge only when they share a ``slug``. Semantic
dedup — two candidates describing the same thing under different slugs — needs fuzzy/embedding matching or
an LLM judgment call and is out of scope for this deterministic baseline (see ``TODO.md`` §B).
"""

from __future__ import annotations

from llm_yuki.domain.entities import Claim, Concept, ContradictionRef
from llm_yuki.domain.pipeline import CompiledUpdate, Merger
from llm_yuki.ports.writer import Writer


class DefaultMerger(Merger):
    """Slug-exact dedup: merges same-slug candidates within a batch, then against already-persisted pages."""

    def merge(self, update: CompiledUpdate, writer: Writer) -> CompiledUpdate:
        """Resolve ``is_new`` / merge against existing pages before ``ApplyUpdates``."""
        return CompiledUpdate(
            claims=self._merge_claims(update.claims, writer),
            concepts=self._merge_concepts(update.concepts, writer),
        )

    def _merge_claims(self, claims: list[Claim], writer: Writer) -> list[Claim]:
        by_slug: dict[str, Claim] = {}
        for claim in claims:
            by_slug[claim.slug] = self._merge_claim_pair(by_slug[claim.slug], claim) if claim.slug in by_slug else claim

        merged: list[Claim] = []
        for slug, claim in by_slug.items():
            existing = writer.read_claim(slug)
            merged.append(self._merge_claim_pair(existing, claim) if existing is not None else claim)
        return merged

    def _merge_concepts(self, concepts: list[Concept], writer: Writer) -> list[Concept]:
        by_slug: dict[str, Concept] = {}
        for concept in concepts:
            by_slug[concept.slug] = (
                self._merge_concept_pair(by_slug[concept.slug], concept) if concept.slug in by_slug else concept
            )

        merged: list[Concept] = []
        for slug, concept in by_slug.items():
            existing = writer.read_concept(slug)
            merged.append(self._merge_concept_pair(existing, concept) if existing is not None else concept)
        return merged

    @staticmethod
    def _merge_claim_pair(base: Claim, new: Claim) -> Claim:
        return base.model_copy(
            update={
                "claim_text": new.claim_text or base.claim_text,
                "source_ref": new.source_ref or base.source_ref,
                "confidence": max(base.confidence, new.confidence),
                "provenance_state": "merged",
                "related_concepts": _union(base.related_concepts, new.related_concepts),
                "contradicted_by": _union_contradictions(base.contradicted_by, new.contradicted_by),
            }
        )

    @staticmethod
    def _merge_concept_pair(base: Concept, new: Concept) -> Concept:
        return base.model_copy(
            update={
                "concept_title": new.concept_title or base.concept_title,
                "aliases": _union(base.aliases, new.aliases),
                "tags": _union(base.tags, new.tags),
                "summary": new.summary or base.summary,
                "key_facts": _union(base.key_facts, new.key_facts),
                "related_pages": _union(base.related_pages, new.related_pages),
                "related_sources": _union(base.related_sources, new.related_sources),
            }
        )


def _union(a: list[str], b: list[str]) -> list[str]:
    """Order-preserving union, first occurrence wins position."""
    result = list(a)
    result.extend(item for item in b if item not in result)
    return result


def _union_contradictions(a: list[ContradictionRef], b: list[ContradictionRef]) -> list[ContradictionRef]:
    """Order-preserving union of ContradictionRef, deduped by ``slug`` (first reason wins)."""
    result = list(a)
    known_slugs = {ref.slug for ref in result}
    for ref in b:
        if ref.slug not in known_slugs:
            result.append(ref)
            known_slugs.add(ref.slug)
    return result
