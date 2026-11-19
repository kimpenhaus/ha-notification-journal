"""Resolve the target of a notify call into the people and channels it reaches."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .models import Recipient, RecipientKind

NOTIFY_DOMAIN = "notify"
NOTIFY_SERVICES_KEY = "notify_services"
GROUP_PLATFORM = "group"
MOBILE_APP_DOMAIN = "mobile_app"
PERSON_DOMAIN = "person"
ATTR_USER_ID = "user_id"
ATTR_WEBHOOK_ID = "webhook_id"
ATTR_DEVICE_NAME = "device_name"
GROUP_MEMBER_KEYS = ("action", "service")
SEND_MESSAGE = "send_message"


def qualify_channel(channel: str) -> str:
    """Return a channel with its domain; older options name a notify action without it."""
    return channel if "." in channel else f"{NOTIFY_DOMAIN}.{channel}"


def excludable_channels(hass: HomeAssistant) -> set[str]:
    """Return what the exclusion list can name: notify actions and entities, media players and voice satellites."""
    services = hass.services.async_services_for_domain(NOTIFY_DOMAIN)
    return {
        *(f"{NOTIFY_DOMAIN}.{service}" for service in services if service != SEND_MESSAGE),
        *hass.states.async_entity_ids((NOTIFY_DOMAIN, "media_player", "assist_satellite")),
    }


def _people(hass: HomeAssistant) -> dict[str, Recipient]:
    people: dict[str, Recipient] = {}
    for state in hass.states.async_all(PERSON_DOMAIN):
        if user_id := state.attributes.get(ATTR_USER_ID):
            people[user_id] = Recipient(
                kind=RecipientKind.PERSON,
                id=state.entity_id,
                name=state.name,
                picture=state.attributes.get("entity_picture"),
                user_id=user_id,
            )
    return people


def _legacy_services(hass: HomeAssistant) -> Iterable[tuple[str, Any]]:
    for platform, services in hass.data.get(NOTIFY_SERVICES_KEY, {}).items():
        for service in services:
            yield platform, service


def _legacy_group_entries(hass: HomeAssistant, service: str) -> list[tuple[str, dict[str, Any]]] | None:
    """Return the members of a legacy notify group with their configuration, or None if the action is no group."""
    for platform, notify_service in _legacy_services(hass):
        if platform != GROUP_PLATFORM or getattr(notify_service, "_service_name", None) != service:
            continue
        entries = []
        for entry in getattr(notify_service, "entities", []):
            if name := next((entry[key] for key in GROUP_MEMBER_KEYS if key in entry), None):
                entries.append((name, entry))
        return entries
    return None


def legacy_group_members(hass: HomeAssistant, service: str) -> list[str] | None:
    """Return the member actions of a legacy notify group, or None if the action is no group."""
    entries = _legacy_group_entries(hass, service)
    return None if entries is None else [name for name, _ in entries]


def member_defaults(
    hass: HomeAssistant, group: str, member: str, seen: frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    """Return the data each legacy group on the way from a group to one of its members adds to the member's call,
    the outer group first; empty when the member is not in the group."""
    if group in seen:
        return []
    for name, entry in _legacy_group_entries(hass, group) or []:
        own = [entry["data"]] if isinstance(entry.get("data"), dict) else []
        if name == member:
            return own
        if inner := member_defaults(hass, name, member, seen | {group}):
            return own + inner
    return []


def entity_group_members(hass: HomeAssistant, entity_id: str) -> list[str] | None:
    """Return the members of a notify group entity, or None if the entity is no group."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    members = state.attributes.get(ATTR_ENTITY_ID)
    return list(members) if isinstance(members, list | tuple) else None


def entity_recipient(hass: HomeAssistant, entity_id: str, kind: RecipientKind) -> Recipient:
    """Return an entity as a recipient, named as Home Assistant shows it."""
    state = hass.states.get(entity_id)
    return Recipient(kind=kind, id=entity_id, name=state.name if state else entity_id)


def mobile_app_entry(hass: HomeAssistant, service: str) -> ConfigEntry | None:
    """Return the Companion app's config entry behind a legacy notify action such as mobile_app_phone."""
    for platform, notify_service in _legacy_services(hass):
        if platform != MOBILE_APP_DOMAIN:
            continue
        webhook_id = getattr(notify_service, "registered_targets", {}).get(service)
        if webhook_id is None:
            continue
        for entry in hass.config_entries.async_entries(MOBILE_APP_DOMAIN):
            if entry.data.get(ATTR_WEBHOOK_ID) == webhook_id:
                return entry
    return None


class RecipientResolver:
    """Turn notify actions and notify entities into recipients."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Bind the resolver to Home Assistant."""
        self._hass = hass

    def for_service(self, service: str) -> list[Recipient]:
        """Resolve a legacy notify action such as notify.mobile_app_phone, groups included."""
        return self._dedupe(self._service(service, set(), _people(self._hass)))

    def for_entities(self, entity_ids: Iterable[str]) -> list[Recipient]:
        """Resolve notify entities, groups included."""
        people = _people(self._hass)
        found: list[Recipient] = []
        for entity_id in entity_ids:
            found.extend(self._entity(entity_id, set(), people))
        return self._dedupe(found)

    def _service(self, service: str, seen: set[str], people: dict[str, Recipient]) -> list[Recipient]:
        if service in seen:
            return []
        seen.add(service)
        if (members := legacy_group_members(self._hass, service)) is not None:
            return [r for member in members for r in self._service(member, seen, people)]
        entry = mobile_app_entry(self._hass, service)
        if entry and entry.data.get(ATTR_USER_ID) in people:
            return [people[entry.data[ATTR_USER_ID]]]
        name = (entry.data.get(ATTR_DEVICE_NAME) if entry else None) or service
        return [Recipient(kind=RecipientKind.CHANNEL, id=f"{NOTIFY_DOMAIN}.{service}", name=name.strip())]

    def _entity(self, entity_id: str, seen: set[str], people: dict[str, Recipient]) -> list[Recipient]:
        if entity_id in seen:
            return []
        seen.add(entity_id)
        if (members := entity_group_members(self._hass, entity_id)) is not None:
            return [r for member in members for r in self._entity(member, seen, people)]
        entry = er.async_get(self._hass).async_get(entity_id)
        if entry and entry.config_entry_id:
            config_entry = self._hass.config_entries.async_get_entry(entry.config_entry_id)
            user_id = config_entry.data.get(ATTR_USER_ID) if config_entry else None
            if config_entry and config_entry.domain == MOBILE_APP_DOMAIN and user_id in people:
                return [people[user_id]]
        return [entity_recipient(self._hass, entity_id, RecipientKind.ENTITY)]

    @staticmethod
    def _dedupe(recipients: list[Recipient]) -> list[Recipient]:
        unique: dict[tuple[RecipientKind, str], Recipient] = {}
        for recipient in recipients:
            unique.setdefault((recipient.kind, recipient.id), recipient)
        return list(unique.values())
