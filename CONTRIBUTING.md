# Contributing

Thanks for helping to improve Notification Journal!

- **Questions and help with setup:** ask in the [discussions](https://github.com/kimpenhaus/ha-notification-journal/discussions/categories/q-a).
- **Bugs & ideas:** open an [issue](https://github.com/kimpenhaus/ha-notification-journal/issues/new/choose).
- **Security issues:** see [SECURITY.md](SECURITY.md) – please report privately.

## Pull requests

1. Fork the repository and create a branch from `main`; its name must not contain `tags/` or end in `tags`, or the HACS check fails.
2. Title the pull request as a [Conventional Commit](https://www.conventionalcommits.org/) with a scope from
   `.github/workflows/pr-title.yml` (`fix(panel): …`) and a summary starting with a lowercase letter, without a
   final period: it becomes the commit message and the changelog entry, and a check enforces it.
   Repairs to CI, tests, tooling or docs use `ci`, `test`, `chore` or `docs` with the scope of the part they
   concern (`test(store): …`), never `fix`, so they stay out of the changelog. A revert made with GitHub's
   button is renamed to `revert(<scope>): …`.
3. The description becomes the commit body, where release-please reads `BREAKING CHANGE:` (or `BREAKING-CHANGE:`) and
   `Release-As:` anywhere, even mid-sentence: write them only when they are meant.
4. Keep changes focused – one topic per pull request.
5. Work through the checklist of the pull request template; the commands are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#commands).

## Releases

Releases are made by the maintainer with release-please: once a beta of the version has been tested, merging its release pull request publishes a GitHub release, which the Marketplace offers as an update.
