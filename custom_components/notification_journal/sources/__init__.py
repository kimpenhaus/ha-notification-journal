"""Sources turn what Home Assistant does into notification records."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar
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


@dataclass(slots=True)
class Resending:
    """A failed notification the panel sends again; active only while its own calls run."""

    record_id: str
    active: bool = True


resending: ContextVar[Resending | None] = ContextVar("notification_journal_resending", default=None)
"""Set while the panel sends a failed notification again; tasks started meanwhile inherit it, hence `active`."""


def resent_from() -> str | None:
    """The notification being sent again right now, if any."""
    mark = resending.get()
    return mark.record_id if mark is not None and mark.active else None


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
        resent_from=resent_from(),
        **fields,
    )
