"""Sensors with today's numbers: notifications, and those that failed in whole or in part."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import NotificationJournalConfigEntry
from .const import DOMAIN
from .statistics import COUNT_COLUMNS
from .today import TodayCounts

SENSORS = {"notifications_today": "notifications", "failed_today": "failed"}
"""Each sensor's key and the column of the counts it shows."""


async def async_setup_entry(
    hass: HomeAssistant, entry: NotificationJournalConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the sensors."""
    async_add_entities(TodaySensor(entry.runtime_data.counts, entry, key, column) for key, column in SENSORS.items())


class TodaySensor(CoordinatorEntity[TodayCounts], SensorEntity):
    """One of today's counts; it starts again at zero at local midnight."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, counts: TodayCounts, entry: NotificationJournalConfigEntry, key: str, column: str) -> None:
        """Show one column of the counts."""
        super().__init__(counts)
        self._column = COUNT_COLUMNS.index(column)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, entry_type=DeviceEntryType.SERVICE, translation_key="journal"
        )

    @property
    def native_value(self) -> int:
        """The count."""
        return self.coordinator.data[self._column]

    @property
    def last_reset(self) -> datetime:
        """Local midnight."""
        return dt_util.start_of_local_day()
