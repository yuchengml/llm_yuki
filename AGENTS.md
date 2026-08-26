# AGENTS.md

> This is the primary entry point for AI Agents operating in this repository.
> Read this document completely before taking any action.

---

## 0. Start Here: Repository Knowledge Map

Before starting any task, read the following documents in order:

### Step 1 — Understand the POC and the system

| Document | Purpose |
|---|---|
| [docs/llm-yuki-v0.1-proposal/SPEC.md](./docs/llm-yuki-v0.1-proposal/SPEC.md) | Hypothesis, Minimal Scope, Success Criteria — what this POC is and is not trying to prove |
| [docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md](./docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md) | Implementation-ready design: data model, module map, Algorithm 1, lint, link/backlink, cost tracking |
| [docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md](./docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md) | Known scope limits and unverified assumptions — check before "fixing" something that is a deliberate exclusion |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Module-boundary summary for this repo (Ports & Adapters) |
| [DECISIONS.md](./DECISIONS.md) | Engineering/tooling ADRs (package manager, architecture style, etc.) |

The proposal's `README.md` ([docs/llm-yuki-v0.1-proposal/README.md](./docs/llm-yuki-v0.1-proposal/README.md))
holds the full decision log (D1–D19) with reasoning. Consult it when a design choice in `ARCHITECTURE.md`
seems arbitrary — it almost certainly traces back to a decision there.

### Step 2 — Learn the rules

| Document | Purpose |
|---|---|
| [.ai/rules/python.md](./.ai/rules/python.md) | Type hints, async rules, naming conventions, module-boundary constraints |
| [.ai/rules/testing.md](./.ai/rules/testing.md) | Test structure, required coverage, naming, agent-specific test rules |
| [.ai/rules/security.md](./.ai/rules/security.md) | Forbidden actions, secret management, input validation |

### Step 3 — Choose the right workflow for your task

| Task Type | Workflow Document |
|---|---|
| New feature | [.ai/workflows/feature-development.md](./.ai/workflows/feature-development.md) |
| Bug fix | [.ai/workflows/bug-fix.md](./.ai/workflows/bug-fix.md) |
| Release | [.ai/workflows/release-process.md](./.ai/workflows/release-process.md) |
| Refactoring | [.ai/workflows/refactoring.md](./.ai/workflows/refactoring.md) |

### Additional references

| Document | When to read |
|---|---|
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Branch naming, commit conventions, PR requirements |
| [README.md](./README.md) | Project overview, tech stack, development setup |

---

## 1. Core Principles

- **Do Not Break the Build:** Always run `make lint`, `make typecheck`, and `make test` before finalizing changes.
- **Explain Your Reasoning:** Provide clear, concise explanations for architectural and design choices.
- **Ask Before Destructive Actions:** Never perform actions like deleting data, force-pushing, or deploying
  without explicit human approval.
- **Explicit Over Implicit:** Follow written rules and the decisions in the proposal docs. Do not rely on
  assumptions or inferred conventions — if something is genuinely undecided, it will be listed in
  `docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md`, not silently guessed.
- **Respect the Minimal Scope:** `SPEC.md` deliberately excludes things (multimodal understanding, chunk-based
  extraction, DB-backed `Writer`, cross-domain bundle merging, etc.). Do not "improve" the POC by expanding
  scope that was explicitly cut — check `ASSUMPTIONS.md` §A before adding anything that looks missing.

---

## 2. Coding Rules

Full details: [.ai/rules/python.md](./.ai/rules/python.md)

- All functions must have type hints (`mypy` compliant, `mypy --strict`).
- Code format must follow the project's `ruff` configuration defined in `pyproject.toml` — do not override inline.
- Docstrings follow Google style; comments in code must be in English.
- Async code must not block the event loop (e.g., use `await asyncio.sleep()` instead of `time.sleep()`).

---

## 3. Testing Rules

Full details: [.ai/rules/testing.md](./.ai/rules/testing.md)

- All new features require unit tests.
- Integration tests are required for anything that touches the filesystem (`Connector`/`Writer` implementations).
- Tests must be deterministic (no flaky tests, no unseeded randomness).
- Every bug fix requires a regression test written before the fix.
- Coverage configuration is defined in `pyproject.toml` — minimum threshold is 60%.

---

## 4. Architecture Constraints

Full details: [ARCHITECTURE.md](./ARCHITECTURE.md) (summary) and
[docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md](./docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md) (full design).

This project uses **Ports & Adapters**, not a layered web-service architecture:

- `src/llm_yuki/domain/` — `Orchestrator`, `Extractor`, `Merger`, `Validator`, `ErrorBook`, `Fixer`. Pure logic,
  no filesystem/network access, no imports from `adapters/`.
- `src/llm_yuki/ports/` — abstract `Connector` / `Writer` interfaces. `domain/` depends only on these.
- `src/llm_yuki/adapters/` — concrete `Connector`/`Writer` implementations. All I/O lives here.
- The `Orchestrator` must never contain domain-specific (per-corpus) rules — e.g. how to segment a scientific
  paper vs. a long document is a future skill's job, not core pipeline code (see proposal `README.md` D3).
- Never write to `bundle/` output except through a `Writer` implementation — this keeps OKF conformance
  (`docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md` §2.3) enforceable in one place.

---

## 5. Security & Forbidden Actions

Full details: [.ai/rules/security.md](./.ai/rules/security.md)

- **NEVER** commit secrets, API keys, or credentials to the repository.
- Do not disable security scanning tools.
- Do not change permissions or access control mechanisms without human review.

---

## 6. SDK Knowledge

If you encounter an import you do not recognize, look up in this order:

1. `sdk/notes/<sdk-name>.md` — if it exists, read this first
2. `sdk/<sdk-name>/src/` — vendored source for deep tracing
3. `sdk/REGISTRY.md` — index of all vendored SDKs and their status

**Never guess SDK APIs.** Always trace the source before writing any call.

This repository currently vendors no external SDKs (see `sdk/REGISTRY.md`). If a future task adds a
`deepagents`-based skill layer (see proposal `ASSUMPTIONS.md` B-1), vendor it under `sdk/` and register it
there before writing any call against it — do not assume its API from training data, since `analysis.md` for
it has not been written yet.

---

## 7. Development Workflow

Full details in [.ai/workflows/](./.ai/workflows/)

1. Identify the task type (feature / bug fix / refactor / release).
2. Read the corresponding workflow file in `.ai/workflows/`.
3. Read `ARCHITECTURE.md` and `DECISIONS.md` for context; read the proposal docs for anything pipeline-related.
4. Implement and write tests following `.ai/rules/`.
5. Run `make lint` and `make test` — all checks must pass.
6. Follow commit and PR conventions in `CONTRIBUTING.md`.
