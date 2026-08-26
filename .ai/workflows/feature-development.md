# Workflow: Feature Development

## Steps

1. **Create Issue**
   - Define the feature clearly with acceptance criteria
   - Check `docs/llm-yuki-v0.1-proposal/SPEC.md` (Minimal Scope) and `ASSUMPTIONS.md` — confirm the feature is
     actually in scope for this POC before starting

2. **Create Branch**
   ```
   git checkout -b feature/<short-description>
   ```

3. **Understand the Codebase**
   - Read `ARCHITECTURE.md` (root) and `docs/llm-yuki-v0.1-proposal/ARCHITECTURE.md` for the relevant module
   - Read `AGENTS.md` for coding rules and constraints
   - Identify whether the change belongs in `domain/`, `ports/`, or `adapters/`

4. **Implement Feature**
   - Follow module boundaries defined in `ARCHITECTURE.md` (no `domain/` → `adapters/` imports)
   - Apply coding rules from `.ai/rules/`
   - No domain-specific (per-corpus) logic inside `Orchestrator`

5. **Add Tests**
   - Unit tests for all new `domain/`/`ports/` logic
   - Integration tests if `adapters/` (filesystem I/O) changed
   - Follow rules in `.ai/rules/testing.md`

6. **Run Checks Locally**
   ```bash
   make lint        # ruff
   make typecheck   # mypy
   make test        # full test suite
   ```

7. **Commit**
   ```
   feat: <short description of what was added>
   ```

8. **Create Pull Request**
   - Fill in PR template: summary, motivation, test evidence, breaking changes
   - Link the related issue

9. **Code Review**
   - Address all review comments before merging
   - Do not merge without approval

## AI Agent Constraints

- Do not skip any step above
- Do not modify unrelated files
- Do not introduce new dependencies without documenting the reason and updating `repo-meta/dependencies.yaml`
- Always verify tests pass before marking the task as complete
