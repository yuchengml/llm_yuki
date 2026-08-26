"""OpenAI-compatible LLM client (root ARCHITECTURE.md §2.1, §5).

Targets either OpenRouter or a self-hosted OpenAI-compatible server — never a vendor-specific native SDK, per
the decision recorded in root ``ARCHITECTURE.md``. Configuration is validated eagerly at construction time
(``from_env``), so a missing API key/base URL/model fails at CLI startup rather than deep inside a batch on
the first LLM-backed call (``TODO.md`` §B: "a clear startup-time error, not a late per-call failure").

Does not record cost events itself — it has no notion of ``stage``/``batch_id``. Callers (the concrete
``Extractor``/``Validator``/``Fixer`` LLM-backed implementations) time their own calls and record them via
``adapters.cost_ledger.JsonlCostLedger``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI

_API_KEY_ENV = "OPENAI_API_KEY"
_BASE_URL_ENV = "OPENAI_BASE_URL"
_MODEL_ENV = "LLM_MODEL"


class LLMConfigError(RuntimeError):
    """Raised when required LLM client configuration is missing or empty."""


@dataclass(frozen=True)
class LLMResponse:
    """Result of one chat-completion call, with token usage for the cost ledger (D19)."""

    content: str
    tokens_in: int
    tokens_out: int


class OpenAICompatibleClient:
    """Thin wrapper around the ``openai`` package, pointed at OpenRouter or a self-hosted endpoint."""

    def __init__(self, api_key: str, base_url: str, model: str, *, client: OpenAI | None = None) -> None:
        if not api_key.strip():
            raise LLMConfigError(f"{_API_KEY_ENV} is required and must not be empty.")
        if not base_url.strip():
            raise LLMConfigError(f"{_BASE_URL_ENV} is required and must not be empty.")
        if not model.strip():
            raise LLMConfigError(f"{_MODEL_ENV} is required and must not be empty.")
        self._model = model
        self._client = client if client is not None else OpenAI(api_key=api_key, base_url=base_url)

    @classmethod
    def from_env(cls) -> OpenAICompatibleClient:
        """Build from ``OPENAI_API_KEY``/``OPENAI_BASE_URL``/``LLM_MODEL``.

        Raises :class:`LLMConfigError` naming every missing variable at once, rather than failing on the
        first one an eager caller happens to read — there is deliberately no default ``base_url``: forcing
        an explicit choice between OpenRouter and a self-hosted endpoint avoids silently talking to a real
        paid endpoint nobody configured on purpose.
        """
        missing = [name for name in (_API_KEY_ENV, _BASE_URL_ENV, _MODEL_ENV) if not os.environ.get(name)]
        if missing:
            raise LLMConfigError(
                f"Missing required environment variable(s): {', '.join(missing)}. Set them to either an "
                "OpenRouter or a self-hosted OpenAI-compatible endpoint (see root ARCHITECTURE.md §2.1)."
            )
        return cls(api_key=os.environ[_API_KEY_ENV], base_url=os.environ[_BASE_URL_ENV], model=os.environ[_MODEL_ENV])

    def complete(self, messages: list[dict[str, str]], *, response_format_json: bool = False) -> LLMResponse:
        """Call the Chat Completions API once, returning content + token usage."""
        kwargs: dict[str, object] = {"model": self._model, "messages": messages}
        if response_format_json:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
        content = response.choices[0].message.content or ""
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage is not None else 0
        tokens_out = usage.completion_tokens if usage is not None else 0
        return LLMResponse(content=content, tokens_in=tokens_in, tokens_out=tokens_out)
