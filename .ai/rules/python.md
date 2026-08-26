# Python Coding Rules

## Type Safety

- All public functions must have type hints
- Use `from __future__ import annotations` for forward references
- Prefer `TypeAlias` / `Literal` for constrained type definitions (e.g. `Claim.provenance_state`)

```python
async def get_page(slug: str) -> Concept: ...
```

## Formatting

- Use `ruff` for linting and formatting
- Use `mypy --strict` for static type checking
- All code must pass `pre-commit` hooks before committing
- Ruff configuration is defined in `pyproject.toml` — do not override it inline

Key ruff settings in effect:

| Setting | Value |
|---|---|
| `line-length` | 120 |
| `target-version` | py312 |
| `quote-style` | double |
| `pydocstyle.convention` | google |
| `lint.per-file-ignores` | ANN rules ignored in `tests/**` |

Run linting and formatting:

```bash
ruff check .
ruff format .
```

## Naming Convention

- Variables and functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private members: `_leading_underscore`

```python
claim_id = "abc"
MAX_RETRY_COUNT = 3


class TxtFileConnector:
    def read_source(self, ref: str) -> Document: ...
```

## Async Rules

- Never use blocking I/O inside async functions
- Never use `time.sleep()` in async context
- Never make synchronous filesystem calls inside async functions once async adapters exist

```python
# Forbidden
async def bad():
    time.sleep(1)


# Correct
async def good():
    await asyncio.sleep(1)
```

## Module-Boundary Rules

This project uses Ports & Adapters (see root `ARCHITECTURE.md`), not a layered web-service architecture.

- `src/llm_yuki/domain/` must not import from `src/llm_yuki/adapters/`
- `src/llm_yuki/domain/` must not perform filesystem or network I/O directly — call through `ports/`
- `src/llm_yuki/adapters/` implement `ports/` interfaces; they may freely do I/O
- No domain-specific (per-corpus) extraction/linking rules inside `Orchestrator` or its sub-steps

## Imports

- Use absolute imports
- Group imports: stdlib → third-party → internal
- No wildcard imports (`from module import *`)
