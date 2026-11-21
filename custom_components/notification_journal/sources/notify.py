"""Record the calls of notify actions."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import target

from ..models import (
    CHANNEL_SEPARATOR,
    SPOKEN_MESSAGE,
    Answer,
    Call,
    NotificationRecord,
    Recipient,
    Status,
    tag_of,
)
from ..origin import resolve_origin
from ..recipients import (
    NOTIFY_DOMAIN,
    SEND_MESSAGE,
    RecipientResolver,
    companion_channels,
    entity_group_members,
    legacy_group_members,
)
from ..store import NotificationStore, TagClose
from . import ATTR_MESSAGE, ATTR_TITLE, TARGET_KEYS, Listener, Resend, as_list, new_record, sending_again

GROUP_CALL_WINDOW = 5.0
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
"""Fired by the Companion app when someone taps a button of a notification; its context carries their user."""
ATTR_ACTION = "action"
ATTR_REPLY_TEXT = "reply_text"
CLEAR_NOTIFICATION = "clear_notification"
"""The message that makes the Companion app remove the notification with the same tag."""
COMMANDS = frozenset(
    {
        "clear_badge",
        "delete_alert",
        "remove_channel",
        "request_location_update",
        "update_complications",
        "update_widgets",
    }
)
"""Messages that make the Companion app do something instead of showing a notification."""
PREFIXED_COMMAND = re.compile(r"(command|kiosk)_[a-z_]+")
"""The commands of the Companion app on Android (`command_*`) and in kiosk mode on iOS (`kiosk_*`)."""


@dataclass(frozen=True, slots=True)
class _GroupCall:
    record_id: str | None
    """None when the group is excluded: its member calls are dropped too."""
    members: frozenset[str]
    context_id: str
    message: str
    started: float
    entity_group: bool
    """A notify group entity calls its members in its own context, a legacy group in a new one."""


_group_call: ContextVar[_GroupCall | None] = ContextVar("notification_journal_group_call", default=None)


@contextmanager
def resend(context_id: str, record_id: str) -> Iterator[Resend]:
    """Record the call made in a context as sending a notification again, apart from any group call before."""
    _group_call.set(None)
    with sending_again(context_id, record_id) as entry:
        yield entry


@dataclass(frozen=True, slots=True)
class SentCall:
    record_id: str
    channel: str


current_call: ContextVar[SentCall | None] = ContextVar("notification_journal_current_call", default=None)
"""Set while a recorded call runs: the action runs in the same asyncio context, so what it logs belongs to the call."""


class NotifySource:
    """Record every call of a notify action, legacy actions and notify entities alike.

    A group calls the action of each member itself, right after its own call and in the same
    asyncio context; those calls are attached to the group's record instead of becoming records.
    A button someone taps in the Companion app is attached to the record that offered it. A notification
    with a tag replaces the earlier ones with that tag on the Companion app's devices it reaches;
    `clear_notification` with a tag withdraws them there; like the commands to the Companion app, it is no
    record of its own unless it also reaches another service, which gets it as text.
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

    def listeners(self) -> list[Listener]:
        """The calls of notify actions and the answers to their buttons."""
        return [(EVENT_CALL_SERVICE, self._handle, _is_notify), (EVENT_NOTIFICATION_ACTION, self._handle_answer, None)]

    async def _handle_answer(self, event: Event) -> None:
        action = event.data.get(ATTR_ACTION)
        if not action or not isinstance(action, str):
            return
        reply = event.data.get(ATTR_REPLY_TEXT)
        answer = Answer(
            action=action,
            time=event.time_fired,
            user_id=event.context.user_id,
            reply_text=str(reply) if reply else None,
        )
        await self._store.async_add_answer(self.name, answer)

    @callback
    def _handle(self, event: Event) -> None:
        current_call.set(None)
        service: str = event.data["service"]
        data: dict[str, Any] = dict(event.data.get("service_data") or {})
        channels = self._channels(service, data)
        if not channels:
            return
        message = str(data.get(ATTR_MESSAGE, ""))
        excluded = bool(self._excluded.intersection(channels))

        if (parent := _group_call.get()) is not None and self._is_inner_call(parent, event, channels, message):
            if parent.record_id is not None and not excluded:
                for channel in channels:
                    call = Call(
                        channel=channel,
                        recipients=self._recipients(service, [channel]),
                        context_id=event.context.id,
                        group=self._is_group(service, channel),
                    )
                    self._store.add_inner_call(parent.record_id, call)
                _track(parent.record_id, channels)
            return

        members = self._group_members(service, channels)
        command = message in COMMANDS or PREFIXED_COMMAND.fullmatch(message) is not None
        tag = None if excluded or command or message == SPOKEN_MESSAGE else tag_of(data)
        companion = companion_channels(self._hass) if tag is not None or command else frozenset()
        reached = companion.intersection(members if members is not None else channels)
        withdraw = bool(reached) and message == CLEAR_NOTIFICATION
        silent = (withdraw or command) and bool(reached) and companion.issuperset(self._ends(members, channels))
        record = None
        if not excluded and not silent:
            record = self._record(event, service, data, channels, group=channels[0] if members is not None else None)
        if tag is not None and reached:
            self._store.close_tagged(
                TagClose(
                    source=self.name,
                    tag=tag,
                    devices=reached,
                    companion=companion,
                    status=Status.WITHDRAWN if withdraw else Status.REPLACED,
                    time=event.time_fired,
                    by=record.origin if record is not None else resolve_origin(self._hass, event.context),
                )
            )
        if record is not None:
            self._store.add(record)
            _track(record.id, channels)
        if members is not None:
            _group_call.set(
                _GroupCall(
                    record_id=record.id if record is not None else None,
                    members=frozenset(members),
                    context_id=event.context.id,
                    message=message,
                    started=event.time_fired_timestamp,
                    entity_group=service == SEND_MESSAGE,
                )
            )

    def _channels(self, service: str, data: dict[str, Any]) -> list[str]:
        """Return the legacy action, or the notify entities a send_message call targets, areas and labels resolved."""
        if service != SEND_MESSAGE:
            return [f"{NOTIFY_DOMAIN}.{service}"]
        explicit = [str(entity_id) for entity_id in as_list(data.get(ATTR_ENTITY_ID))]
        selected = target.async_extract_referenced_entity_ids(
            self._hass,
            target.TargetSelection({key: data[key] for key in TARGET_KEYS if key in data}),
            expand_group=False,
        )
        indirect = sorted(
            entity_id
            for entity_id in selected.indirectly_referenced
            if entity_id.startswith(f"{NOTIFY_DOMAIN}.") and entity_id not in explicit
        )
        return explicit + indirect

    def _record(
        self, event: Event, service: str, data: dict[str, Any], channels: list[str], *, group: str | None
    ) -> NotificationRecord:
        recipients = self._recipients(service, channels)
        extra = {key: value for key, value in data.items() if key not in (ATTR_MESSAGE, ATTR_TITLE, *TARGET_KEYS)}
        return new_record(
            self._hass,
            event,
            source=self.name,
            channel=CHANNEL_SEPARATOR.join(channels),
            title=data.get(ATTR_TITLE),
            message=str(data.get(ATTR_MESSAGE, "")),
            data=extra,
            recipients=recipients,
            group=group,
        )

    def _recipients(self, service: str, channels: list[str]) -> list[Recipient]:
        if service == SEND_MESSAGE:
            return self._resolver.for_entities(channels)
        return self._resolver.for_service(service)

    def _is_group(self, service: str, channel: str) -> bool:
        if service == SEND_MESSAGE:
            return entity_group_members(self._hass, channel) is not None
        return legacy_group_members(self._hass, service) is not None

    def _ends(self, members: list[str] | None, channels: list[str]) -> list[str]:
        """The channels of a legacy action's call that are no groups: the action, or the members of its group."""
        if members is None:
            return channels
        return [m for m in members if legacy_group_members(self._hass, m.removeprefix(f"{NOTIFY_DOMAIN}.")) is None]

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
            (event.context.id != parent.context_id or parent.entity_group)
            and parent.members.issuperset(channels)
            and message == parent.message
            and event.time_fired_timestamp - parent.started < GROUP_CALL_WINDOW
        )


def _track(record_id: str, channels: list[str]) -> None:
    if len(channels) == 1:
        current_call.set(SentCall(record_id, channels[0]))


@callback
def _is_notify(event_data: dict[str, Any]) -> bool:
    return event_data.get("domain") == NOTIFY_DOMAIN
