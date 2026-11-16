"""Sources turn what Home Assistant does into notification records."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from homeassistant.const import ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.util.ulid import ulid_now

from ..models import NotificationRecord
from ..origin import resolve_origin

ATTR_MESSAGE = "message"
ATTR_TITLE = "title"
TARGET_KEYS = (ATTR_ENTITY_ID, ATTR_DEVICE_ID, ATTR_AREA_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID)
"""The keys of a service call's target."""

type Listener = tuple[str, Callable[[Event], Any], Callable[[dict[str, Any]], bool] | None]
"""An event type, the handler and the filter of its data, as for `hass.bus.async_listen`."""


class EventSource(Protocol):
    """A source that records events of the bus; the recorder import replays old ones through the same listeners."""

    name: str

    def listeners(self) -> list[Listener]:
        """Return what the source listens to."""


@callback
def async_listen(hass: HomeAssistant, source: EventSource) -> CALLBACK_TYPE:
    """Listen to the events of a source; return what stops it."""
    removers = [hass.bus.async_listen(kind, handler, event_filter=check) for kind, handler, check in source.listeners()]

    @callback
    def _stop() -> None:
        for remove in removers:
            remove()

    return _stop


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
    return NotificationRecord(
        id=ulid_now(),
        time=event.time_fired,
        data=plain(data) if data else None,
        origin=resolve_origin(hass, event.context),
        context_id=event.context.id,
        **fields,
    )
