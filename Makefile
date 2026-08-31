.PHONY: install lint format typecheck test test-cov clean compile search query evaluate-qa musique-sample musique-compile

install:
	poetry install

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

typecheck:
	poetry run mypy src

test:
	poetry run pytest

test-cov:
	poetry run pytest --cov=src --cov-report=term-missing --cov-report=html

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml dist build

# Overridable variables for the targets below, e.g.:
#   make search BUNDLE=bundle Q="what is water?"
BUNDLE ?= bundle
SOURCE_DIR ?= data/raw_sources
QA ?= qa.jsonl
Q ?=
METHOD ?= single-pass
TOP_K ?= 8
OUTPUT ?= report.json
NUM_QUESTIONS ?= 20
SEED ?= 0
MUSIQUE_RAW_SOURCES ?= data/raw_sources/musique-sample
MUSIQUE_BUNDLE ?= bundle-musique-sample

# Needs .env (OPENAI_API_KEY/OPENAI_BASE_URL/LLM_MODEL) — see .env.example / root README.md.
compile:
	poetry run llm-yuki compile $(SOURCE_DIR) $(BUNDLE)

# Retrieval only — no LLM/.env needed at all (D25).
search:
	poetry run llm-yuki search $(BUNDLE) "$(Q)" --top-k $(TOP_K)

# Needs .env — full cited answer (single-pass or agentic via METHOD=).
query:
	poetry run llm-yuki query $(BUNDLE) "$(Q)" --method $(METHOD) --top-k $(TOP_K)

# Needs .env — EM/F1 against a QA JSONL (see evaluation/qa_runner.py).
evaluate-qa:
	poetry run llm-yuki evaluate-qa $(BUNDLE) $(QA) --method $(METHOD) --top-k $(TOP_K) --output $(OUTPUT)

# Prepares a MuSiQue subset (D26) — no LLM needed, just downloads/samples data.
#   make musique-sample NUM_QUESTIONS=20 SEED=0
musique-sample:
	poetry run python scripts/musique_subset_to_raw_sources.py \
		--num-questions $(NUM_QUESTIONS) --seed $(SEED) \
		--out-raw-sources $(MUSIQUE_RAW_SOURCES) \
		--out-qa-jsonl data/musique-sample-qa.jsonl

# Compiles the MuSiQue subset from `make musique-sample` into a bundle — needs .env, run musique-sample first.
#   make musique-compile MUSIQUE_BUNDLE=bundle-musique-sample
musique-compile:
	poetry run llm-yuki compile $(MUSIQUE_RAW_SOURCES) $(MUSIQUE_BUNDLE)
