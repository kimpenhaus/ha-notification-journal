"""Send a recorded notification again to targets an administrator picks: notify entities and actions, text-to-speech
on media players, announcements on voice satellites."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import config_validation as cv

from .models import NotificationRecord
from .recipients import NOTIFY_DOMAIN, SEND_MESSAGE, companion_channels, mobile_app_entry
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
    {vol.Required("kind"): NOTIFY_ACTION, vol.Required("service"): cv.slug},
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


def targets(hass: HomeAssistant) -> dict[str, list[dict[str, Any]]]:
    """What a notification can be sent to, by kind, each named as Home Assistant shows it."""
    companion = companion_channels(hass)
    actions = sorted(
        service for service in hass.services.async_services_for_domain(NOTIFY_DOMAIN) if service not in NOT_A_TARGET
    )
    return {
        NOTIFY_ENTITY: _entities(hass, NOTIFY_DOMAIN),
        NOTIFY_ACTION: [_action(hass, service, f"{NOTIFY_DOMAIN}.{service}" in companion) for service in actions],
        "engines": _entities(hass, TTS_DOMAIN),
        SPEAK: _entities(hass, MEDIA_PLAYER_DOMAIN),
        ANNOUNCE: _entities(hass, SATELLITE_DOMAIN),
    }


def calls(hass: HomeAssistant, record: NotificationRecord, chosen: list[dict[str, Any]]) -> list[SendCall]:
    """The calls that send a notification to each chosen target: text only, except a Companion app action for a
    notification that went through the Companion app, which keeps its data (image, buttons, tag)."""
    companion = companion_channels(hass)
    reached = {*record.channels, *(call.channel for call in record.inner_calls)}
    same_medium = record.source == NOTIFY_DOMAIN and bool(companion.intersection(reached))
    text = record.spoken_text or record.message
    titled = {ATTR_MESSAGE: text, **({ATTR_TITLE: record.title} if record.title else {})}
    found = []
    for target in chosen:
        kind = target["kind"]
        if kind == NOTIFY_ENTITY:
            found.append(SendCall(NOTIFY_DOMAIN, SEND_MESSAGE, {**titled, ATTR_ENTITY_ID: target["entity_id"]}))
        elif kind == NOTIFY_ACTION:
            service = target["service"]
            if same_medium and f"{NOTIFY_DOMAIN}.{service}" in companion:
                data = {ATTR_MESSAGE: record.message, **({ATTR_TITLE: record.title} if record.title else {})}
                found.append(SendCall(NOTIFY_DOMAIN, service, {**data, **deepcopy(record.data or {})}))
            else:
                found.append(SendCall(NOTIFY_DOMAIN, service, titled))
        elif kind == SPEAK:
            data = {ATTR_ENTITY_ID: target["engine"], ATTR_MEDIA_PLAYERS: target["entity_id"], ATTR_MESSAGE: text}
            found.append(SendCall(TTS_DOMAIN, "speak", data))
        else:
            data = {ATTR_ENTITY_ID: target["entity_id"], ATTR_MESSAGE: text}
            found.append(SendCall(SATELLITE_DOMAIN, ANNOUNCE, data))
    return found


def _action(hass: HomeAssistant, service: str, companion: bool) -> dict[str, Any]:
    """A legacy notify action, named after the phone for the Companion app's."""
    entry = mobile_app_entry(hass, service) if companion else None
    return {"service": service, "name": entry.title if entry else service, "companion": companion}


def _entities(hass: HomeAssistant, domain: str) -> list[dict[str, str]]:
    states: list[State] = sorted(hass.states.async_all(domain), key=lambda state: state.name.casefold())
    return [{"entity_id": state.entity_id, "name": state.name} for state in states if state.state != "unavailable"]
