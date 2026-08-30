# llm_yuki

> LLM Wiki 知識編譯與推理(Compilation & Inference)—— 一套領域無關、可持續維護的 LLM Wiki 知識庫編譯方法論 POC。

---

# Overview

這個 repo 是 [`docs/llm-yuki-v0.1-proposal/`](./docs/llm-yuki-v0.1-proposal/) 這份方法論提案的實作場所。

提案的核心假設:以 [OKF (Open Knowledge Format)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) 規格與 Karpathy 原始 LLM Wiki 三層架構(Raw Sources / Wiki / Schema)為基礎,補上「lint 診斷矛盾 → 根因歸因 → 針對性修正」的差異化機制,把來源文件編譯成一份持續存在、可累積、可雙向連結的結構化知識庫,取代「每次查詢都重新檢索、重新推理」的傳統 RAG 模式 —— 且這套方法論設計上領域無關,可以在特質差異大的領域間移植。

完整背景、已決議事項(D1–D23)、架構細節、範疇與成功判準都在提案文件裡:

| 文件 | 內容 |
|---|---|
| [`docs/llm-yuki-v0.1-proposal/README.md`](./docs/llm-yuki-v0.1-proposal/README.md) | 討論稿(scratchpad):動機、已決議事項 D1–D23 |
| [`docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md`](./docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md) | Implementation-ready 架構參考(資料模型、模組、演算法、lint、link/backlink、成本統計) |
| [`docs/llm-yuki-v0.1-proposal/SPEC.md`](./docs/llm-yuki-v0.1-proposal/SPEC.md) | POC Hypothesis、Minimal Scope、Success Criteria |
| [`docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md`](./docs/llm-yuki-v0.1-proposal/ASSUMPTIONS.md) | 已知範疇侷限與未查證假設清單 |
| [`docs/implementation/`](./docs/implementation/) | 現況機制文件:每個子系統實際上怎麼運作(模組、方法、演算法細節),跟上面「為什麼這樣決定」的提案文件是不同層次,互補不重複 |

本 repo 根目錄的 `ARCHITECTURE.md` 只提供 AI-Native Repository Standard 要求的高階摘要;實作 pipeline 邏輯前,請先讀上表的提案文件與 `docs/implementation/`。

---

# Features

呼應 `SPEC.md` 的 Minimal Scope:

- 可插拔的 `Connector` 攝入端(預設實作:txt file connector,資料夾 = 文件,`txt` 正文 + `images/`)
- 抽取粒度採**自然段落**單位(空行分段的預設切分器,`domain/passage_splitter.py`),不做固定長度 chunk 切割
  (D11);產出共享核心型別 `Claim` / `Concept` / `Source`(OKF typed frontmatter)—— `Source` 是每份 Raw
  Source 專屬的導覽頁,`summary` 由遞迴 batch-reduce 生成,彙整該文件**所有段落**產出的 `Claim`(D21)
- 執行策略分兩階段(D12):**Phase 1 平行**(`SelectPages`/`CompileWikiPages`,同批次每個段落各自比對同一份
  wiki index 快照,`ThreadPoolExecutor` 實作,worker 數可由 CLI `--max-workers` 調整)、**Phase 2 序列化**
  (`Merger`/`Validator`/`ErrorBook`/`Fixer`/寫入,依序執行避免並發寫入衝突)
- `Merger` 三層合併保護:陣列欄位聯集(決定性)/ `Concept.summary` 衝突時 LLM 合併 + 70% 長度比例拒絕 / 鎖定
  欄位(`concept_title`)不受 LLM 輸出影響(D22)
- 兩層 lint:OKF conformance(結構性,含跨 `Claim`/`Concept`/`Source` 的 slug 碰撞檢查)+ 自訂跨頁矛盾偵測
  (內容性),走 Error Book 五階段生命週期,每次 Attribute/VerifyAndClose 都同步寫一筆事件進 `log.md`
- `Writer` 決定性渲染 body 連結、增量維護 backlink(含 `Source.produced_claims`/`produced_concepts`),
  避免 body/frontmatter 不一致;`index.md` 依核心型別分層(根目錄 + `claims/`/`concepts/`/`sources/` 三份
  子目錄各自的 `index.md`,D23)
