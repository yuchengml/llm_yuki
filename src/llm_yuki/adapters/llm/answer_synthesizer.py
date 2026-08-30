"""LLM-backed ``AnswerSynthesizer`` (proposal ARCHITECTURE.md §8.6): question + pages → cited answer.

Same shape as ``adapters/llm/extractor.py::LLMExtractor``: a thin prompt-and-parse wrapper around
``OpenAICompatibleClient``, recording cost via ``JsonlCostLedger``. Domain-agnostic by construction — the
prompt only ever talks about "pages" and "a question," never anything corpus-specific.
"""

from __future__ import annotations

import time

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import OpenAICompatibleClient
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.adapters.llm.json_utils import parse_json_object
from llm_yuki.domain.query import AnswerSynthesizer, PageRecord, SynthesizedAnswer

_SYNTHESIZE_SYSTEM_PROMPT = """\
You are the answer-synthesis step of a domain-agnostic wiki-query pipeline. Given a question and a list of \
wiki pages (slug, title, and content), write a grounded answer using only the provided pages — do not invent \
facts the pages don't support. If the pages don't contain enough information to answer, say so plainly \
rather than guessing. Respond with a JSON object: {"answer": "...", "cited_slugs": ["slug-1", ...]}. \
cited_slugs must list every page slug your answer actually draws on — never a slug that isn't in the \
provided list, and never an empty list if you used any page's content."""


class LLMAnswerSynthesizer(AnswerSynthesizer):
    """Calls ``llm_client`` to synthesize a cited answer, recording cost via ``cost_ledger``."""

    def __init__(self, llm_client: OpenAICompatibleClient, cost_ledger: JsonlCostLedger) -> None:
        self._llm_client = llm_client
        self._cost_ledger = cost_ledger

    def synthesize(self, question: str, pages: list[PageRecord], batch_id: int) -> SynthesizedAnswer:
        """Ask the LLM to answer ``question`` grounded in ``pages``, with mandatory citations.

        A hallucinated slug in the LLM's ``cited_slugs`` is filtered out, not treated as a fatal error — same
        defensive-filtering precedent as ``LLMExtractor.select_pages`` (proposal §2.2.1).
        """
        known_slugs = {page.slug for page in pages}
        if not pages:
            return SynthesizedAnswer(
                answer="No wiki pages were found for this question — nothing to answer from.", cited_slugs=[]
            )

        page_index = "\n\n".join(f"### {page.slug} ({page.title})\n{page.content}" for page in pages)
        user_prompt = f"Question:\n{question}\n\nPages:\n{page_index}"

        content = self._call_llm(
            stage="AnswerSynthesizer.Synthesize",
            batch_id=batch_id,
            system_prompt=_SYNTHESIZE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        payload = parse_json_object(content, context="AnswerSynthesizer.Synthesize")
        answer = payload.get("answer")
        cited_slugs = payload.get("cited_slugs", [])
        if not isinstance(answer, str):
            raise LLMOutputError(f"AnswerSynthesizer.Synthesize: 'answer' must be a string, got {answer!r}")
        if not isinstance(cited_slugs, list) or not all(isinstance(slug, str) for slug in cited_slugs):
            raise LLMOutputError(
                f"AnswerSynthesizer.Synthesize: 'cited_slugs' must be a list of strings, got {cited_slugs!r}"
            )

        return SynthesizedAnswer(answer=answer, cited_slugs=[slug for slug in cited_slugs if slug in known_slugs])

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
