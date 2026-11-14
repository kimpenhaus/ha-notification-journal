"""Record the notifications Home Assistant sends and show them in a panel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_EXCLUDED_CHANNELS,
    CONF_MAX_ENTRIES,
    CONF_NON_ADMIN_VISIBILITY,
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    CONF_RECORD_NOTIFY,
    CONF_RECORD_PERSISTENT,
    CONF_RECORD_SPEECH,
    CONF_RECORD_TELEGRAM,
    CONF_RETENTION_DAYS,
    CONF_SHOW_IN_SIDEBAR,
    DATABASE_FILE,
    DEFAULT_OPTIONS,
    DOMAIN,
    Visibility,
)
from .panel import async_register_frontend, async_register_panel, async_remove_panel
from .recipients import qualify_channel
from .sources.notify import NotifySource
from .sources.persistent import PersistentNotificationSource
from .sources.speech import SpeechSource
from .sources.telegram import TelegramSource
from .store import NewerSchemaError, NotificationStore
from .websocket_api import async_register

PURGE_INTERVAL = timedelta(days=1)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class RuntimeData:
    """What the integration holds while it is loaded."""

    store: NotificationStore


type NotificationJournalConfigEntry = ConfigEntry[RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the WebSocket commands and the panel's scripts."""
    async_register(hass)
    async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NotificationJournalConfigEntry) -> bool:
    """Set up the integration from its config entry."""
    options = {**DEFAULT_OPTIONS, **entry.options}
    store = NotificationStore(hass.config.path(DATABASE_FILE))
    try:
        await store.async_open()
    except NewerSchemaError as err:
        await store.async_close()
        raise ConfigEntryError(str(err)) from err
    entry.runtime_data = RuntimeData(store=store)

    retention_days = int(options[CONF_RETENTION_DAYS])
    max_entries = int(options[CONF_MAX_ENTRIES])
    await store.async_purge(retention_days, max_entries)

    @callback
    def _purge(_now: datetime) -> None:
        entry.async_create_background_task(
            hass, store.async_purge(retention_days, max_entries), "notification_journal purge"
        )

    entry.async_on_unload(async_track_time_interval(hass, _purge, PURGE_INTERVAL))

    excluded = {qualify_channel(channel) for channel in options[CONF_EXCLUDED_CHANNELS]}
    if options[CONF_RECORD_NOTIFY]:
        entry.async_on_unload(NotifySource(hass, store, excluded_channels=excluded).async_start())
    if options[CONF_RECORD_SPEECH]:
        entry.async_on_unload(SpeechSource(hass, store, excluded_channels=excluded).async_start())
    if options[CONF_RECORD_TELEGRAM]:
        entry.async_on_unload(TelegramSource(hass, store, excluded_channels=excluded).async_start())
    if options[CONF_RECORD_PERSISTENT]:
        entry.async_on_unload(await PersistentNotificationSource(hass, store).async_start())

    async_register_panel(
        hass,
        require_admin=options[CONF_NON_ADMIN_VISIBILITY] == Visibility.NONE,
        show_in_sidebar=bool(options[CONF_SHOW_IN_SIDEBAR]),
        title=options.get(CONF_PANEL_TITLE),
        icon=options.get(CONF_PANEL_ICON),
    )
    entry.async_on_unload(lambda: async_remove_panel(hass))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NotificationJournalConfigEntry) -> bool:
    """Unload the config entry; listeners are removed before the store closes."""
    await entry.runtime_data.store.async_close()
    return True


async def _async_options_updated(hass: HomeAssistant, entry: NotificationJournalConfigEntry) -> None:
    """Reload the entry so changed options take effect."""
    await hass.config_entries.async_reload(entry.entry_id)
