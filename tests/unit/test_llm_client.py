"""Unit tests for OpenAICompatibleClient — no real network access (fake ``openai`` client injected)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm_yuki.adapters.llm.client import LLMConfigError, OpenAICompatibleClient

pytestmark = pytest.mark.unit


class _FakeCompletions:
    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self._response


def _fake_openai_client(content: str, tokens_in: int, tokens_out: int) -> tuple[object, _FakeCompletions]:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )
    completions = _FakeCompletions(response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return fake_client, completions


@pytest.mark.parametrize(
    ("api_key", "base_url", "model"),
    [("", "http://x", "m"), ("k", "", "m"), ("k", "http://x", ""), ("  ", "http://x", "m")],
)
def test_constructor_rejects_empty_config(api_key: str, base_url: str, model: str) -> None:
    with pytest.raises(LLMConfigError):
        OpenAICompatibleClient(api_key=api_key, base_url=base_url, model=model)


def test_from_env_raises_naming_all_missing_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    with pytest.raises(LLMConfigError) as exc_info:
        OpenAICompatibleClient.from_env()

    message = str(exc_info.value)
    assert "OPENAI_API_KEY" in message
    assert "OPENAI_BASE_URL" in message
    assert "LLM_MODEL" in message


def test_from_env_succeeds_when_all_vars_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "some-model")

    client = OpenAICompatibleClient.from_env()

    assert isinstance(client, OpenAICompatibleClient)


def test_complete_parses_content_and_token_usage() -> None:
    fake_client, completions = _fake_openai_client("hello world", tokens_in=10, tokens_out=3)
    client = OpenAICompatibleClient(api_key="k", base_url="http://x", model="m", client=fake_client)  # type: ignore[arg-type]

    result = client.complete([{"role": "user", "content": "hi"}])

    assert result.content == "hello world"
    assert result.tokens_in == 10
    assert result.tokens_out == 3
    assert completions.calls[0]["model"] == "m"
    assert completions.calls[0]["messages"] == [{"role": "user", "content": "hi"}]


def test_complete_passes_response_format_json_when_requested() -> None:
    fake_client, completions = _fake_openai_client("{}", tokens_in=1, tokens_out=1)
    client = OpenAICompatibleClient(api_key="k", base_url="http://x", model="m", client=fake_client)  # type: ignore[arg-type]

    client.complete([{"role": "user", "content": "hi"}], response_format_json=True)

    assert completions.calls[0]["response_format"] == {"type": "json_object"}


def test_complete_handles_missing_usage_as_zero_tokens() -> None:
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="x"))], usage=None)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(response)))
    client = OpenAICompatibleClient(api_key="k", base_url="http://x", model="m", client=fake_client)  # type: ignore[arg-type]

    result = client.complete([{"role": "user", "content": "hi"}])

    assert result.tokens_in == 0
    assert result.tokens_out == 0
