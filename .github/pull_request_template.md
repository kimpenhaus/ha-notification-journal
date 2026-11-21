## What and why



Closes #

## Checks

- [ ] `scripts/install-test-requirements.sh && ruff check . && ruff format --check . && python3 -m pytest` pass
- [ ] The panel checks and builds (`cd frontend && npm ci && npm run check && npm run build`), if it changed
- [ ] Texts in `strings.json` and both translations, and in `frontend/src/localize.ts` (en and de), if any changed
- [ ] `git diff --check` is clean
- [ ] `README.md`, `docs/DEVELOPMENT.md`, `CONTRIBUTING.md`, `AGENTS.md`, the `.github/` templates and the screenshots match the change; the places checked are named above
- [ ] The title follows the rules in [CONTRIBUTING.md](https://github.com/kimpenhaus/ha-notification-journal/blob/main/CONTRIBUTING.md#pull-requests): it becomes the commit message and the changelog entry
- [ ] No personal data in code, tests or screenshots