- 成本統計(`cost_ledger.jsonl`),用於跟向量 RAG、`openwiki` 做量化對照

---

# Repository Structure

```text
llm_yuki/
├── src/llm_yuki/
│   ├── domain/          # Orchestrator + abstract Extractor/Merger/Validator/ErrorBook/Fixer — no I/O
│   ├── ports/            # Connector / Writer abstract interfaces
│   ├── adapters/          # Concrete implementations (I/O lives here): connectors/, writers/, llm/,
│   │                       #   validation/, fixing/, merging/, state/, cost_ledger.py
│   ├── cli.py             # `llm-yuki` entrypoint — wires adapters into a real Orchestrator
│   └── logging.py         # Operational console logging: log format + get_logger()
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── docs/
│   ├── llm-yuki-v0.1-proposal/   # POC proposal: README / ARCHITECTURE / SPEC / ASSUMPTIONS
│   └── implementation/           # Current mechanism docs, one file per subsystem
├── .ai/
│   ├── rules/            # python / testing / security rules for AI agents
│   └── workflows/        # feature-development / bug-fix / refactoring / release-process
├── scripts/              # standalone manual scripts, not part of the installed package — see below
├── repo-meta/            # ownership.yaml, dependencies.yaml
├── sdk/                  # REGISTRY.md — vendored/internal SDK index
├── .github/workflows/    # CI: lint, typecheck, test
├── pyproject.toml
├── Makefile
├── README.md
├── TODO.md
├── .env.example
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

`SPEC.md` is decided (2026-08-26), the repository is initialized per the AI-Native Repository Standard, the
full compile pipeline (Algorithm 1) is implemented end to end and wired to a CLI, the proposal's D20–D23
update (`Source` core type, `Merger`'s D22 merge mechanics, D23's hierarchical `index.md`) is implemented
on top of it, and D11/D12 (natural-paragraph passage splitting, Phase 1 parallel / Phase 2 sequential
execution — previously never actually built, despite being decided from the start) landed last:

- **Core types**: `Claim`/`Concept`/`Source` — the three shared OKF typed-frontmatter core types
  (`domain/entities.py`). `Source` is a per-Raw-Source navigation page (D21) — not a replacement for
  `Claim.source_ref`, which still points to the Raw Source itself (D17).
- **`Connector`**: `TxtFileConnector` — reads Raw Sources from a `txt` + `images/` folder layout
  (`adapters/connectors/`)
- **Passage splitting**: `split_into_natural_paragraphs` — default blank-line-delimited natural-paragraph
  splitter (D11), pure/no I/O; the real per-corpus splitting rule is still delegated to a future domain
  skill (D3) (`domain/passage_splitter.py`)
- **`Writer`**: `MarkdownWriter` — writes OKF-conformant markdown under per-type `claims/`/`concepts/`/
  `sources/` subdirectories (each with its own `index.md`, plus a root `index.md` linking to all three,
  D23), renders body links deterministically, maintains backlinks (including `Source.produced_claims`/
  `produced_concepts`), and appends `log.md` audit-trail events (`adapters/writers/`). Every `index.md` entry
  is followed by a one-line description sourced from that page's own `description` frontmatter field
  (LLM-generated for `Claim`/`Concept`; deterministically Writer-generated for `Source`, extending D23 — see
  `TODO.md`)
- **`Extractor`**: `LLMExtractor` — LLM-backed `SelectPages`/`CompileWikiPages` (`adapters/llm/extractor.py`)
- **`Merger`**: `DefaultMerger` — deterministic slug-exact dedupe; three-layer merge protection for `Concept`
  updates (array union / LLM merge + 70%-length rejection / locked `concept_title`, D22); generates
  `Source.summary` via recursive batch-reduce over that document's Claims (D21 §1.5) (`adapters/merging/`)
- **`Validator`**: `DefaultValidator` — deterministic structural checks (5 types, including slug collisions
  across all three core types) + LLM-backed content checks (2 types) (`adapters/validation/`)
- **`Fixer`**: `DefaultFixer` — deterministic auto-fix + LLM-backed periodic fix (`adapters/fixing/`)
- **`ErrorBook`**: full five-phase lifecycle + YAML persistence + `log.md` event writes on every
  Attribute/VerifyAndClose call (§4.4) (`domain/error_book.py`, `adapters/state/error_book_store.py`)
- **Cost tracking**: `JsonlCostLedger` records every LLM call's token usage/latency, including `Source.summary`'s
  batch-reduce rounds (`adapters/cost_ledger.py`)
- **`Orchestrator`**: runs Algorithm 1 as D12's two phases — Phase 1 (`SelectPages`/`CompileWikiPages`) in
  parallel across every passage in the batch (`ThreadPoolExecutor`, `max_workers`), Phase 2 (`Merger`/
  `Validator`/`ErrorBook`/`Fixer`/writes) sequentially per passage to avoid concurrent write conflicts;
  creates each source's `Source` page once Phase 1 is done, and finalizes its `summary` once every one of
  that document's passages has gone through Phase 2; deterministically anchors every compiled
  `Claim.source_ref` to `<source id>#p<passage index>` so `Writer` backlink maintenance can find it
  (`domain/pipeline.py`)
