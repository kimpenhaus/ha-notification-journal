"""Import, once on first setup, the notifications the recorder still holds.

The recorder keeps the events of the last days (10 by default), service calls among them. Replaying the calls of
notify actions, spoken announcements and Telegram, and the answers to buttons, through the same listeners that
record them live rebuilds those notifications: recipients, notify groups and answers alike. Their origin comes from
the recorded contexts, as the call stack and the traces of that time are gone.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context, Event, EventOrigin, HomeAssistant
from homeassistant.helpers.recorder import get_instance, session_scope
from homeassistant.util.ulid import bytes_to_ulid_or_none
from sqlalchemy import text

from .models import Origin, OriginKind
from .origin import replayed_origin
from .sources import EventSource
from .sources.notify import EVENT_NOTIFICATION_ACTION

_LOGGER = logging.getLogger(__name__)

RECORDER = "recorder"
ORIGIN_EVENTS = {"automation_triggered": OriginKind.AUTOMATION, "script_started": OriginKind.SCRIPT}
CALL_DOMAINS = ("notify", "tts", "assist_satellite", "telegram_bot")

# Home Assistant stores event data as compact JSON, so the domain of a call is found by its text in every database
# the recorder supports, without reading the data of every other call.
_CALLS = " OR ".join(f"""d.shared_data LIKE '%"domain":"{domain}"%'""" for domain in CALL_DOMAINS)
_OTHERS = ", ".join(f"'{kind}'" for kind in (EVENT_NOTIFICATION_ACTION, *ORIGIN_EVENTS))
EVENTS = text(
    f"""SELECT t.event_type, d.shared_data, e.time_fired_ts, e.context_id_bin, e.context_user_id_bin,
              e.context_parent_id_bin
        FROM events e
        JOIN event_types t ON t.event_type_id = e.event_type_id
        LEFT JOIN event_data d ON d.data_id = e.data_id
        WHERE e.time_fired_ts < :before
          AND (t.event_type IN ({_OTHERS}) OR (t.event_type = '{EVENT_CALL_SERVICE}' AND ({_CALLS})))
        ORDER BY e.time_fired_ts, e.event_id"""
)

Row = tuple[str, str | None, float, bytes | None, bytes | None, bytes | None]


async def async_import(hass: HomeAssistant, sources: Iterable[EventSource], before: datetime) -> int:
    """Replay what the recorder holds from before a moment through the sources; return how many events.

    Does nothing without the recorder. A database the recorder cannot be read from logs a warning; the journal stays
    as it is either way.
    """
    if RECORDER not in hass.config.components:
        return 0
    recorder = get_instance(hass)
    try:
        await recorder.async_block_till_done()
        rows = await recorder.async_add_executor_job(_read, hass, before.timestamp())
    except Exception as err:
        _LOGGER.warning("Could not read past notifications from the recorder: %s", err)
        return 0
    events = [_event(row) for row in rows]
    origins = {
        event.context.id: Origin(
            kind=ORIGIN_EVENTS[event.event_type],
            entity_id=event.data.get("entity_id"),
            name=event.data.get("name"),
            imported=True,
        )
        for event in events
        if event.event_type in ORIGIN_EVENTS
    }
    listeners = [listener for source in sources for listener in source.listeners()]
    replayed_origin.set(lambda context: _origin(origins, context))
    count = 0
    for event in events:
        for kind, handler, check in listeners:
            if kind == event.event_type and (check is None or check(event.data)):
                count += 1
                if inspect.isawaitable(result := handler(event)):
                    await result
    _LOGGER.debug("Replayed %s events from the recorder", count)
    return count


def _read(hass: HomeAssistant, before: float) -> list[Row]:
    with session_scope(hass=hass, read_only=True) as session:
        return [tuple(row) for row in session.execute(EVENTS, {"before": before})]


def _event(row: Row) -> Event[dict[str, Any]]:
    event_type, data, fired, context_id, user_id, parent_id = row
    return Event(
        event_type,
        json.loads(data) if data else {},
        EventOrigin.local,
        fired,
        Context(
            user_id=user_id.hex() if user_id else None,
            parent_id=bytes_to_ulid_or_none(parent_id),
            id=bytes_to_ulid_or_none(context_id),
        ),
    )


def _origin(origins: dict[str, Origin], context: Context) -> Origin:
    """Return the automation or script that ran in a context, else the user, else an unknown origin."""
    if (origin := origins.get(context.id)) is not None:
        return origin
    if context.user_id:
        return Origin(kind=OriginKind.USER, user_id=context.user_id, imported=True)
    return Origin(kind=OriginKind.UNKNOWN, imported=True)
