# Testing Rules

## Test Structure

```text
tests/
├── unit/          # isolated tests, no I/O — mainly src/llm_yuki/domain
├── integration/   # real filesystem — Connector/Writer round-trips against bundle/
├── e2e/           # full Orchestrator loop, once Extractor/Validator/Fixer are implemented
└── fixtures/      # shared sample Raw Sources / bundles
```

## Required Coverage

| Type             | Requirement                                             |
| ----------------- | -------------------------------------------------------- |
| Unit Test        | Required for all `domain/` and `ports/` code             |
| Integration Test | Required for all `adapters/` (Connector/Writer) changes  |
| E2E Test         | Required once the full `Orchestrator` loop is implemented |

Coverage configuration is defined in `pyproject.toml` — do not override it inline.

Key coverage settings in effect:

| Setting | Value |
|---|---|
| `run.branch` | `true` — branch coverage measured |
| `run.source` | `["src"]` — application code only |
| `report.fail_under` | `60` — minimum threshold to pass (raise to 80%+ as project matures) |
| `html.directory` | `htmlcov` |
| `xml.output` | `coverage.xml` (consumed by CI) |

Run coverage:

```bash
pytest --cov=src --cov-report=term-missing
pytest --cov=src --cov-report=html   # generates htmlcov/
```

## Test Rules

- Every bug fix must include a regression test
- Tests must be deterministic — no random data without seeding
- Tests must not depend on external unstable services (no live LLM calls in unit/integration tests — mock them)
- Use mocks/stubs for external dependencies in unit tests
- Snapshot tests are discouraged

## Naming Convention

```python
# Pattern: test_<unit>_<scenario>_<expected>
def test_claim_confidence_out_of_range_raises_validation_error(): ...
def test_txt_file_connector_reads_image_links_preserves_markdown(): ...
```

## Fixtures

- Define shared fixtures in `tests/fixtures/`
- Never hardcode test data inline if reused across tests

## AI Agent Rules

- Do not delete existing tests without explicit instruction
- Do not skip tests with `pytest.mark.skip` without a comment explaining why
- Always run the full test suite after making changes
- Verify that new tests actually fail before the fix is applied
- Do not "fix" a test by relaxing an assertion instead of fixing the underlying code
