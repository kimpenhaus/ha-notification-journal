## What and why



Closes #

## Checks

- [ ] `scripts/install-test-requirements.sh && ruff check . && ruff format --check . && python3 -m pytest` pass
- [ ] The panel checks and builds (`cd frontend && npm ci && npm run check && npm run build`), if it changed
- [ ] Texts in `strings.json` and both translations, and in `frontend/src/localize.ts` (en and de), if any changed
- [ ] `git diff --check` is clean
- [ ] The title is a Conventional Commit with a scope from `.github/workflows/pr-title.yml` (`feat(statistics): …`, `fix(panel): …`): it becomes the commit message and the changelog entry
- [ ] No personal data in code, tests or screenshots
