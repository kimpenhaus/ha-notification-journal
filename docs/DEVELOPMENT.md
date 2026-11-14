# Development

How Notification Journal is built, tested and deployed. For what it does and how to use it, see the [README](../README.md).

## Commands

| Task | Command |
|------|---------|
| Install tools | `python3 -m pip install -r requirements-dev.txt` |
| Lint | `ruff check . && ruff format --check .` |
| Tests | `python3 -m pytest` (needs the frontend wheel: `scripts/install-test-requirements.sh` installs both) |
| Panel: check and build | `cd frontend && npm ci && npm run check && npm run build` |
| Panel: format | `cd frontend && npm run format` |

## How it records

Each source listens to Home Assistant's `call_service` event and reads the calls; it never changes them.

- **notify** (`sources/notify.py`): legacy notify actions and `notify.send_message` on notify entities. A notify group calls the actions of its members right after its own call, in the same asyncio context; those calls are attached to the group's record instead of becoming records.
- **The bell** (`sources/persistent.py`): `persistent_notification` reports a notification without the context of the call that created or dismissed it. Its services run right after the `call_service` event, in the same asyncio context, so the event listener leaves the call in a context variable for the update that follows; without one the origin is Home Assistant itself. On start the source catches up with what appeared or disappeared while it was not running. Creating an ID that is still open adds a record and marks the previous one *replaced*.
- **Telegram** (`sources/telegram.py`): the `telegram_bot` send actions with text (`send_message`, and `send_photo`, `send_video`, `send_animation`, `send_voice`, `send_document` with a caption, `send_poll` with its question). The chats come from the target's notify entities, from `chat_id` matched against the bot's allowed chats, or, with neither, the bot's first allowed chat, as Telegram does itself. Another action needs only an entry in `TEXT_FIELDS`. Messages sent with `notify.send_message` to the bot's notify entities are recorded by the notify source.
- **Speech** (`sources/speech.py`): `tts.speak` (recipients from `media_player_entity_id`) and `assist_satellite.announce` (target resolved with `helpers.target`: entities, devices, areas, floors, labels); media player groups expanded. Calls without text are skipped.

The origin comes from the trace context variable of the running automation or script (`origin.py`), the user from the call's context. Recipients of the bell and of announcements count for every user (`EVERYONE` in `notification_users`); Telegram chats belong to no user, so only administrators see them.

## Database

`notification_journal.db` next to `configuration.yaml`, SQLite with FTS5, accessed from one worker thread so writes keep their order; during a backup the worker waits. `SCHEMA` in `store.py` is the current state for a new database. A schema change raises `SCHEMA_VERSION` and adds a step to `MIGRATIONS`, from the previous version; on open, the store copies the database to `notification_journal.db.bak-v<version>` and runs each missing step in its own transaction. A database of a newer version is left untouched and the setup fails (`tests/test_migrations.py`).

## Panel

TypeScript with [Lit](https://lit.dev), bundled by esbuild into `custom_components/notification_journal/frontend/panel.js`; the bundle is not committed, the CI and the release build it. It uses only the theme's CSS variables, the `hass` object Home Assistant passes in and `ha-icon` (for the icons of automations and scripts, with an own fallback), no other frontend components, so it does not break when those change. The integration serves the scripts (`panel.js`, `iconset.js`) itself with `Cache-Control: no-cache`, so a new panel reaches the browser on the next load without a restart.

The panel is registered with `frontend.async_register_built_in_panel` as a custom panel, because `panel_custom.async_register_panel` cannot hide it from the sidebar. Changed options reload the entry, which registers the panel anew.

The icon (`custom_components/notification_journal/brand/`) is drawn in `icon.svg`; the PNGs are rendered from it with `magick -background none -density 192 icon.svg -resize 256x256 icon.png` (and `-density 384 … 512x512 icon@2x.png`). The sidebar shows the same motif as a single-colour 24 px icon, `notification_journal:bell-stack`, from the icon set in `frontend/src/iconset.ts`; Home Assistant loads that script with every frontend (`frontend.add_extra_js_url`).

The screenshots in `docs/screenshots/` are rendered from made-up data with a mock Home Assistant in headless Chromium (`scripts/screenshots/`): build the panel, then `scripts/screenshots/render.sh`.

## WebSocket API

The panel reads the journal through these commands. An administrator sees every notification; any other user only those that reached them (a notification counts for a user when one of its recipients, the members reached through a group included, is that user's person), those under the bell and announcements, or nothing when the option says so. A record carries `status_time` and `status_by` (an origin) once it was dismissed or replaced, and `source_ref`, the ID of the notification under the bell.

| Command | Returns |
|---------|---------|
| `notification_journal/list` | `records` and `total`; filters `text` (full-text, prefix match), `channel` (action or group), `origin` (automation or script entity), `status`, `since`, `until`, `user_id` (administrators only), `newest_first`, `group_by: origin` (sorted by origin, then time; adds `groups`, the number per origin), `archived` (the caller's archive instead of the active view), `limit` (≤ 200), `offset` |
| `notification_journal/get` | one record by `record_id` with its data, the calls a group made and `trace_path`, the link to the exact run of the automation or script |
| `notification_journal/facets` | `origins`: the automations and scripts that sent notifications the caller may see, for the origin filter |
| `notification_journal/subscribe` | an event `{change: added \| updated, record}` for every new or changed notification the caller may see, `{change: removed, record_id}` for a deleted one |
| `notification_journal/archive` | archives `record_ids` (≤ 200) for the caller, or restores them with `archived: false`; only the caller's view changes, a user who is no administrator only archives what they may see; returns `changed` |
| `notification_journal/delete` | deletes one notification by `record_id` for every recipient; administrators only, not used by the panel |

## CI and releases

The CI (`.github/workflows/ci.yml`) runs on every pull request and on `main`: lint and tests in `python:3.14-slim`, the panel's type check and build in `node:26-slim`, and Home Assistant's `hassfest` and the HACS check. Renovate keeps the tools, images and actions current.

Releases come from release-please (`.github/workflows/release.yml`, `release-please-config.json`). From the Conventional Commit subjects on `main` it keeps a release pull request with the next version and the changelog up to date; merging it tags the version, writes it into `manifest.json` and publishes a GitHub release. The release workflow then builds the panel and attaches `notification_journal.zip` (the contents of `custom_components/notification_journal/` with the built `panel.js`), which the Marketplace installs (`hacs.json`: `zip_release`). To test before a release, publish a pre-release by hand (e.g. `gh release create v0.1.0-beta.1 --prerelease --target main`): the same workflow attaches the archive, with the version from the tag in the manifest. Only those who turn on pre-releases for the repository are offered it.

## History of the name

The integration started as `notification_history`, a domain that already belongs to another integration in the HACS catalogue, and was renamed to `notification_journal` before its first release.
