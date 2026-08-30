"""Shared exception for malformed LLM structured output, used by the LLM-backed pipeline stages."""

from __future__ import annotations


class LLMOutputError(RuntimeError):
    """Raised when an LLM response doesn't match the expected structured-output shape.

    Deliberately not swallowed anywhere in this pipeline: a batch that can't parse its own extraction output
    should fail loudly, not silently apply an empty/partial update (AGENTS.md §1, "Explicit Over Implicit").
    """
