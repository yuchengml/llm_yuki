# llm_yuki

> LLM Wiki 知識編譯與推理(Compilation & Inference)—— 一套領域無關、可持續維護的 LLM Wiki 知識庫編譯方法論 POC。

---

# Overview

這個 repo 是 [`docs/llm-yuki-v0.1-proposal/`](./docs/llm-yuki-v0.1-proposal/) 這份方法論提案的實作場所。

提案的核心假設:以 [OKF (Open Knowledge Format)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) 規格與 Karpathy 原始 LLM Wiki 三層架構(Raw Sources / Wiki / Schema)為基礎,補上「lint 診斷矛盾 → 根因歸因 → 針對性修正」的差異化機制,把來源文件編譯成一份持續存在、可累積、可雙向連結的結構化知識庫,取代「每次查詢都重新檢索、重新推理」的傳統 RAG 模式 —— 且這套方法論設計上領域無關,可以在特質差異大的領域間移植。

完整背景、已決議事項(D1–D19)、架構細節、範疇與成功判準都在提案文件裡:

| 文件 | 內容 |
|---|---|
| [`docs/llm-yuki-v0.1-proposal/README.md`](./docs/llm-yuki-v0.1-proposal/README.md) | 討論稿(scratchpad):動機、已決議事項 D1–D19 |
| [`docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md`](./docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md) | Implementation-ready 架構參考(資料模型、模組、演算法、lint、link/backlink、成本統計) |
| [`docs/llm-yuki-v0.1-proposal/SPEC.md`](./docs/llm-yuki-v0.1-proposal/SPEC.md) | POC Hypothesis、Minimal Scope、Success Criteria |
| [`docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md`](./docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md) | 已知範疇侷限與未查證假設清單 |

本 repo 根目錄的 `ARCHITECTURE.md` 只提供 AI-Native Repository Standard 要求的高階摘要;實作 pipeline 邏輯前,請先讀上表的提案文件。

---

# Features

呼應 `SPEC.md` 的 Minimal Scope:

- 可插拔的 `Connector` 攝入端(預設實作:txt file connector,資料夾 = 文件,`txt` 正文 + `images/`)
- 段落/概念單位抽取,產出共享核心型別 `Claim` / `Concept`(OKF typed frontmatter,不做固定長度 chunk 切割)
- 兩層 lint:OKF conformance(結構性)+ 自訂跨頁矛盾偵測(內容性),走 Error Book 五階段生命週期
- `Writer` 決定性渲染 body 連結、增量維護 backlink,避免 body/frontmatter 不一致
- 成本統計(`cost_ledger.jsonl`),用於跟向量 RAG、`openwiki` 做量化對照

---

# Repository Structure

```text
llm_yuki/
├── src/llm_yuki/
│   ├── domain/          # Orchestrator + Extractor/Merger/Validator/ErrorBook/Fixer — no I/O
│   ├── ports/            # Connector / Writer abstract interfaces
│   └── adapters/          # Concrete Connector/Writer implementations (I/O lives here)
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── docs/
│   └── llm-yuki-v0.1-proposal/   # POC proposal: README / ARCHITECTURE / SPEC / ASSUMPTIONS
├── .ai/
│   ├── rules/            # python / testing / security rules for AI agents
│   └── workflows/        # feature-development / bug-fix / refactoring / release-process
├── repo-meta/            # ownership.yaml, dependencies.yaml
├── sdk/                  # REGISTRY.md — vendored/internal SDK index
├── .github/workflows/    # CI: lint, typecheck, test
├── pyproject.toml
├── Makefile
├── README.md
├── AGENTS.md
├── CLAUDE.md
├── ARCHITECTURE.md
├── CONTRIBUTING.md
├── DECISIONS.md
└── LICENSE
```

---

# Architecture

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the module-boundary summary (Ports & Adapters, not a
layered web-service), and [`docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md`](./docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md)
for the full design.

High-level flow:

```text
Raw Sources (folder + txt + images/)
  ↓
Connector (input port)
  ↓
Orchestrator: Extractor → Merger → Validator → ErrorBook → Fixer
  ↓
Writer (output port)
  ↓
bundle/ (OKF-conformant markdown)
```

---

# Technology Stack

| Category | Technology |
|---|---|
| Language | Python 3.12 |
| Data validation | Pydantic |
| Testing | pytest, pytest-cov |
| Formatting / Lint | ruff |
| Type Checking | mypy |
| Dependency management | poetry |
| CI/CD | GitHub Actions |

---

# POC Status

This project is at the **scaffolding** stage: `SPEC.md` is decided (2026-08-26), the repository is initialized
per the AI-Native Repository Standard, and the pipeline modules exist as typed skeletons:

