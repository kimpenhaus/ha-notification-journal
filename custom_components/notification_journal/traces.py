"""Mark a notification failed when the action that sent it raised an error inside an automation or script.

Home Assistant keeps the error of each step in the trace of the run; every notification sent by an automation or
script carries the key and run of that trace. An automation or script writes its state when a run starts and ends,
so the journal reads the trace of the runs it waits for then, and once more right away for a run that already ended.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.trace.util import async_get_trace
from homeassistant.const import ATTR_ENTITY_ID, EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import SIGNAL_CHANGED
from .models import NotificationRecord
from .store import NotificationStore

FORGET_AFTER = timedelta(days=1)
"""A run still running after this long is no longer waited for."""

Run = tuple[str, str]


class RunWatcher:
    """Waits for the runs that sent notifications and fails the notifications whose step raised."""

    def __init__(self, hass: HomeAssistant, store: NotificationStore) -> None:
        self._hass = hass
        self._store = store
        self._runs: dict[str, dict[Run, list[NotificationRecord]]] = {}

    def start(self) -> CALLBACK_TYPE:
        """Start waiting; return how to stop."""
        stops = [
            async_dispatcher_connect(self._hass, SIGNAL_CHANGED, self._changed),
            self._hass.bus.async_listen(EVENT_STATE_CHANGED, self._state_changed, event_filter=self._waited_for),
        ]

        @callback
        def stop() -> None:
            for remove in stops:
                remove()

        return stop

    @callback
    def _changed(self, change: str, record_id: str, record: NotificationRecord | None) -> None:
        origin = record.origin if record else None
        if change != "added" or origin is None or not (origin.entity_id and origin.trace_key and origin.run_id):
            return
        runs = self._runs.setdefault(origin.entity_id, {})
        runs.setdefault((origin.trace_key, origin.run_id), []).append(record)
        self._hass.async_create_task(self._check(origin.entity_id), eager_start=False)

    @callback
    def _waited_for(self, event_data: dict[str, Any]) -> bool:
        return event_data.get(ATTR_ENTITY_ID) in self._runs

    @callback
    def _state_changed(self, event: Event) -> None:
        self._hass.async_create_task(self._check(event.data[ATTR_ENTITY_ID]), eager_start=False)

    async def _check(self, entity_id: str) -> None:
        runs = self._runs.get(entity_id, {})
        oldest = dt_util.utcnow() - FORGET_AFTER
        for run, records in list(runs.items()):
            try:
                trace = await async_get_trace(self._hass, *run)
            except KeyError:
                trace = None
            for step in _failed_steps(trace or {}):
                if (record := _sent_by(records, step["result"]["params"])) is not None:
                    records.remove(record)
                    self._store.mark_failed(record.id, None, step["error"])
            if trace is None or trace.get("state") == "stopped" or all(r.time < oldest for r in records):
                del runs[run]
        if not runs:
            self._runs.pop(entity_id, None)


def _failed_steps(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """The steps of a trace that called an action and raised."""
    return [
        step
        for steps in trace.get("trace", {}).values()
        for step in steps
        if step.get("error") and isinstance((step.get("result") or {}).get("params"), dict)
    ]


def _sent_by(records: list[NotificationRecord], params: dict[str, Any]) -> NotificationRecord | None:
    """The notification an action call of a step sent: same action, and the same text if several share it."""
    action = f"{params.get('domain')}.{params.get('service')}"
    texts = {str(value).strip() for value in (params.get("service_data") or {}).values() if isinstance(value, str)}
    candidates = [
        record
        for record in records
        if action in (record.channel, record.group) or (action == "notify.send_message" and record.source == "notify")
    ]
    return next((record for record in candidates if record.message.strip() in texts), None) or next(
        iter(candidates), None
    )
