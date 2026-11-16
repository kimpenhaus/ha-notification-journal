"""Record the notifications Home Assistant sends and show them in a panel."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

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
    CONF_STATISTICS_YEARS,
    DATABASE_FILE,
    DEFAULT_OPTIONS,
    DOMAIN,
    SIGNAL_CHANGED,
    Visibility,
)
from .importer import async_import
from .panel import async_register_frontend, async_register_panel, async_remove_panel
from .recipients import qualify_channel
from .sources import EventSource
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
    stop: list[CALLBACK_TYPE] = field(default_factory=list)
    """What feeds the store: the sources, the purge timer and the change forwarding, stopped before it closes."""


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
    runtime = RuntimeData(store=store)
    try:
        sources = _start(hass, entry, store, runtime.stop, options)
        if options[CONF_RECORD_PERSISTENT]:
            runtime.stop.append(await PersistentNotificationSource(hass, store).async_start())
    except Exception:
        _stop(runtime)
        await store.async_close()
        raise
    entry.runtime_data = runtime
    if store.created:
        entry.async_create_background_task(
            hass, async_import(hass, sources, dt_util.utcnow()), "notification_journal recorder import"
        )

    async_register_panel(
        hass,
        require_admin=options[CONF_NON_ADMIN_VISIBILITY] == Visibility.NONE,
        show_in_sidebar=bool(options[CONF_SHOW_IN_SIDEBAR]),
        title=options.get(CONF_PANEL_TITLE),
        icon=options.get(CONF_PANEL_ICON),
    )
    entry.async_on_unload(lambda: async_remove_panel(hass))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NotificationJournalConfigEntry) -> bool:
    """Unload the config entry: stop everything that writes to the store, then close it."""
    _stop(entry.runtime_data)
    await entry.runtime_data.store.async_close()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: NotificationJournalConfigEntry) -> None:
    """Remove the journal with the integration, so a new setup starts empty and imports from the recorder again."""
    await hass.async_add_executor_job(_remove_database, Path(hass.config.path(DATABASE_FILE)))


def _remove_database(database: Path) -> None:
    """Delete the database, its WAL and SHM files and the copies made before migrations."""
    own = re.compile(rf"{re.escape(database.name)}(-wal|-shm|\.bak-v\d+)?")
    for path in database.parent.iterdir():
        if own.fullmatch(path.name):
            path.unlink(missing_ok=True)


def _start(
    hass: HomeAssistant,
    entry: NotificationJournalConfigEntry,
    store: NotificationStore,
    stop: list[CALLBACK_TYPE],
    options: dict,
) -> list[EventSource]:
    """Start the purge, the forwarding of changes to subscribers and the event sources; return the sources."""
    retention_days = int(options[CONF_RETENTION_DAYS])
    max_entries = int(options[CONF_MAX_ENTRIES])
    statistics_years = int(options[CONF_STATISTICS_YEARS])

    @callback
    def _purge(_now: datetime | None = None) -> None:
        entry.async_create_background_task(
            hass, store.async_purge(retention_days, max_entries, statistics_years), "notification_journal purge"
        )

    async def _publish(change: str, record_id: str) -> None:
        record = None
        if change in ("added", "updated"):
            try:
                record = await store.async_get(record_id)
            except RuntimeError:
                return
            if record is None:
                return
        async_dispatcher_send(hass, SIGNAL_CHANGED, change, record_id, record)

    @callback
    def _changed(change: str, record_id: str) -> None:
        entry.async_create_background_task(hass, _publish(change, record_id), "notification_journal change")

    stop.append(store.async_add_listener(_changed))
    _purge()
    stop.append(async_track_time_interval(hass, _purge, PURGE_INTERVAL))
    excluded = {qualify_channel(channel) for channel in options[CONF_EXCLUDED_CHANNELS]}
    sources: list[EventSource] = []
    for option, source in (
        (CONF_RECORD_NOTIFY, NotifySource),
        (CONF_RECORD_SPEECH, SpeechSource),
        (CONF_RECORD_TELEGRAM, TelegramSource),
    ):
        if options[option]:
            sources.append(source(hass, store, excluded_channels=excluded))
    for started in sources:
        stop.append(started.async_start())
    return sources


def _stop(runtime: RuntimeData) -> None:
    while runtime.stop:
        runtime.stop.pop()()
