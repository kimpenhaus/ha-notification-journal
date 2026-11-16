# Changelog

## [0.3.0](https://github.com/kimpenhaus/ha-notification-journal/compare/v0.2.0...v0.3.0) (2026-11-16)


### Features

* list every day of the timeline, load a day when it opens ([#66](https://github.com/kimpenhaus/ha-notification-journal/issues/66)) ([1383f2f](https://github.com/kimpenhaus/ha-notification-journal/commit/1383f2fa5363d3d5dd579a2c9f5b455f0d9f5513))
* open an image in an overlay ([#64](https://github.com/kimpenhaus/ha-notification-journal/issues/64)) ([208887b](https://github.com/kimpenhaus/ha-notification-journal/commit/208887b94d002194d2aabd5f2a35af3628c80f25))
* open the timeline with only the newest day expanded ([#62](https://github.com/kimpenhaus/ha-notification-journal/issues/62)) ([01c3885](https://github.com/kimpenhaus/ha-notification-journal/commit/01c38855550f9d08ca81b5b59344f37b34f5df8e))
* show the media and the tag of a notification ([#60](https://github.com/kimpenhaus/ha-notification-journal/issues/60)) ([5cc9e43](https://github.com/kimpenhaus/ha-notification-journal/commit/5cc9e43108e16c45fc5869b6cb5243dc32e8eb52))

## [0.2.0](https://github.com/kimpenhaus/ha-notification-journal/compare/v0.1.0...v0.2.0) (2026-11-16)


### Features

* import past notifications from the recorder ([#54](https://github.com/kimpenhaus/ha-notification-journal/issues/54)) ([f81e055](https://github.com/kimpenhaus/ha-notification-journal/commit/f81e05530e80d1d7b46b7baa1298f363a4fa104c))
* name the integration that sent a notification ([#35](https://github.com/kimpenhaus/ha-notification-journal/issues/35)) ([3f01578](https://github.com/kimpenhaus/ha-notification-journal/commit/3f01578870553c74bf7a3e4be52a5df90ab21853))
* show answers to notification buttons ([#37](https://github.com/kimpenhaus/ha-notification-journal/issues/37)) ([58a603a](https://github.com/kimpenhaus/ha-notification-journal/commit/58a603ad22ab440847f917947d17a973236b9269))
* statistics in the panel ([#51](https://github.com/kimpenhaus/ha-notification-journal/issues/51)) ([90489ef](https://github.com/kimpenhaus/ha-notification-journal/commit/90489efeaba8d62d877b01f3f1185e905ef3c582))
* **store:** remove old database copies ([#46](https://github.com/kimpenhaus/ha-notification-journal/issues/46)) ([c837bfc](https://github.com/kimpenhaus/ha-notification-journal/commit/c837bfc8de524f123b39e03dee3057735b83a1e7))


### Bug Fixes

* **panel:** use only home assistant theme values ([#48](https://github.com/kimpenhaus/ha-notification-journal/issues/48)) ([6ad20a8](https://github.com/kimpenhaus/ha-notification-journal/commit/6ad20a8cd71ed969f24c04dbf87db0eea6d9ee5f))
* show the current name of an origin ([#50](https://github.com/kimpenhaus/ha-notification-journal/issues/50)) ([ec383c8](https://github.com/kimpenhaus/ha-notification-journal/commit/ec383c8362b3c17069e7dc7fdb91eb4804bacb56))


### Reverts

* use absolute urls for images and links ([#40](https://github.com/kimpenhaus/ha-notification-journal/issues/40)) ([79a2657](https://github.com/kimpenhaus/ha-notification-journal/commit/79a2657deafe5711546f978c8c3d620579940d57))

## 0.1.0 (2026-11-14)

The first release of Notification Journal: a journal of every notification your Home Assistant sends, in a sidebar panel.

### Features

* Records notify actions without changing a single automation: the Companion app, notify entities, and notify groups, resolved into the people and devices they reach
* Records Home Assistant's own notifications under the bell, with when and by whom they were dismissed or replaced
* Records spoken announcements with text (`tts.speak`, `assist_satellite.announce`) and messages of the Telegram bot
* Shows the automation or script behind every notification, with a link to the exact trace of that run, or the user who sent it by hand
* Sidebar panel with a timeline by day or a view grouped by automation, full-text search, filters, live updates and an archive per person
* Every person sees the notifications sent to them, administrators see all
* Options for sources, exclusions, retention, access and the sidebar entry; English and German
