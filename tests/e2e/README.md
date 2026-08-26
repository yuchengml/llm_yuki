# e2e tests

Full-pipeline tests (`Connector` → `Orchestrator` → `Writer`, driven by real `Extractor`/`Validator`/`Fixer`
implementations, with a scripted fake LLM client standing in for actual network calls) live here. See
`test_compile_batch.py` for the first one, covering one full `run_batch` — extraction, structural + content
validation, ApplyUpdates, and backlink maintenance — end to end.
