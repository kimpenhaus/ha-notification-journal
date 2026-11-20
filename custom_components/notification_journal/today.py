"""Today's counts of every notification, for the sensors."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_CHANGED
from .statistics import Counts
from .store import NotificationStore

_LOGGER = logging.getLogger(__name__)


class TodayCounts(DataUpdateCoordinator[Counts]):
    """Today's counts from the statistics, read again after each change of the journal and at midnight."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: NotificationStore) -> None:
        """Bind the counts to the store."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self._store = store

    async def _async_update_data(self) -> Counts:
        return await self._store.async_counts_since(dt_util.start_of_local_day())

    @callback
    def follow(self) -> list[CALLBACK_TYPE]:
        """Read the counts again after every change and at midnight; return the stoppers."""
        return [
            async_dispatcher_connect(self.hass, SIGNAL_CHANGED, self._async_changed),
            async_track_time_change(self.hass, self._async_midnight, hour=0, minute=0, second=0),
        ]

    async def _async_changed(self, *_: object) -> None:
        await self.async_request_refresh()

    async def _async_midnight(self, _now: datetime) -> None:
        await self.async_refresh()
