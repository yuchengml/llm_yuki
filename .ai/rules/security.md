# Security Rules

## Forbidden Actions

- Never commit secrets, API keys, or credentials to source code
- Never modify production infrastructure automatically
- Never store credentials in source code or config files
- Never disable security scanning in CI/CD
- Never use `eval()` or `exec()` with user-supplied input
- Never construct file paths from untrusted input without validating they stay inside the intended
  Raw Sources / `bundle/` root (path traversal risk in `Connector`/`Writer` implementations)

## Secret Management

Always use:
- Environment variables for runtime secrets (e.g. LLM provider API keys, once `Extractor`/`Fixer` call an LLM)
- A secret manager for any deployed environment
- `.env` files only for local development (must be in `.gitignore`)

```python
# Forbidden
API_KEY = "sk-hardcoded-secret"

# Correct
import os

API_KEY = os.environ["API_KEY"]
```

## Input Validation

- Validate all Raw Source input (`Connector.read_source`) — do not trust file contents or filenames
- Use `pydantic` schema validation for `Claim`/`Concept` construction; never write unvalidated data into `bundle/`
- Never trust data from external systems (future connectors, e.g. Gmail/Notion) without validation

## Dependency Security

- Run `poetry run pip-audit` (or equivalent) regularly
- Do not use dependencies with known critical vulnerabilities
- Review all new dependencies before adding them, and record their trust status in `repo-meta/dependencies.yaml`

## AI Agent Rules

- Never generate or suggest hardcoded credentials
- Always use environment variables for secrets in generated code
- Flag any existing hardcoded secrets found in the codebase
- Do not modify CI security-scan configuration without explicit approval
