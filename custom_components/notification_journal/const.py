"""Constants of the Notification Journal integration."""

from enum import StrEnum
from typing import Final

DOMAIN: Final = "notification_journal"
TITLE: Final = "Notification Journal"
DATABASE_FILE: Final = "notification_journal.db"

PANEL_URL_PATH: Final = "notification-journal"
PANEL_COMPONENT: Final = "notification-journal-panel"
FRONTEND_URL: Final = "/notification_journal"
PANEL_MODULE_URL: Final = f"{FRONTEND_URL}/panel.js"
ICONSET_URL: Final = f"{FRONTEND_URL}/iconset.js"
PANEL_ICON: Final = "notification_journal:bell-stack"
PANEL_TITLES: Final = {"de": "Benachrichtigungsverlauf"}

CONF_RETENTION_DAYS: Final = "retention_days"
CONF_MAX_ENTRIES: Final = "max_entries"
CONF_RECORD_NOTIFY: Final = "record_notify"
CONF_EXCLUDED_CHANNELS: Final = "excluded_channels"
CONF_NON_ADMIN_VISIBILITY: Final = "non_admin_visibility"
CONF_SHOW_IN_SIDEBAR: Final = "show_in_sidebar"
CONF_PANEL_TITLE: Final = "panel_title"
CONF_PANEL_ICON: Final = "panel_icon"
CONF_RECORD_PERSISTENT: Final = "record_persistent_notifications"
CONF_RECORD_SPEECH: Final = "record_speech"
CONF_RECORD_TELEGRAM: Final = "record_telegram"


class Visibility(StrEnum):
    """What a user without administrator rights sees in the panel."""

    OWN = "own"
    NONE = "none"


MIN_RETENTION_DAYS: Final = 1
MAX_RETENTION_DAYS: Final = 3650
MIN_MAX_ENTRIES: Final = 100
MAX_MAX_ENTRIES: Final = 1_000_000

DEFAULT_OPTIONS: Final = {
    CONF_RETENTION_DAYS: 90,
    CONF_MAX_ENTRIES: 100_000,
    CONF_RECORD_NOTIFY: True,
    CONF_RECORD_PERSISTENT: True,
    CONF_RECORD_SPEECH: True,
    CONF_RECORD_TELEGRAM: True,
    CONF_EXCLUDED_CHANNELS: [],
    CONF_NON_ADMIN_VISIBILITY: Visibility.OWN.value,
    CONF_SHOW_IN_SIDEBAR: True,
}
