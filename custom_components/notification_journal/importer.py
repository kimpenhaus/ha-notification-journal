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
from dataclasses import replace
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
PRECISION = 1e-6
"""Records keep their time to the microsecond, the recorder more exactly: resuming does not read the last one again."""

# Home Assistant stores event data as compact JSON, so the domain of a call is found by its text in every database
# the recorder supports, without reading the data of every other call. Of the automations and scripts that ran,
# only those are read whose context sent one of the notifications.
_CALLS = " OR ".join(f"""d.shared_data LIKE '%"domain":"{domain}"%'""" for domain in CALL_DOMAINS)
_ORIGINS = ", ".join(f"'{kind}'" for kind in ORIGIN_EVENTS)
EVENTS = text(
    f"""WITH sent AS (
            SELECT e.event_id, e.context_id_bin
            FROM events e
            JOIN event_types t ON t.event_type_id = e.event_type_id
            LEFT JOIN event_data d ON d.data_id = e.data_id
            WHERE e.time_fired_ts > :after AND e.time_fired_ts < :before
              AND (t.event_type = '{EVENT_NOTIFICATION_ACTION}'
                   OR (t.event_type = '{EVENT_CALL_SERVICE}' AND ({_CALLS})))
        )
        SELECT t.event_type, d.shared_data, e.time_fired_ts, e.context_id_bin, e.context_user_id_bin,
               e.context_parent_id_bin
        FROM events e
        JOIN event_types t ON t.event_type_id = e.event_type_id
        LEFT JOIN event_data d ON d.data_id = e.data_id
        WHERE e.event_id IN (SELECT event_id FROM sent)
           OR (t.event_type IN ({_ORIGINS}) AND e.time_fired_ts < :before
               AND e.context_id_bin IN (SELECT context_id_bin FROM sent))
        ORDER BY e.time_fired_ts, e.event_id"""
)

Row = tuple[str, str | None, float, bytes | None, bytes | None, bytes | None]


async def async_import(
    hass: HomeAssistant, sources: Iterable[EventSource], after: datetime | None, before: datetime
) -> None:
    """Replay what the recorder holds between two moments through the sources, in order of time.

    Does nothing without the recorder. A database the recorder cannot be read from logs a warning; an event a source
    cannot handle is skipped, and the number of them logged once.
    """
    if RECORDER not in hass.config.components:
        return
    recorder = get_instance(hass)
    try:
        await recorder.async_block_till_done()
        rows = await recorder.async_add_executor_job(
            _read, hass, after.timestamp() + PRECISION if after else 0.0, before.timestamp()
        )
    except Exception as err:
        _LOGGER.warning("Could not read past notifications from the recorder: %s", err)
        return
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
    replayed = failed = 0
    for event in events:
        for kind, handler, check in listeners:
            if kind != event.event_type or (check is not None and not check(event.data)):
                continue
            try:
                if inspect.isawaitable(result := handler(event)):
                    await result
            except Exception as err:
                failed += 1
                _LOGGER.debug("Skipped a %s event from the recorder: %s", event.event_type, err)
            else:
                replayed += 1
    if failed:
        _LOGGER.warning("Skipped %s of the events from the recorder that could not be read as notifications", failed)
    _LOGGER.debug("Replayed %s events from the recorder", replayed)


def _read(hass: HomeAssistant, after: float, before: float) -> list[Row]:
    with session_scope(hass=hass, read_only=True) as session:
        return [tuple(row) for row in session.execute(EVENTS, {"after": after, "before": before})]


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
    """Return the automation or script that ran in a context, with the user who started it, else the user, else an
    unknown origin."""
    if (origin := origins.get(context.id)) is not None:
        return replace(origin, user_id=context.user_id)
    if context.user_id:
        return Origin(kind=OriginKind.USER, user_id=context.user_id, imported=True)
    return Origin(kind=OriginKind.UNKNOWN, imported=True)
