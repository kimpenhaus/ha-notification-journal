# Changelog

## [0.6.0](https://github.com/kimpenhaus/ha-notification-journal/compare/v0.5.0...v0.6.0) (2026-11-21)


### New

* **panel:** export the journal as csv or json ([#125](https://github.com/kimpenhaus/ha-notification-journal/issues/125)) ([e51fc68](https://github.com/kimpenhaus/ha-notification-journal/commit/e51fc68262bba46a9e5853a70c93b899c15faec6))
* **panel:** send any notification to any target ([#129](https://github.com/kimpenhaus/ha-notification-journal/issues/129)) ([5fbef9c](https://github.com/kimpenhaus/ha-notification-journal/commit/5fbef9c5ed32ee32e245dacdc8e3ad5271bec7f0))


### Fixed

* **panel:** list each phone once in send to ([#130](https://github.com/kimpenhaus/ha-notification-journal/issues/130)) ([b496fb0](https://github.com/kimpenhaus/ha-notification-journal/commit/b496fb09ab4f1e29fa4600e85cdc4e55d96b8afe))
* **panel:** separate csv as the number format expects ([#128](https://github.com/kimpenhaus/ha-notification-journal/issues/128)) ([92199ad](https://github.com/kimpenhaus/ha-notification-journal/commit/92199ad16b554a365571f7001dd07984cbbbebce))

## [0.5.0](https://github.com/kimpenhaus/ha-notification-journal/compare/v0.4.0...v0.5.0) (2026-11-21)


### New

* **automations:** add events, query and sensors ([#112](https://github.com/kimpenhaus/ha-notification-journal/issues/112)) ([0da7d53](https://github.com/kimpenhaus/ha-notification-journal/commit/0da7d534c562867d2457264cd790d4a527e07608))
* **sources:** mark notifications replaced by tag ([#107](https://github.com/kimpenhaus/ha-notification-journal/issues/107)) ([6d33a15](https://github.com/kimpenhaus/ha-notification-journal/commit/6d33a155ef084506bcf2b90dfd3635a2c61a0eb5))
* **sources:** skip commands to the companion app ([#109](https://github.com/kimpenhaus/ha-notification-journal/issues/109)) ([3a15f47](https://github.com/kimpenhaus/ha-notification-journal/commit/3a15f4714b8939dafb04c376a745fc85fbaf7d17))


### Fixed

* **store:** report live changes during an import ([#115](https://github.com/kimpenhaus/ha-notification-journal/issues/115)) ([def0890](https://github.com/kimpenhaus/ha-notification-journal/commit/def08906549b42665278bfb34f5b852b42a29d5e))

## [0.4.0](https://github.com/kimpenhaus/ha-notification-journal/compare/v0.3.1...v0.4.0) (2026-11-19)


### Features

* **failures:** read raised errors from traces ([#87](https://github.com/kimpenhaus/ha-notification-journal/issues/87)) ([ec05fa4](https://github.com/kimpenhaus/ha-notification-journal/commit/ec05fa4a4550d63ed63642f7133ddefd6b19da31))
* record notifications that failed to send ([#86](https://github.com/kimpenhaus/ha-notification-journal/issues/86)) ([ff1c2df](https://github.com/kimpenhaus/ha-notification-journal/commit/ff1c2dfa4d8408117c74e54c993886ca5f20d10b))
* send a failed notification again ([#90](https://github.com/kimpenhaus/ha-notification-journal/issues/90)) ([2af0470](https://github.com/kimpenhaus/ha-notification-journal/commit/2af0470ba0515c7aac434b265579fec48044629c))
* **statistics:** count and show failed ones ([#88](https://github.com/kimpenhaus/ha-notification-journal/issues/88)) ([0a24c29](https://github.com/kimpenhaus/ha-notification-journal/commit/0a24c29449418c75287426ef7146149c4e38a59a))


### Bug Fixes

* **panel:** catch up after the connection returns ([#93](https://github.com/kimpenhaus/ha-notification-journal/issues/93)) ([a65c843](https://github.com/kimpenhaus/ha-notification-journal/commit/a65c8432561e944d07ef0bb9b7574aeca8b3c4a4))
* **tests:** wait for the notify group before calling it ([#81](https://github.com/kimpenhaus/ha-notification-journal/issues/81)) ([139fc6c](https://github.com/kimpenhaus/ha-notification-journal/commit/139fc6cf8710180d47c7076c61deee1588b8c668))

## [0.3.1](https://github.com/kimpenhaus/ha-notification-journal/compare/v0.3.0...v0.3.1) (2026-11-17)


### Miscellaneous Chores

* release 0.3.1 ([#76](https://github.com/kimpenhaus/ha-notification-journal/issues/76)) ([53e665a](https://github.com/kimpenhaus/ha-notification-journal/commit/53e665a3c2fca2073d11849437eff4515db70ce6))

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
