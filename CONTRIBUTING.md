# Contributing

Thanks for helping to improve Notification Journal!

- **Bugs & ideas:** open an [issue](https://github.com/kimpenhaus/ha-notification-journal/issues/new/choose).
- **Security issues:** see [SECURITY.md](SECURITY.md) – please report privately.

## Pull requests

1. Fork the repository and create a branch from `main`.
   Name the pull request in the [Conventional Commits](https://www.conventionalcommits.org/) style
   with a scope (`feat(statistics): …`, `fix(panel): …`, `docs(readme): …`; the scopes are listed in
   `.github/workflows/pr-title.yml`): its title becomes the commit message and the changelog entry. A check fails if it does not.
2. Keep changes focused – one topic per pull request.
3. Run the checks from [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#commands): lint, tests and, if the panel changed, its type check and build.
4. Every text a user sees goes through the translations, in English and German.
5. Use made-up data in tests and screenshots, never data from a real Home Assistant installation.

## Releases

Releases are made by the maintainer with release-please: merging its release pull request publishes a GitHub release, which the Marketplace offers as an update.
