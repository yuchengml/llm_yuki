"""LLM-backed ``NextActionDecider`` (proposal ARCHITECTURE.md §8.5): drives ``IterativeAgenticQueryEngine``'s
round-by-round ``wiki_search``/``wiki_read``/stop decision.

Same shape as ``adapters/llm/extractor.py::LLMExtractor`` — prompt-and-parse around ``OpenAICompatibleClient``,
cost recorded via ``JsonlCostLedger``.
"""

from __future__ import annotations

import time

from llm_yuki.adapters.cost_ledger import JsonlCostLedger
from llm_yuki.adapters.llm.client import OpenAICompatibleClient
from llm_yuki.adapters.llm.errors import LLMOutputError
from llm_yuki.adapters.llm.json_utils import parse_json_object
from llm_yuki.domain.query import EvidenceItem, NextActionDecider, QueryAction

_DECIDE_SYSTEM_PROMPT = """\
You are the action-decider for a domain-agnostic wiki's agentic query loop. Given a question and the \
evidence gathered so far (search results and/or page reads from previous rounds), decide the single next \
action. Respond with a JSON object matching exactly one of these shapes:
{"tool": "wiki_search", "query": "..."} - search the wiki index for more relevant pages.
{"tool": "wiki_read", "slugs": ["slug-1", ...]} - read the full content of specific page slugs that already \
appeared in a previous search's results. Never invent a slug that hasn't appeared in the evidence.
{"tool": "stop"} - the evidence gathered so far is sufficient to answer the question.

Prefer wiki_search first if there is no evidence yet. Use wiki_read to look at the full content of promising \
search hits before answering. Stop as soon as the evidence is sufficient — do not keep searching or reading \
unnecessarily; every round costs an LLM call."""


class LLMActionDecider(NextActionDecider):
    """Calls ``llm_client`` once per round to decide the agentic loop's next action."""

    def __init__(self, llm_client: OpenAICompatibleClient, cost_ledger: JsonlCostLedger, batch_id: int) -> None:
        self._llm_client = llm_client
        self._cost_ledger = cost_ledger
        self._batch_id = batch_id

    def decide(self, question: str, evidence: list[EvidenceItem]) -> QueryAction:
        """Ask the LLM for the next ``wiki_search``/``wiki_read``/``stop`` action."""
        user_prompt = f"Question:\n{question}\n\nEvidence so far:\n{_format_evidence(evidence)}"

        start = time.monotonic()
        response = self._llm_client.complete(
            [{"role": "system", "content": _DECIDE_SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
            response_format_json=True,
        )
        wall_clock_ms = (time.monotonic() - start) * 1000
        self._cost_ledger.record(
            "NextActionDecider.Decide",
            self._batch_id,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            wall_clock_ms=wall_clock_ms,
        )

        payload = parse_json_object(response.content, context="NextActionDecider.Decide")
        tool = payload.get("tool")
        if tool == "stop":
            return QueryAction(tool="stop")
        if tool == "wiki_search":
            query = payload.get("query")
            if not isinstance(query, str) or not query.strip():
                raise LLMOutputError(f"NextActionDecider.Decide: 'query' must be a non-empty string, got {query!r}")
            return QueryAction(tool="wiki_search", query=query)
        if tool == "wiki_read":
            slugs = payload.get("slugs", [])
            if not isinstance(slugs, list) or not all(isinstance(slug, str) for slug in slugs):
                raise LLMOutputError(f"NextActionDecider.Decide: 'slugs' must be a list of strings, got {slugs!r}")
            return QueryAction(tool="wiki_read", slugs=slugs)
        raise LLMOutputError(
            f"NextActionDecider.Decide: 'tool' must be one of wiki_search/wiki_read/stop, got {tool!r}"
        )


def _format_evidence(evidence: list[EvidenceItem]) -> str:
    """Render prior rounds' evidence into a short, LLM-readable transcript."""
    if not evidence:
        return "(none yet)"

    lines: list[str] = []
    for round_number, item in enumerate(evidence, start=1):
        if item.kind == "search":
            hits = ", ".join(f"{hit.slug} (score={hit.score:.2f})" for hit in item.hits) or "(no hits)"
            lines.append(f"Round {round_number} [wiki_search]: {hits}")
        else:
            pages = ", ".join(f"{page.slug}: {page.content[:200]}" for page in item.pages) or "(no pages)"
            lines.append(f"Round {round_number} [wiki_read]: {pages}")
    return "\n".join(lines)
