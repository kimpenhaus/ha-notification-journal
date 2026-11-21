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
- `README.md` is for users (what it does, installation, options, privacy); how it is built, tested and released goes into `docs/DEVELOPMENT.md`. Its section *How this project was made* is wanted by the maintainer and stays.
- Log at `warning` and above for what a user has to act on; routine operation logs at `debug`.
- Only add a comment when the reader cannot derive it from the code.
- Tests that check what the store reports (events, sensors, panel updates) wait with `hass.async_block_till_done(wait_background_tasks=True)` after `store.async_flush()`: the reports and, on a new database as in every test setup, the import from the recorder run as background tasks of the entry.
- The panel uses the theme's CSS variables and the `hass` object only: no colour, font or shadow of its own and no fallback for a variable Home Assistant always sets (only the optional `--ha-card-*` ones get one, as in `ha-card`); the card surface and the controls the views share live in `frontend/src/styles.ts`, no internal `ha-*` components of the Home Assistant frontend apart from `ha-icon` with a fallback; its texts live in `frontend/src/localize.ts` with `en` and `de`.

## Commits, Pull Requests and Releases

- Every change goes through a pull request with a green `ci`, merged by squash; the pull request title becomes the commit subject and its description the commit body.
- Before a pull request is pushed, run `/code-review`, `/simplify` and `/security-review` on its changes and work their findings in; the description says what they found and what was left out on purpose. This holds for every pull request, small fixes included.
- Every pull request brings the docs up to date with its change before it is pushed, so they always describe the current state: search `README.md`, `docs/DEVELOPMENT.md`, `CONTRIBUTING.md`, this file and the templates in `.github/` for every statement the change touches (behaviour, options, events, limits), not only the obvious place, and render the screenshots again for a change users can see (`scripts/screenshots/render.sh`, made-up data extended for it). The description names the places checked and changed. Ask the maintainer before changing behaviour the docs describe.
- Conventional Commit subjects: `type(scope): imperative summary`, the summary starting with a lowercase letter, without a final period, at most 50 characters. The scope is required and one of those in `.github/workflows/pr-title.yml`, which checks the title of every pull request (`Conventional PR title`); a new part of the integration adds its scope there. release-please derives the version and the changelog from the subjects: `fix` is a patch, `feat` a minor version, `!` a breaking change.
- `feat`, `fix`, `perf` and `revert` end up in the release notes, so they describe what users notice; changes to CI, tests, tooling or docs use `ci`, `test`, `chore` or `docs`, even when they repair something, with the scope of the part they concern (`test(store): …`, `ci(release): …`), or `docs`, `ci` or `tooling` for the docs besides the README, the CI jobs and the build and lint tools. A revert made with GitHub's button is renamed to `revert(<scope>): …`.
- A pull request that resolves an issue has `Closes #<n>` in its description.
- Branch names contain no `tags/` and do not end in `tags`: HACS strips `tags/` from a branch's download address, and the `hacs` check fails.
- Do not edit the version in `manifest.json` or `CHANGELOG.md` by hand; release-please does that in its release pull request.
- Before the release pull request is merged, a beta of that version is tagged and tested on a Home Assistant installation (`docs/DEVELOPMENT.md`, CI and releases); the last beta contains everything the release does.
- Before the release pull request is merged, compare `README.md`, `docs/DEVELOPMENT.md` and the screenshots with everything the release contains (its changelog): every feature is in the README's feature list, and every one users can see is on a screenshot. Close the gaps by pull request first; that each pull request updated the docs does not replace this check.
- Do not add `Co-Authored-By`, AI attribution, or another author identity to commits, pull requests, issue comments or release notes.

## Security

- Never commit secrets, tokens or data from a real Home Assistant installation (notification texts, names, entity IDs).
- Links from notification payloads open only with `http(s)` or as a same-origin path.