- **Implemented**:
  - `Claim`/`Concept` entities — the shared OKF typed-frontmatter core types (`domain/entities.py`)
  - `TxtFileConnector` — reads Raw Sources from a `txt` + `images/` folder layout (`adapters/connectors/`)
  - `MarkdownWriter` — writes OKF-conformant markdown, renders body links, maintains backlinks
    (`adapters/writers/`)
  - `Orchestrator` control flow — the Algorithm 1 call sequence is wired up and testable, but calls into the
    stubs below (`domain/pipeline.py`)
  - `llm-yuki` CLI scaffold — pipeline execution is exposed as a CLI first, no web/API service planned
    (`src/llm_yuki/cli.py`, see `ARCHITECTURE.md` §5); `compile` fails fast until the stubs below exist
- **Stubbed (interface/types only, logic raises `NotImplementedError`, pending LLM-backed implementation)**:
  `Extractor`, `Merger`, `Validator`, `ErrorBook`, `Fixer`

See [`TODO.md`](./TODO.md) for the full, itemized task list to take this from scaffolding to a validated POC
(core logic to implement, test coverage gaps, known risks, and the SPEC.md validation experiments still
outstanding). See [`.ai/workflows/feature-development.md`](./.ai/workflows/feature-development.md) for how to
pick up an individual piece, and `ASSUMPTIONS.md` in the proposal for known open risks (esp. B-1: the
deepagents skill extension point is unverified).

---

# Development Setup

## Requirements

- Python 3.12+
- poetry

## Installation

```bash
git clone <repository>
cd llm_yuki

poetry install
```

## Run the CLI

```bash
poetry run llm-yuki compile <source_dir> <bundle_dir>
```

`compile` currently exits with an error pointing at `TODO.md` §B — the domain logic it depends on
(`Extractor`/`Merger`/`Validator`/`ErrorBook`/`Fixer`) isn't implemented yet. See `ARCHITECTURE.md` §5.

## Run Tests

```bash
make test
```

## Run Lint

```bash
make lint
```

## Run Type Check

```bash
make typecheck
```

---

# Testing Strategy

```text
tests/
├── unit/          # isolated, no I/O — mainly src/llm_yuki/domain
├── integration/   # real filesystem — Connector/Writer round-trips
├── e2e/           # full Orchestrator loop, once implemented
└── fixtures/      # shared sample Raw Sources / bundles
```

Testing principles:

- Deterministic tests only, no flaky tests
- Regression tests required for every bug fix
- `domain/` code must be testable with zero filesystem/network access

---

# Coding Standards

See [`AGENTS.md`](./AGENTS.md) and [`.ai/rules/`](./.ai/rules/). Key rules:

- All functions require type hints (mypy-checked)
- `domain/` must not import `adapters/` (see `ARCHITECTURE.md` §4)
- No domain-specific (per-corpus) extraction rules inside the Orchestrator

---

# AI-Agent Guidelines

This repository is AI-Native: it follows the
[AI-Native Repository Standard](https://github.com/yuchengml/AINativeRepositoryStandard).

| File | Purpose |
|---|---|
| `AGENTS.md` | Primary entry point for all AI agents |
| `CLAUDE.md` | Claude Code entry point — redirects to `AGENTS.md` |
| `ARCHITECTURE.md` | Module boundaries (summary) |
| `DECISIONS.md` | Engineering/tooling ADRs |
| `.ai/rules/` | Coding, testing, security rules |
| `.ai/workflows/` | Step-by-step task workflows |
| `repo-meta/` | Machine-readable ownership/dependency metadata |
| `docs/llm-yuki-v0.1-proposal/` | The POC's methodology, decisions (D1–D19), spec, and known assumptions |

AI agents must read `AGENTS.md` before taking any action in this repository.

---

# CI/CD

```text
.github/workflows/ci.yml
```

Pipeline: lint (ruff) → typecheck (mypy) → test (pytest + coverage).

---

# Security

- Never commit secrets, API keys, or credentials
- Use environment variables for runtime configuration
- See [`.ai/rules/security.md`](./.ai/rules/security.md)

---

# Contribution Guide

See [`CONTRIBUTING.md`](./CONTRIBUTING.md). Pull requests must pass all CI checks and include tests.

---

# Commit Convention

```text
feat:
fix:
refactor:
test:
docs:
chore:
```

---

# License

MIT — see [`LICENSE`](./LICENSE).

---

# References

- `AGENTS.md`
- `ARCHITECTURE.md`
- `DECISIONS.md`
- `CONTRIBUTING.md`
- `TODO.md`
- `docs/llm-yuki-v0.1-proposal/`
