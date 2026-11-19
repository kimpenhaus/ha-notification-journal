# Contributing

Thanks for helping to improve Notification Journal!

- **Bugs & ideas:** open an [issue](https://github.com/kimpenhaus/ha-notification-journal/issues/new/choose).
- **Security issues:** see [SECURITY.md](SECURITY.md) – please report privately.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Title the pull request as a [Conventional Commit](https://www.conventionalcommits.org/) with a scope from
   `.github/workflows/pr-title.yml` (`fix(panel): …`): it becomes the commit message and the changelog entry,
   and a check enforces it.
3. Keep changes focused – one topic per pull request.
4. Work through the checklist of the pull request template; the commands are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#commands).

## Releases

Releases are made by the maintainer with release-please: merging its release pull request publishes a GitHub release, which the Marketplace offers as an update.
