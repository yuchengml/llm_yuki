"""JSON-parsing helper shared by every LLM-backed pipeline stage that expects structured output."""

from __future__ import annotations

import json
from typing import Any

from llm_yuki.adapters.llm.errors import LLMOutputError


def parse_json_object(content: str, *, context: str) -> dict[str, Any]:
    """Parse ``content`` as a JSON object, raising :class:`LLMOutputError` with ``context`` on any mismatch."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"{context}: LLM response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMOutputError(f"{context}: expected a JSON object, got {type(parsed).__name__}")
    return parsed
