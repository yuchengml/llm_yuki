# data/

Example Raw Sources for trying `llm-yuki compile` locally — not test fixtures (those live in
`tests/fixtures/`) and not tracked as part of any test assertion.

## Layout

Follows the Raw Sources format from `docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md` §1.1: one folder per
document, each containing a single `.txt` body file (and optionally an `images/` subfolder — markdown image
links in the body are preserved as references, never interpreted/OCR'd, per decision D10).

```text
data/
└── raw_sources/
    └── water/
        └── body.txt
```

## Try it

```bash
cp .env.example .env   # fill in OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL
export $(grep -v '^#' .env | xargs)
poetry run llm-yuki compile data/raw_sources data/bundle
```

Writes the compiled OKF bundle to `data/bundle/` and pipeline state to `data/pipeline-state/`. Both are
gitignored — add more folders under `data/raw_sources/` to try compiling additional documents.
