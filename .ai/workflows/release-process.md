# Workflow: Release Process

## Steps

1. **Verify Main Branch**
   - All CI checks must be passing on `main`
   - No open critical issues targeting this release

2. **Create Release Branch**
   ```
   git checkout -b release/<version>
   ```

3. **Bump Version**
   - Update `version` in `pyproject.toml`
   - Follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

   | Change Type      | Version Bump |
   | ---------------- | ------------ |
   | Breaking change  | MAJOR        |
   | New feature      | MINOR        |
   | Bug fix / patch  | PATCH        |

4. **Update Changelog**
   - Document all changes since the last release
   - Group by: Added, Changed, Fixed, Deprecated, Removed, Security

5. **Run Full Test Suite**
   ```bash
   make test
   make lint
   make typecheck
   ```

6. **Create Pull Request to Main**
   - Title: `release: v<version>`
   - Include changelog summary in PR description

7. **Tag Release After Merge**
   ```bash
   git tag v<version>
   git push origin v<version>
   ```

8. **Publish**
   - Trigger the release pipeline (CI/CD)
   - Verify deployment succeeds before wider rollout, if this becomes a deployed service

## AI Agent Constraints

- Never release without all CI checks passing
- Never bump a MAJOR version without explicit human approval
- Never push directly to `main` — always use a PR
- Do not modify the changelog for previous releases
