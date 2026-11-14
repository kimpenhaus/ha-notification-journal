# Changelog

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
