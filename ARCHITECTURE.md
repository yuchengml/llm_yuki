# Architecture Document

> System boundaries, module responsibilities, and dependency flow for `llm_yuki`.
> This file is the AI-Native Repository Standard's required root-level summary. The authoritative, detailed
> design — data model, execution algorithm, lint rules, link/backlink handling, cost tracking — lives in
> [`docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md`](./docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md). Read that
> document before implementing any pipeline logic; this file only orients you to the module boundaries.

---

## 1. High-Level Architecture

This project follows **Ports & Adapters (hexagonal architecture)**, not a layered web-service architecture —
there is no HTTP API layer. The core is a domain-agnostic `Orchestrator` that runs the compile → lint → fix
loop; all I/O (reading Raw Sources, persisting wiki pages) happens through replaceable adapters.

```mermaid
flowchart LR
    RS[("Raw Sources<br/>folder = document<br/>txt + images/")] --> C["Connector<br/>(input port)"]
    C --> O

    subgraph O["Orchestrator (domain, no I/O)"]
        direction TB
        EX["Extractor"] --> ME["Merger"]
        ME --> VA["Validator"]
        VA --> EB["ErrorBook"]
        EB --> FX["Fixer"]
        FX -. "constraints for next round" .-> EX
    end

    ME --> W["Writer<br/>(output port)"]
    EB -. "log.md events" .-> W
    W --> FS[("bundle/<br/>OKF markdown")]
    EB --> PS[("pipeline-state/<br/>error_book.yaml")]
```

---

## 2. Module Responsibilities

### 2.1 `llm_yuki.domain` — core logic, no I/O

- `Orchestrator`: runs the compile loop (Algorithm 1; see proposal `ARCHITECTURE.md` §3)
- `Extractor` / `Merger` / `Validator` / `ErrorBook` / `Fixer`: sub-steps of the loop (proposal `ARCHITECTURE.md` §2.2)
- **Forbidden**: importing anything from `llm_yuki.adapters`, filesystem or network access, and any
  domain-specific (per-corpus) rule — those belong to a future skill layer, not the core pipeline
  (proposal `README.md` D3; unverified extension mechanism, see `ASSUMPTIONS.md` B-1)
- **LLM call interface**: the LLM-backed steps (`Extractor.compile_wiki_pages`, `Validator.content_validate`,
  `Fixer.llm_periodic_fix`) are expected to call an OpenAI-compatible Chat Completions API — either via
  OpenRouter, or a self-hosted OpenAI-compatible server (e.g. vLLM, Ollama) — via the `openai` Python package
  with a configurable `base_url`/`api_key`, not a vendor-specific native SDK. See `TODO.md` §B.
- **Core types** (`domain/entities.py`): `Claim` / `Concept` / `Document` — the three shared OKF
  typed-frontmatter types every domain uses (D9, D21). `Document` is a per-Raw-Source navigation page
  (`slug` = the source's id), distinct from `Claim.source_ref` (which still points *out* of the wiki to the
  Raw Source itself, D17) — see proposal `ARCHITECTURE.md` §1.5.

### 2.2 `llm_yuki.ports` — abstract interfaces

- `Connector`: `list_sources()` / `read_source(ref)` — turns Raw Sources into passages/documents
- `Writer`: persists `Claim`/`Concept`/`Document` pages, supports read-back, renders body links
  deterministically, maintains backlinks incrementally, and appends `log.md` audit-trail events
  (proposal `ARCHITECTURE.md` §2.3/§4.4)

### 2.3 `llm_yuki.adapters` — concrete I/O implementations

- `adapters.connectors.txt_file_connector.TxtFileConnector`: default/first `Connector` (D10) — reads the
  "folder = document, txt + `images/`" Raw Source format, preserving image links without interpreting them
- `adapters.writers.markdown_writer.MarkdownWriter`: default `Writer` — serializes `Claim`/`Concept`/
  `Document` pages as OKF-conformant markdown with YAML frontmatter under `bundle/`, in per-type
  subdirectories (`claims/`, `concepts/`, `documents/`) each with its own `index.md`, plus a root `index.md`
  linking to all three (D23)
- `adapters.llm.extractor.LLMExtractor`: LLM-backed `Extractor` — `SelectPages`/`CompileWikiPages`
- `adapters.merging.default_merger.DefaultMerger`: `Merger` — slug-exact dedupe; for `Concept` updates,
  three-layer merge protection (array union / LLM merge + 70%-length rejection / locked `concept_title`, D22);
  also generates `Document.summary` via recursive batch-reduce over that document's Claims (D21 §1.5)
- `adapters.validation.default_validator.DefaultValidator`: `Validator` — deterministic structural checks
  (5 types) + LLM-backed content checks (2 types)
- `adapters.fixing.default_fixer.DefaultFixer`: `Fixer` — deterministic auto-fix + LLM-backed periodic fix
- `adapters.state.error_book_store.YamlErrorBookStore`: persists `ErrorBook` to `pipeline-state/error_book.yaml`
- `adapters.cost_ledger.JsonlCostLedger`: append-only `pipeline-state/cost_ledger.jsonl` cost recorder (D19)

---

## 3. Dependency Flow

```text
adapters  →  ports  ←  domain
```

Adapters depend on ports (they implement them). Domain depends only on ports (it calls them through the
interface), never on adapters directly. This keeps `domain` testable without any filesystem or network access,
and lets `Connector`/`Writer` implementations be swapped — e.g. for a `deepagents` skill (proposal `README.md`
D3) — without touching the `Orchestrator`.

---

## 4. Forbidden

- No cross-boundary imports: `domain` must not import `adapters`.
- No domain-specific extraction/linking rules inside `Orchestrator` — that logic belongs to a per-corpus skill.
- No writing directly into `bundle/` from anywhere except a `Writer` implementation — this is what keeps OKF
  conformance enforceable in one place.
- No mixing of `pipeline-state/` (internal, e.g. `error_book.yaml`, `cost_ledger.jsonl`) into `bundle/`
  (must pass OKF conformance) — see proposal `ARCHITECTURE.md` §4.4.

---

## 5. Execution Interface

Pipeline execution is exposed as a **CLI first** — `llm_yuki.cli` (installed as the `llm-yuki` script; see
`pyproject.toml` `[tool.poetry.scripts]`). No web/API service is planned for this POC. The `compile`
subcommand wires every concrete adapter (§2.3) into a real `Orchestrator` and runs one batch end to end;
missing/invalid LLM configuration (`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`LLM_MODEL`) fails fast at startup with
a clear error, before any batch work starts, rather than partway through one.
