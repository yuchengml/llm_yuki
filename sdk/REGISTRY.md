# SDK Registry

> Index of all vendored and internal SDKs in this repository.
> AI agents must consult this file before writing any call to an unrecognized import.

| Name | Status | Source Path | Purpose |
|------|--------|-------------|---------|
| _(none yet)_ | — | — | — |

This repository currently vendors no external SDKs. The proposal's `README.md` (D3) and `ASSUMPTIONS.md` (B-1)
flag a possible future `deepagents`-based skill layer for per-corpus customization, but it is explicitly
unverified and deferred — this POC's `Connector`/`Extractor`/`Writer` implementations are all built-in code
(see `docs/llm-yuki-v0.1-proposal/SPEC.md`, Minimal Scope). If that skill layer is adopted later, vendor
`deepagents` under `sdk/deepagents/`, write `sdk/deepagents/analysis.md` (or `sdk/notes/deepagents.md`), and
register it in the table above before writing any call against it.

## Status Definitions

| Status | Meaning |
|--------|---------|
| `internal` | Developed internally in this project; not published as a public package |
| `vendored` | Publicly released but not covered by LLM training data |
