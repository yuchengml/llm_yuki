"""Manual script for exercising OpenRouter's reasoning-preserving multi-turn flow directly.

Not part of the llm_yuki package/pipeline — a standalone sanity check for the OPENAI_API_KEY/
OPENAI_BASE_URL/LLM_MODEL config in .env (same variables the CLI uses, see root ARCHITECTURE.md §2.1) and
for OpenRouter's `reasoning` extra_body option. Demonstrates the two-call pattern: pass the first response's
`reasoning_details` back unmodified on the assistant turn so the model continues reasoning instead of
starting over.

Usage:
    poetry run python scripts/call_llm.py
"""

from __future__ import annotations

import os
import sys

from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

QUESTION = "How many r's are in the word 'strawberry'?"


def main() -> int:
    """Run the two-call reasoning-preserving flow and print both responses."""
    load_dotenv(find_dotenv(usecwd=True))

    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    missing = [
        name
        for name, value in [("OPENAI_API_KEY", api_key), ("OPENAI_BASE_URL", base_url), ("LLM_MODEL", model)]
        if not value
    ]
    if missing:
        print(
            f"error: missing required environment variable(s): {', '.join(missing)} (see .env.example)",
            file=sys.stderr,
        )
        return 1
    assert api_key and base_url and model  # narrowed: `missing` above is empty, so none of these are None

    client = OpenAI(base_url=base_url, api_key=api_key)

    # First call, with reasoning enabled.
    first_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": QUESTION}],
        extra_body={"reasoning": {"enabled": True}},
    )
    assistant_message = first_response.choices[0].message
    print("--- first response ---")
    print(assistant_message.content)

    # Second call: pass reasoning_details back unmodified so the model continues from where it left off,
    # instead of reasoning from scratch.
    messages = [
        {"role": "user", "content": QUESTION},
        {
            "role": "assistant",
            "content": assistant_message.content,
            "reasoning_details": getattr(assistant_message, "reasoning_details", None),
        },
        {"role": "user", "content": "Are you sure? Think carefully."},
    ]
    second_response = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]  # reasoning_details is an OpenRouter extension field
        extra_body={"reasoning": {"enabled": True}},
    )
    print("\n--- second response ---")
    print(second_response.choices[0].message.content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
