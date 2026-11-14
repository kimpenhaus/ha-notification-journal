"""Sources turn what Home Assistant does into notification records."""

from __future__ import annotations

import json
from typing import Any, Protocol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE

TARGET_KEYS = (ATTR_ENTITY_ID, "device_id", "area_id", "floor_id", "label_id")
"""The keys of a service call's target."""


def as_list(value: Any) -> list[Any]:
    """Return a single value or a list of values as a list."""
    if value is None:
        return []
    return [value] if isinstance(value, str | int) else list(value)


def plain(data: dict[str, Any]) -> dict[str, Any]:
    """Return service data as JSON-safe values; what JSON cannot hold becomes its text."""
    return json.loads(json.dumps(data, default=str))


class Source(Protocol):
    """Something that records notifications of one kind, such as notify actions."""

    name: str

    def async_start(self) -> CALLBACK_TYPE:
        """Start listening and return the callback that stops it."""
        ...
