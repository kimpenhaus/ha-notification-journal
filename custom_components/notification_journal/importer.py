"""Import, once on first setup, the notifications the recorder still holds.

The recorder keeps the events of the last days (10 by default), service calls among them. Replaying the calls of
notify actions, spoken announcements and Telegram, and the answers to buttons, through the same listeners that
record them live rebuilds those notifications: recipients, notify groups and answers alike. Their origin comes from
the recorded contexts, as the call stack and the traces of that time are gone.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from homeassistant.components.recorder.models import bytes_to_uuid_hex_or_none
from homeassistant.const import ATTR_ENTITY_ID, ATTR_NAME, EVENT_CALL_SERVICE
from homeassistant.core import Context, Event, EventOrigin, HomeAssistant
from homeassistant.helpers.recorder import get_instance, session_scope
from homeassistant.util.json import json_loads_object
from homeassistant.util.ulid import bytes_to_ulid_or_none
from sqlalchemy import text

from .models import Origin, OriginKind
from .origin import replayed_origins
from .sources import EventSource
from .sources.notify import EVENT_NOTIFICATION_ACTION

_LOGGER = logging.getLogger(__name__)

RECORDER = "recorder"
ORIGIN_EVENTS = {"automation_triggered": OriginKind.AUTOMATION, "script_started": OriginKind.SCRIPT}
CALL_DOMAINS = ("notify", "tts", "assist_satellite", "telegram_bot")
YIELD_EVERY = 100
"""Replaying gives the event loop a turn after this many events."""

# Home Assistant stores event data as compact JSON, so the domain of a call is found by its text in every database
# the recorder supports, without reading the data of every other call. Of the automations and scripts that ran,
# only those are read whose context made one of the calls. Two selects joined by UNION ALL, so each can use an
# index in SQLite, MariaDB and PostgreSQL alike.
_CALLS = " OR ".join(f"""d.shared_data LIKE '%"domain":"{domain}"%'""" for domain in CALL_DOMAINS)
_ORIGINS = ", ".join(f"'{kind}'" for kind in ORIGIN_EVENTS)
_COLUMNS = """t.event_type, d.shared_data, e.time_fired_ts, e.context_id_bin, e.context_user_id_bin,
              e.context_parent_id_bin, e.event_id"""
EVENTS = text(
    f"""WITH sent AS (
            SELECT e.event_id, e.context_id_bin, t.event_type
            FROM events e
            JOIN event_types t ON t.event_type_id = e.event_type_id
            LEFT JOIN event_data d ON d.data_id = e.data_id
            WHERE e.time_fired_ts < :before
              AND (t.event_type = '{EVENT_NOTIFICATION_ACTION}'
                   OR (t.event_type = '{EVENT_CALL_SERVICE}' AND ({_CALLS})))
        )
        SELECT {_COLUMNS}
        FROM sent s
        JOIN events e ON e.event_id = s.event_id
        JOIN event_types t ON t.event_type_id = e.event_type_id
        LEFT JOIN event_data d ON d.data_id = e.data_id
        UNION ALL
        SELECT {_COLUMNS}
        FROM events e
        JOIN event_types t ON t.event_type_id = e.event_type_id
        LEFT JOIN event_data d ON d.data_id = e.data_id
        WHERE t.event_type IN ({_ORIGINS}) AND e.time_fired_ts < :before
          AND e.context_id_bin IN (SELECT context_id_bin FROM sent WHERE event_type = '{EVENT_CALL_SERVICE}')
        ORDER BY time_fired_ts, event_id"""
)


async def async_import(hass: HomeAssistant, sources: Iterable[EventSource], before: datetime) -> None:
    """Replay what the recorder holds from before a moment through the sources, in order of time.

    Does nothing without the recorder. A database the recorder cannot be read from logs a warning; an event a source
    cannot handle is skipped, and the number of them logged once.
    """
    if RECORDER not in hass.config.components:
        return
    recorder = get_instance(hass)
    try:
        await recorder.async_block_till_done()
        events = await recorder.async_add_executor_job(_read, hass, before.timestamp())
    except Exception as err:
        _LOGGER.warning("Could not read past notifications from the recorder: %s", err)
        return
    listeners = [listener for source in sources for listener in source.listeners()]
    token = replayed_origins.set(
        {
            event.context.id: Origin(
                kind=ORIGIN_EVENTS[event.event_type],
                entity_id=event.data.get(ATTR_ENTITY_ID),
                name=event.data.get(ATTR_NAME),
                imported=True,
            )
            for event in events
            if event.event_type in ORIGIN_EVENTS
        }
    )
    failed = 0
    try:
        for index, event in enumerate(events):
            if index % YIELD_EVERY == YIELD_EVERY - 1:
                await asyncio.sleep(0)
            for kind, handler, check in listeners:
                if kind != event.event_type or (check is not None and not check(event.data)):
                    continue
                try:
                    if inspect.isawaitable(result := handler(event)):
                        await result
                except Exception as err:
                    failed += 1
                    _LOGGER.debug("Skipped a %s event from the recorder: %s", event.event_type, err)
    finally:
        replayed_origins.reset(token)
    if failed:
        _LOGGER.warning("Skipped %s of the events from the recorder that could not be read as notifications", failed)


def _read(hass: HomeAssistant, before: float) -> list[Event[dict[str, Any]]]:
    with session_scope(hass=hass, read_only=True) as session:
        return [_event(tuple(row)) for row in session.execute(EVENTS, {"before": before})]


Row = tuple[str, str | None, float, bytes | None, bytes | None, bytes | None, int]


def _event(row: Row) -> Event[dict[str, Any]]:
    event_type, data, fired, context_id, user_id, parent_id, _event_id = row
    return Event(
        event_type,
        json_loads_object(data) if data else {},
        EventOrigin.local,
        fired,
        Context(
            user_id=bytes_to_uuid_hex_or_none(user_id),
            parent_id=bytes_to_ulid_or_none(parent_id),
            id=bytes_to_ulid_or_none(context_id),
        ),
    )
