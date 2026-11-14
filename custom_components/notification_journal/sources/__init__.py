"""Sources turn what Home Assistant does into notification records."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.const import ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID
from homeassistant.core import Event, HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from ..models import NotificationRecord
from ..origin import resolve_origin

ATTR_MESSAGE = "message"
ATTR_TITLE = "title"
TARGET_KEYS = (ATTR_ENTITY_ID, ATTR_DEVICE_ID, ATTR_AREA_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID)
"""The keys of a service call's target."""


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
    """Return the record of a service call that is running right now, with its origin and JSON-safe data.

    `fields` are the remaining fields of the record: source, channel, message, recipients and optionally title, group.
    """
    fields.setdefault("title", None)
    return NotificationRecord(
        id=ulid_now(),
        time=dt_util.utcnow(),
        data=plain(data) if data else None,
        origin=resolve_origin(hass, event.context),
        context_id=event.context.id,
        **fields,
    )
