"""Shared core types: ``Claim`` and ``Concept``.

Field definitions follow docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md §1.2/§1.3 (sourced from decision D9 and
its 2026-08-25 follow-up). These are the two OKF typed-frontmatter types every domain shares; a per-corpus
skill may add its own extension types on top (e.g. ``sci-paper:Paper``), but the core pipeline only ever
needs to understand ``Claim``/``Concept``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProvenanceState = Literal["extracted", "merged", "inferred", "ambiguous"]
"""How a Claim came to exist — see D9 supplementary decision for how this feeds root-cause attribution."""


class ContradictionRef(BaseModel):
    """One entry of ``Claim.contradicted_by``: a candidate conflict with another Claim.

    This is a lint *candidate/accelerator*, not an authoritative judgment — the Validator must still run its
    own full contradiction sweep (proposal ARCHITECTURE.md §1.2, "⚠️ 這個欄位是 lint 的候選線索/加速器").
    """

    slug: str
    reason: str


class Claim(BaseModel):
    """A sourced, extracted/inferred assertion — the smallest unit the contradiction-detection loop operates on."""

    slug: str = Field(description="Unique page identifier, used by related_concepts/contradicted_by/key_facts.")
    claim_text: str = Field(description="Structured assertion text — not a verbatim copy of the source passage.")
    source_ref: str = Field(description="Pointer into the Raw Source (document/passage position, or image link).")
    confidence: float = Field(ge=0.0, le=1.0, description="Factual-certainty score.")
    provenance_state: ProvenanceState
    related_concepts: list[str] = Field(default_factory=list, description="Slugs of linked Concept pages.")
    contradicted_by: list[ContradictionRef] = Field(default_factory=list)


class Concept(BaseModel):
    """A general topic/entity page — the fallback type when no more specific type applies."""

    slug: str = Field(description="Unique page identifier.")
    concept_title: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    summary: str = Field(description="LLM-generated one-paragraph summary.")
    key_facts: list[str] = Field(
        default_factory=list,
        description="Slugs of related Claims — a backlink maintained incrementally by the Writer, not the LLM.",
    )
    related_pages: list[str] = Field(default_factory=list, description="Wikilinks to other Concept pages.")
    related_sources: list[str] = Field(default_factory=list, description="Source/provenance digest links.")