- **`llm-yuki` CLI**: `compile` wires all of the above into a real `Orchestrator` and runs one batch
  (`src/llm_yuki/cli.py`, see `ARCHITECTURE.md` §5)

Not yet built: the soft-collision dedup pass (D22, architecture-only by design — see `TODO.md`'s Out of scope
list) and the SPEC.md validation experiments themselves (running real `M3SciQA`/`MMDocRAG` data through this
and measuring against the Success Criteria) — see [`TODO.md`](./TODO.md) §E for what's left. See
`ASSUMPTIONS.md` in the proposal for known open risks (esp. B-1: the deepagents skill extension point is
unverified — this POC's adapters are all built-in code, not deepagents skills).

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
cp .env.example .env   # fill in OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL — see ARCHITECTURE.md §2.1
poetry run llm-yuki compile <source_dir> <bundle_dir>
```

`.env` (in the directory you run the command from, or a parent of it) is loaded automatically — no need to
`export` it into the shell yourself; a real environment variable always takes precedence over the `.env`
value if both are set. Runs one compile batch (Algorithm 1) over `<source_dir>` (a Raw Sources folder — one
subfolder per document, each with a `.txt` body, split into natural paragraphs — D11) and writes the
resulting OKF bundle to `<bundle_dir>`. Pipeline-internal state (`error_book.yaml`, `cost_ledger.jsonl`) is
written to a `pipeline-state` sibling of `<bundle_dir>` by default (override with `--pipeline-state-dir`).
`--max-workers N` (default 4) caps how many Phase 1 extraction calls run concurrently (D12). Missing LLM
configuration fails immediately at startup with a clear message, not partway through a batch. See
`ARCHITECTURE.md` §5.

Operational console logging (`src/llm_yuki/logging.py`) writes timestamped progress lines to stderr as the
batch runs — batch/phase progress at `INFO`, per-passage/per-LLM-call detail at `DEBUG`. Set
`LLM_YUKI_LOG_LEVEL=DEBUG` (in `.env` or the environment) for the verbose view. This is separate from
`log.md` (the durable OKF audit trail inside the bundle) and from `cost_ledger.jsonl` — purely for watching a
run happen in real time, see `docs/implementation/cli-and-cost-ledger.md`.

`scripts/cli.py` is a thin convenience wrapper around the same `main()` for running it as a plain script
instead of the installed console command:

```bash
poetry run python scripts/cli.py compile <source_dir> <bundle_dir>
```

`src/llm_yuki/cli.py` itself stays inside the package — `[tool.poetry.scripts]` requires the entrypoint
module to live there to register `llm-yuki` as a console script — so this wrapper exists alongside it rather
than replacing it.

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
| `docs/llm-yuki-v0.1-proposal/` | The POC's methodology, decisions (D1–D23), spec, and known assumptions |
| `docs/implementation/` | How each subsystem actually works today — one file per module, complementary to the proposal above |

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
- `docs/implementation/`
