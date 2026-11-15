# Agent Instructions

## Scope

- Home Assistant custom integration `notification_journal` in `custom_components/notification_journal/`, tests in `tests/` (`pytest-homeassistant-custom-component`), and the sidebar panel in `frontend/` (TypeScript, Lit, esbuild), built into `custom_components/notification_journal/frontend/panel.js` (not committed).
- How it works, the database, the API and the release process: `docs/DEVELOPMENT.md`.
- Database schema: `SCHEMA` in `store.py` is the current state for a new database; a change raises `SCHEMA_VERSION` and adds a step to `MIGRATIONS` (from the previous version), with a test in `tests/test_migrations.py`.
- `strings.json` is the source of the texts; `translations/en.json` is a copy of it and `translations/de.json` has the same keys (checked by a test).
- Target the Home Assistant version in `hacs.json` and newer, Python 3.14. The tests run against the Home Assistant release that `pytest-homeassistant-custom-component` pins.

## Commands

| Task | Command |
|------|---------|
| Install tools | `python3 -m pip install -r requirements-dev.txt` |
| Lint and format check (as in CI) | `ruff check . && ruff format --check .` |
| Tests (installs the frontend wheel the tests need) | `scripts/install-test-requirements.sh && python3 -m pytest` |
| Panel: type check, format check, build (as in CI) | `cd frontend && npm ci && npm run check && npm run build` |
| Whitespace check | `git diff --check` |

## Conventions

- Code, comments, documentation, issues and commits in English; every user-facing text through translations with `en` and `de`.
- Built for any Home Assistant installation: no names, entity IDs or addresses of a particular home in code, defaults or tests; test data and screenshots (`scripts/screenshots/`) are made up.
- Every change updates `README.md`, `docs/DEVELOPMENT.md` and this file where it changes what they describe, and a change users can see renders the screenshots again (`scripts/screenshots/render.sh`, made-up data extended for it), in the same pull request.
- `README.md` is for users (what it does, installation, options, privacy); how it is built, tested and released goes into `docs/DEVELOPMENT.md`. Its section *How this project was made* is wanted by the maintainer and stays.
- Log at `warning` and above for what a user has to act on; routine operation logs at `debug`.
- Only add a comment when the reader cannot derive it from the code.
- The panel uses the theme's CSS variables and the `hass` object only: no colour, font or shadow of its own and no fallback for a variable Home Assistant always sets (only the optional `--ha-card-*` ones get one, as in `ha-card`); the card surface and the controls the views share live in `frontend/src/styles.ts`, no internal `ha-*` components of the Home Assistant frontend apart from `ha-icon` with a fallback; its texts live in `frontend/src/localize.ts` with `en` and `de`.

## Commits, Pull Requests and Releases

- Every change goes through a pull request with a green `ci`, merged by squash; the pull request title becomes the commit message.
- Conventional Commit subjects: `type(scope): imperative summary`, lowercase, at most 50 characters. release-please derives the version and the changelog from them: `fix` is a patch, `feat` a minor version, `!` a breaking change.
- `feat`, `fix` and `perf` end up in the release notes, so they describe what users notice; changes to CI, tooling or docs use `ci`, `chore` or `docs`, even when they repair something.
- A pull request that resolves an issue has `Closes #<n>` in its description.
- Do not edit the version in `manifest.json` or `CHANGELOG.md` by hand; release-please does that in its release pull request.
- Do not add `Co-Authored-By`, AI attribution, or another author identity to commits, pull requests, issue comments or release notes.

## Security

- Never commit secrets, tokens or data from a real Home Assistant installation (notification texts, names, entity IDs).
- Links from notification payloads open only with `http(s)` or as a same-origin path.
