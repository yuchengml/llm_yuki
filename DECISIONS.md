# Architecture Decision Records (ADRs)

> This document tracks significant *engineering/tooling* decisions made during the lifecycle of the project.
>
> The POC's methodology decisions (D1–D23: what to build, which corpora to test against, success criteria,
> etc.) are tracked separately in
> [`docs/llm-yuki-v0.1-proposal/README.md`](./docs/llm-yuki-v0.1-proposal/README.md) — that log is the
> authoritative source for "why does the pipeline work this way." This file is for decisions about how the
> repository itself is engineered (package manager, code architecture style, CI, etc.).

---

## [ADR-001] Use of `poetry` for Package Management

### Status
Accepted

### Context
The Python ecosystem has multiple package managers (pip, poetry, pipenv, uv). We need a reliable, mature, and
standardized tool for dependency management and virtual environments that aligns with the AI-Native Repository
Standard.

### Decision
We chose `poetry` as the default package management tool.

### Consequences
- **Positive:** Mature ecosystem, robust dependency resolution, lockfile support out-of-the-box, and
  widespread community adoption.
- **Negative:** Slightly slower dependency resolution compared to newer tools like `uv`.

---

## [ADR-002] Ports & Adapters instead of a layered web-service architecture

### Status
Accepted

### Context
The AI-Native Repository Standard's default `ARCHITECTURE.md` template assumes an API/Application/Domain/
Infrastructure layered web service. `llm_yuki` is not a web service — it is a batch/CLI-style compilation
pipeline with no HTTP API, whose central requirement (per proposal `README.md` D3) is that the core
`Orchestrator` stays domain-agnostic while `Connector`/`Writer` implementations, and potentially whole
per-corpus skills, are swappable.

### Decision
Structure `src/llm_yuki/` as `domain/` (Orchestrator + its sub-steps, no I/O) + `ports/` (abstract
`Connector`/`Writer`) + `adapters/` (concrete I/O implementations), i.e. hexagonal architecture, instead of the
template's layered model. See root `ARCHITECTURE.md` for the resulting module map.

### Consequences
- **Positive:** `domain/` is unit-testable with zero I/O; `Connector`/`Writer` (and later, per-corpus skills)
  can be swapped without touching pipeline logic — directly matches the proposal's D3 requirement.
- **Negative:** Diverges from the standard template's example layout; anyone applying the generic standard
  checklist literally needs to map "layers" to "ports/adapters" mentally. Documented here and in
  `ARCHITECTURE.md` to keep that mapping explicit.

---

## [ADR-003] No `tox.ini`; single supported Python version for now

### Status
Accepted

### Context
The standard's recommended structure includes `tox.ini` for multi-version testing. This POC targets a single
Python version (3.12) and has no cross-version compatibility requirement yet.

### Decision
Skip `tox.ini` for now; rely on `poetry` + `pytest` + CI running a single Python version. Revisit if the
project needs to support multiple Python versions (e.g. if it is published as a library).

### Consequences
- **Positive:** One less moving part while the pipeline itself is still unimplemented.
- **Negative:** No automated cross-version regression testing; must be added before any multi-version support
  claim is made.

---

<!-- Add new ADRs above this line -->
