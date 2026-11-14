"""Record the calls of notify actions."""

from __future__ import annotations

import json
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from ..models import Call, NotificationRecord, Recipient
from ..origin import resolve_origin
from ..recipients import (
    NOTIFY_DOMAIN,
    SEND_MESSAGE,
    RecipientResolver,
    entity_group_members,
    legacy_group_members,
)
from ..store import NotificationStore

ATTR_MESSAGE = "message"
ATTR_TITLE = "title"
GROUP_CALL_WINDOW = 5.0


@dataclass(frozen=True, slots=True)
class _GroupCall:
    record_id: str
    members: frozenset[str]
    context_id: str
    message: str
    started: float


_group_call: ContextVar[_GroupCall | None] = ContextVar("notification_journal_group_call", default=None)


def _channels(service: str, data: dict[str, Any]) -> list[str]:
    if service != SEND_MESSAGE:
        return [f"{NOTIFY_DOMAIN}.{service}"]
    entity_ids = data.get(ATTR_ENTITY_ID) or []
    return [entity_ids] if isinstance(entity_ids, str) else list(entity_ids)


def _plain(data: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(data, default=str))


class NotifySource:
    """Record every call of a notify action, legacy actions and notify entities alike.

    A group calls the action of each member itself, right after its own call and in the same
    asyncio context; those calls are attached to the group's record instead of becoming records.
    """

    name = NOTIFY_DOMAIN

    def __init__(
        self,
        hass: HomeAssistant,
        store: NotificationStore,
        *,
        excluded_channels: set[str],
    ) -> None:
        """Bind the source to Home Assistant and the store."""
        self._hass = hass
        self._store = store
        self._excluded = excluded_channels
        self._resolver = RecipientResolver(hass)

    def async_start(self) -> CALLBACK_TYPE:
        """Listen to the calls of notify actions."""
        return self._hass.bus.async_listen(EVENT_CALL_SERVICE, self._handle, event_filter=_is_notify)

    @callback
    def _handle(self, event: Event) -> None:
        service: str = event.data["service"]
        data: dict[str, Any] = dict(event.data.get("service_data") or {})
        channels = _channels(service, data)
        if not channels or self._excluded.intersection(channels):
            return
        message = str(data.get(ATTR_MESSAGE, ""))

        if (parent := _group_call.get()) is not None and self._is_inner_call(parent, event, channels, message):
            recipients = self._recipients(service, channels)
            for channel in channels:
                self._store.add_inner_call(
                    parent.record_id, Call(channel=channel, recipients=recipients, context_id=event.context.id)
                )
            return

        record = self._record(event, service, data, channels, message)
        self._store.add(record)
        if (members := self._group_members(service, channels)) is not None:
            _group_call.set(
                _GroupCall(
                    record_id=record.id,
                    members=frozenset(members),
                    context_id=event.context.id,
                    message=message,
                    started=time.monotonic(),
                )
            )

    def _record(
        self, event: Event, service: str, data: dict[str, Any], channels: list[str], message: str
    ) -> NotificationRecord:
        recipients = self._recipients(service, channels)
        extra = {key: value for key, value in data.items() if key not in (ATTR_MESSAGE, ATTR_TITLE, ATTR_ENTITY_ID)}
        group = channels[0] if self._group_members(service, channels) is not None else None
        return NotificationRecord(
            id=ulid_now(),
            time=dt_util.utcnow(),
            source=self.name,
            channel=", ".join(channels),
            title=data.get(ATTR_TITLE),
            message=message,
            data=_plain(extra) if extra else None,
            recipients=recipients,
            origin=resolve_origin(self._hass, event.context),
            context_id=event.context.id,
            group=group,
        )

    def _recipients(self, service: str, channels: list[str]) -> list[Recipient]:
        if service == SEND_MESSAGE:
            return self._resolver.for_entities(channels)
        return self._resolver.for_service(service)

    def _group_members(self, service: str, channels: list[str]) -> list[str] | None:
        """Return every channel a group reaches, nested groups included, or None for no group."""
        if service != SEND_MESSAGE:
            lookup, start, prefix = legacy_group_members, service, f"{NOTIFY_DOMAIN}."
        elif len(channels) == 1:
            lookup, start, prefix = entity_group_members, channels[0], ""
        else:
            return None
        if lookup(self._hass, start) is None:
            return None
        found: list[str] = []
        pending = [start]
        while pending:
            for member in lookup(self._hass, pending.pop()) or []:
                if f"{prefix}{member}" not in found:
                    found.append(f"{prefix}{member}")
                    pending.append(member)
        return found

    @staticmethod
    def _is_inner_call(parent: _GroupCall, event: Event, channels: list[str], message: str) -> bool:
        return (
            event.context.id != parent.context_id
            and parent.members.issuperset(channels)
            and message == parent.message
            and time.monotonic() - parent.started < GROUP_CALL_WINDOW
        )


@callback
def _is_notify(event_data: dict[str, Any]) -> bool:
    return event_data.get("domain") == NOTIFY_DOMAIN
