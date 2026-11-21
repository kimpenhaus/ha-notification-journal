"""Send a recorded notification again to targets an administrator picks: notify entities and actions, text-to-speech
on media players, announcements on voice satellites."""

from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .models import NotificationRecord
from .recipients import NOTIFY_DOMAIN, SEND_MESSAGE, companion_channels, mobile_app_entry, phone_name
from .sources import ATTR_MESSAGE, ATTR_TITLE
from .sources.speech import ATTR_MEDIA_PLAYERS, MEDIA_PLAYER_DOMAIN, SATELLITE_DOMAIN, TTS_DOMAIN

NOTIFY_ENTITY = "notify_entity"
NOTIFY_ACTION = "notify_action"
SPEAK = "speak"
ANNOUNCE = "announce"
NOT_A_TARGET = {SEND_MESSAGE, "persistent_notification"}
"""Notify actions that are no target of their own: send_message takes entities, the bell is not a medium to pick."""

TARGET = vol.Any(
    {vol.Required("kind"): NOTIFY_ENTITY, vol.Required("entity_id"): cv.entity_domain(NOTIFY_DOMAIN)},
    {vol.Required("kind"): NOTIFY_ACTION, vol.Required("service"): vol.All(cv.slug, vol.NotIn(NOT_A_TARGET))},
    {
        vol.Required("kind"): SPEAK,
        vol.Required("engine"): cv.entity_domain(TTS_DOMAIN),
        vol.Required("entity_id"): cv.entity_domain(MEDIA_PLAYER_DOMAIN),
    },
    {vol.Required("kind"): ANNOUNCE, vol.Required("entity_id"): cv.entity_domain(SATELLITE_DOMAIN)},
)


@dataclass(frozen=True, slots=True)
class SendCall:
    """One action call that sends a notification to one target."""

    domain: str
    service: str
    data: dict[str, Any]


def targets(hass: HomeAssistant, record: NotificationRecord | None) -> dict[str, Any]:
    """What a notification can be sent to, by kind, each named as Home Assistant shows it, and whether the Companion
    app's actions get the notification's data too. A phone with the Companion app's action is listed once, by that
    action: its notify entity sends only title and message."""
    companion = companion_channels(hass)
    services = [
        service for service in hass.services.async_services_for_domain(NOTIFY_DOMAIN) if service not in NOT_A_TARGET
    ]
    phones = {
        service: mobile_app_entry(hass, service) for service in services if f"{NOTIFY_DOMAIN}.{service}" in companion
    }
    registry = er.async_get(hass)
    phone_entities = {
        entity.entity_id
        for entry in phones.values()
        if entry
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    actions = [_action(hass, service, phones) for service in services]
    return {
        NOTIFY_ENTITY: _entities(hass, NOTIFY_DOMAIN, phone_entities),
        NOTIFY_ACTION: sorted(actions, key=lambda action: action["name"].casefold()),
        "engines": _entities(hass, TTS_DOMAIN),
        SPEAK: _entities(hass, MEDIA_PLAYER_DOMAIN),
        ANNOUNCE: _entities(hass, SATELLITE_DOMAIN),
        "same_medium": record is not None and same_medium(hass, record),
    }


def same_medium(hass: HomeAssistant, record: NotificationRecord) -> bool:
    """Whether a notification went through the Companion app, so its actions get image, buttons and tag again."""
    return record.source == NOTIFY_DOMAIN and bool(companion_channels(hass) & record.devices)


def titled(record: NotificationRecord, message: str) -> dict[str, Any]:
    """The message of a notify call, with the notification's title if it has one."""
    return {ATTR_MESSAGE: message, **({ATTR_TITLE: record.title} if record.title else {})}


def calls(hass: HomeAssistant, record: NotificationRecord, chosen: list[dict[str, Any]]) -> list[SendCall]:
    """The calls that send a notification to each chosen target: text only, except a Companion app action for a
    notification that went through the Companion app, which keeps its data (image, buttons, tag)."""
    companion = companion_channels(hass)
    with_data = same_medium(hass, record)
    text = record.spoken_text or record.message
    found = []
    for target in chosen:
        kind = target["kind"]
        if kind == NOTIFY_ENTITY:
            found.append(
                SendCall(NOTIFY_DOMAIN, SEND_MESSAGE, {**titled(record, text), ATTR_ENTITY_ID: target["entity_id"]})
            )
        elif kind == NOTIFY_ACTION:
            service = target["service"]
            if with_data and f"{NOTIFY_DOMAIN}.{service}" in companion:
                data = {**titled(record, record.message), **deepcopy(record.data or {})}
                found.append(SendCall(NOTIFY_DOMAIN, service, data))
            else:
                found.append(SendCall(NOTIFY_DOMAIN, service, titled(record, text)))
        elif kind == SPEAK:
            data = {ATTR_ENTITY_ID: target["engine"], ATTR_MEDIA_PLAYERS: target["entity_id"], ATTR_MESSAGE: text}
            found.append(SendCall(TTS_DOMAIN, "speak", data))
        else:
            data = {ATTR_ENTITY_ID: target["entity_id"], ATTR_MESSAGE: text}
            found.append(SendCall(SATELLITE_DOMAIN, ANNOUNCE, data))
    return found


def _action(hass: HomeAssistant, service: str, phones: dict[str, ConfigEntry | None]) -> dict[str, Any]:
    """A legacy notify action, the Companion app's named after its phone."""
    entry = phones.get(service)
    name = (phone_name(hass, entry) if entry else "") or service
    return {"service": service, "name": name, "companion": service in phones}


def _entities(hass: HomeAssistant, domain: str, skip: Collection[str] = ()) -> list[dict[str, str]]:
    """The available entities of a domain by name, without those to skip."""
    states: list[State] = sorted(hass.states.async_all(domain), key=lambda state: state.name.casefold())
    return [
        {"entity_id": state.entity_id, "name": state.name}
        for state in states
        if state.state != "unavailable" and state.entity_id not in skip
    ]
