# Workflow: Bug Fix

## Steps

1. **Reproduce the Bug**
   - Confirm the bug exists with a failing test or manual reproduction steps
   - Document the exact input and expected vs. actual output

2. **Create Branch**
   ```
   git checkout -b fix/<short-description>
   ```

3. **Root Cause Analysis**
   - Identify the root cause before writing any fix
   - Check if the bug exists in other parts of the codebase (e.g. both `TxtFileConnector` and `MarkdownWriter`
     touch path handling — a path-traversal bug in one may exist in the other)

4. **Write a Regression Test First**
   - Add a failing test that reproduces the bug
   - Confirm it fails before applying the fix

5. **Implement the Fix**
   - Fix only the root cause — do not refactor unrelated code
   - Follow coding rules in `.ai/rules/`

6. **Verify the Fix**
   - Confirm the regression test now passes
   - Run the full test suite to check for regressions

7. **Run Checks Locally**
   ```bash
   make lint
   make typecheck
   make test
   ```

8. **Commit**
   ```
   fix: <short description of what was fixed>
   ```

9. **Create Pull Request**
   - Include reproduction steps in the PR description
   - Reference the related issue

## AI Agent Constraints

- Always write a regression test before fixing
- Do not change behavior beyond what is required to fix the bug
- Do not skip root cause analysis — treat symptoms only as a last resort
- Confirm the regression test fails before applying the fix
