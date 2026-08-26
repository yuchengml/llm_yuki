# Workflow: Refactoring

## Steps

1. **Define Scope**
   - Clearly state what is being refactored and why
   - Confirm the refactoring does not change external behavior

2. **Create Branch**
   ```
   git checkout -b refactor/<short-description>
   ```

3. **Ensure Test Coverage First**
   - Verify existing tests cover the area being refactored
   - Add tests if coverage is insufficient before starting
   - Tests are the safety net — do not refactor without them

4. **Refactor in Small Steps**
   - Make one logical change at a time
   - Run tests after each step to catch regressions early
   - Commit each step independently for easier review

5. **Verify No Behavior Change**
   - All existing tests must still pass
   - No new functionality should be introduced
   - No performance regressions (run benchmarks if applicable)

6. **Run Checks Locally**
   ```bash
   make lint
   make typecheck
   make test
   ```

7. **Commit**
   ```
   refactor: <short description of what was restructured>
   ```

8. **Create Pull Request**
   - Clearly state in the PR that this is behavior-preserving
   - Include before/after structure comparison if helpful

## AI Agent Constraints

- Never mix refactoring with feature additions or bug fixes in the same PR
- Never delete tests during refactoring
- Always confirm test suite passes before and after each step
- Do not rename public APIs without a deprecation plan
- Do not restructure the `domain/`/`ports/`/`adapters/` boundary without explicit instruction
