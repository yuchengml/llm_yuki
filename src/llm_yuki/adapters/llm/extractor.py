"""LLM-backed ``Extractor``: ``SelectPages`` + ``CompileWikiPages`` (proposal ARCHITECTURE.md §2.2.1).

Domain-agnostic by construction (AGENTS.md §4): the prompts below only ever talk about passages, existing
pages, and constraints — never anything corpus-specific. Per-corpus segmentation/type extensions are a future
skill's job (proposal README.md D3), not this class's.
"""

from __future__ import annotations

import time

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import OpenAICompatibleClient
from llm_yuki.adapters.llm.compiled_update_parsing import parse_compiled_update
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.adapters.llm.json_utils import parse_json_object
from llm_yuki.domain.pipeline import CompiledUpdate, Extractor
from llm_yuki.ports.writer import Writer

_SELECT_PAGES_SYSTEM_PROMPT = """\
You are the SelectPages step of a domain-agnostic wiki-compilation pipeline. Given a source passage and a \
list of existing pages (slug plus a short description), return the slugs of existing pages that this \
passage is relevant to — pages it might add facts to, update, or contradict. Respond with a JSON object: \
{"selected": ["slug-1", "slug-2", ...]}. Return an empty list if none are relevant. Only return slugs from \
the provided list — never invent one."""

_COMPILE_WIKI_PAGES_SYSTEM_PROMPT = """\
You are the CompileWikiPages step of a domain-agnostic wiki-compilation pipeline. Given a source passage, \
the content of existing pages selected as relevant, and a list of active constraints (rules from previously \
discovered pipeline errors — follow them to avoid repeating past mistakes), extract candidate Claim and \
Concept pages as JSON, matching this schema exactly:

{
  "claims": [
    {"slug": "...", "claim_text": "...", "description": "...", "source_ref": "...", "confidence": 0.0-1.0,
     "provenance_state": "extracted"|"merged"|"inferred"|"ambiguous",
     "related_concepts": ["slug", ...], "contradicted_by": [{"slug": "...", "reason": "..."}]}
  ],
  "concepts": [
    {"slug": "...", "concept_title": "...", "aliases": ["...", ...], "tags": ["...", ...],
     "summary": "...", "description": "...", "related_pages": ["slug", ...], "related_sources": ["...", ...]}
  ]
}

Rules:
- claim_text is a structured assertion, not a verbatim copy of the passage.
- description is always a short one-sentence summary for index listings, regardless of how long/structured \
claim_text or summary is.
- concept summary is not limited to one paragraph: use your judgment — plain prose for a simple Concept, or \
markdown "## " subsections (e.g. "## History", "## Usage") when the topic has multiple distinct facets. \
Don't force structure onto a Concept that doesn't need it.
- source_ref must point into this passage (e.g. a document id, optionally "#locator").
- Do not include a "key_facts" field on concepts — it is maintained separately by the pipeline, not by you.
- Only reference related_concepts/contradicted_by/related_pages slugs that are either defined in this same \
response or already exist among the provided pages — never invent a slug that resolves nowhere.
- Return {"claims": [], "concepts": []} if the passage yields nothing new."""


class LLMExtractor(Extractor):
    """Calls ``llm_client`` for both ``select_pages`` and ``compile_wiki_pages``, recording cost via ``cost_ledger``."""

    def __init__(self, llm_client: OpenAICompatibleClient, cost_ledger: JsonlCostLedger) -> None:
        self._llm_client = llm_client
        self._cost_ledger = cost_ledger

    def select_pages(self, passage: str, writer: Writer, batch_id: int) -> list[str]:
        """``S ← SelectPages(x, I)``: ask the LLM which existing pages this passage is relevant to."""
        known_slugs = writer.list_pages()
        if not known_slugs:
            return []

        page_index = "\n".join(f"- {slug}: {_describe_page(writer, slug)}" for slug in known_slugs)
        user_prompt = f"Passage:\n{passage}\n\nExisting pages:\n{page_index}"

        content = self._call_llm(
            stage="Extractor.SelectPages",
            batch_id=batch_id,
            system_prompt=_SELECT_PAGES_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        payload = parse_json_object(content, context="Extractor.SelectPages")
        selected = payload.get("selected", [])
        if not isinstance(selected, list) or not all(isinstance(slug, str) for slug in selected):
            raise LLMOutputError(f"Extractor.SelectPages: 'selected' must be a list of strings, got {selected!r}")

        known_set = set(known_slugs)
        return [slug for slug in selected if slug in known_set]

    def compile_wiki_pages(
        self, passage: str, selected: list[str], constraints: list[str], batch_id: int
    ) -> CompiledUpdate:
        """``U ← CompileWikiPages(x, S, C)``: ask the LLM for candidate Claim/Concept pages."""
        constraints_text = "\n".join(f"- {c}" for c in constraints) if constraints else "(none)"
        selected_text = "(none)" if not selected else "\n".join(f"- {slug}" for slug in selected)
        user_prompt = (
            f"Passage:\n{passage}\n\n"
            f"Selected existing pages:\n{selected_text}\n\n"
            f"Active constraints:\n{constraints_text}"
        )

        content = self._call_llm(
            stage="Extractor.CompileWikiPages",
            batch_id=batch_id,
            system_prompt=_COMPILE_WIKI_PAGES_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        payload = parse_json_object(content, context="Extractor.CompileWikiPages")
        return parse_compiled_update(payload, context="Extractor.CompileWikiPages")

    def _call_llm(self, *, stage: str, batch_id: int, system_prompt: str, user_prompt: str) -> str:
        start = time.monotonic()
        response = self._llm_client.complete(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format_json=True,
        )
        wall_clock_ms = (time.monotonic() - start) * 1000
        self._cost_ledger.record(
            stage, batch_id, tokens_in=response.tokens_in, tokens_out=response.tokens_out, wall_clock_ms=wall_clock_ms
        )
        return response.content


def _describe_page(writer: Writer, slug: str) -> str:
    concept = writer.read_concept(slug)
    if concept is not None:
        return concept.summary or concept.concept_title
    claim = writer.read_claim(slug)
    if claim is not None:
        return claim.claim_text
    return "(no description available)"
