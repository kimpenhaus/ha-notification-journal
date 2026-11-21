"""Sources turn what Home Assistant does into notification records."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from homeassistant.const import ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID
from homeassistant.core import Event, HomeAssistant
from homeassistant.util.ulid import ulid_now

from ..models import NotificationRecord
from ..origin import resolve_origin

ATTR_MESSAGE = "message"
ATTR_TITLE = "title"
TARGET_KEYS = (ATTR_ENTITY_ID, ATTR_DEVICE_ID, ATTR_AREA_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID)
"""The keys of a service call's target."""


@dataclass(slots=True)
class Resend:
    """A notification sent again in a call's context, and the record that call made."""

    record_id: str
    sent: str | None = None


_resends: dict[str, Resend] = {}


@contextmanager
def sending_again(context_id: str, record_id: str) -> Iterator[Resend]:
    """Record what a call in this context sends as sending a notification again, whichever source records it."""
    _resends[context_id] = entry = Resend(record_id)
    try:
        yield entry
    finally:
        _resends.pop(context_id, None)


type Listener = tuple[str, Callable[[Event], Any], Callable[[dict[str, Any]], bool] | None]
"""An event type, the handler and the filter of its data, as for `hass.bus.async_listen`."""


class EventSource(Protocol):
    """A source that records events of the bus; the recorder import replays old ones through the same listeners."""

    def listeners(self) -> list[Listener]:
        """Return what the source listens to."""


def as_list(value: Any) -> list[Any]:
    """Return a single value or a list of values as a list."""
    if value is None:
        return []
    return [value] if isinstance(value, str | int) else list(value)


def plain(data: dict[str, Any]) -> dict[str, Any]:
    """Return service data as JSON-safe values; what JSON cannot hold becomes its text."""
    return json.loads(json.dumps(data, default=str))


def new_record(
    hass: HomeAssistant, event: Event, *, data: dict[str, Any] | None = None, **fields: Any
) -> NotificationRecord:
    """Return the record of a service call, sent when its event fired, with its origin and JSON-safe data.

    `fields` are the remaining fields of the record: source, channel, message, recipients and optionally title, group.
    """
    fields.setdefault("title", None)
    record = NotificationRecord(
        id=ulid_now(),
        time=event.time_fired,
        data=plain(data) if data else None,
        origin=resolve_origin(hass, event.context),
        context_id=event.context.id,
        **fields,
    )
    if (again := _resends.get(event.context.id)) is not None:
        record.resent_from, again.sent = again.record_id, record.id
    return record
