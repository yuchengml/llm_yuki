"""QA evaluation harness — SPEC.md's "檢索/推理正確性" success criterion (D5/D8), built on the Query module
(D25). Lives outside `domain`/`ports`/`adapters` (root ARCHITECTURE.md's Ports & Adapters split): this is
evaluation tooling, not core pipeline logic, the same top-level status `cli.py` already has.
"""
