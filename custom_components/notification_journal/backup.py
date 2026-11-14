"""Keep the database consistent while Home Assistant creates a backup."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN


def _stores(hass: HomeAssistant) -> list:
    return [entry.runtime_data.store for entry in hass.config_entries.async_loaded_entries(DOMAIN)]


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Write pending notifications to the database file and hold new ones."""
    for store in _stores(hass):
        await store.async_pause_for_backup()


async def async_post_backup(hass: HomeAssistant) -> None:
    """Record again."""
    for store in _stores(hass):
        store.resume_after_backup()
