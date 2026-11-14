<!-- Title: a Conventional Commit subject, e.g. "feat(source): record matrix messages" -->

## What and why



Closes #

## Checks

- [ ] `scripts/install-test-requirements.sh && ruff check . && ruff format --check . && python3 -m pytest` pass
- [ ] The panel checks and builds (`cd frontend && npm ci && npm run check && npm run build`), if it changed
- [ ] Texts in `strings.json` and both translations, and in `frontend/src/localize.ts` (en and de), if any changed
- [ ] `git diff --check` is clean
- [ ] No personal data in code, tests or screenshots
