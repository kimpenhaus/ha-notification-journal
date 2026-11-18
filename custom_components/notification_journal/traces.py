"""Mark a notification failed when the action that sent it raised an error inside an automation or script.

Home Assistant keeps the error of each step in the trace of the run; every notification sent by an automation or
script carries the key and run of that trace. An automation or script writes its state when a run starts and ends,
so the journal reads the trace of the runs it waits for then, and once more right away for a run that already ended.
Each failed step is used once; a run is forgotten once its trace reads stopped, which Home Assistant marks only a
moment after the state was written, so at the next check, or after a day.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.trace.util import async_get_trace
from homeassistant.const import ATTR_ENTITY_ID, EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import SIGNAL_CHANGED
from .models import NotificationRecord
from .store import NotificationStore

FORGET_AFTER = timedelta(days=1)
"""A run still waited for after this long is forgotten."""

Run = tuple[str, str]


@dataclass(slots=True)
class _Waiting:
    """The notifications a run sent that no failed step has claimed yet, and the steps already looked at."""

    started: datetime
    records: list[NotificationRecord] = field(default_factory=list)
    seen: set[tuple[str, int]] = field(default_factory=set)


class RunWatcher:
    """Waits for the runs that sent notifications and fails the notifications whose step raised."""

    def __init__(self, hass: HomeAssistant, store: NotificationStore) -> None:
        self._hass = hass
        self._store = store
        self._runs: dict[str, dict[Run, _Waiting]] = {}
        self._checking: dict[str, asyncio.Task[None]] = {}
        self._again: set[str] = set()

    def start(self) -> CALLBACK_TYPE:
        """Start waiting; return how to stop."""
        stops = [
            async_dispatcher_connect(self._hass, SIGNAL_CHANGED, self._changed),
            self._hass.bus.async_listen(EVENT_STATE_CHANGED, self._state_changed, event_filter=self._waited_for),
            async_track_time_interval(self._hass, self._forget, timedelta(hours=1)),
        ]

        @callback
        def stop() -> None:
            for remove in stops:
                remove()
            for task in self._checking.values():
                task.cancel()
            self._runs.clear()

        return stop

    @callback
    def _changed(self, change: str, record_id: str, record: NotificationRecord | None) -> None:
        origin = record.origin if record else None
        if change != "added" or origin is None or not (origin.entity_id and origin.trace_key and origin.run_id):
            return
        runs = self._runs.setdefault(origin.entity_id, {})
        runs.setdefault((origin.trace_key, origin.run_id), _Waiting(dt_util.utcnow())).records.append(record)
        self._schedule(origin.entity_id)

    @callback
    def _waited_for(self, event_data: dict[str, Any]) -> bool:
        return event_data.get(ATTR_ENTITY_ID) in self._runs

    @callback
    def _state_changed(self, event: Event) -> None:
        self._schedule(event.data[ATTR_ENTITY_ID])

    @callback
    def _schedule(self, entity_id: str) -> None:
        """Check an entity's runs, once more after a check that is running already; never two at a time."""
        if entity_id in self._checking:
            self._again.add(entity_id)
        elif entity_id in self._runs:
            self._checking[entity_id] = self._hass.async_create_task(self._check(entity_id), eager_start=False)

    async def _check(self, entity_id: str) -> None:
        try:
            while True:
                self._again.discard(entity_id)
                for run, waiting in list(self._runs.get(entity_id, {}).items()):
                    await self._check_run(entity_id, run, waiting)
                if entity_id not in self._again:
                    break
        finally:
            self._checking.pop(entity_id, None)

    async def _check_run(self, entity_id: str, run: Run, waiting: _Waiting) -> None:
        try:
            trace = await async_get_trace(self._hass, *run)
        except KeyError:
            trace = None
        for key, step in _failed_steps(trace or {}):
            if key in waiting.seen:
                continue
            waiting.seen.add(key)
            if (record := _sent_by(waiting.records, step["result"]["params"])) is not None:
                waiting.records.remove(record)
                self._store.mark_failed(record.id, None, step["error"])
        if trace is None or trace.get("state") == "stopped":
            self._drop(entity_id, run)

    def _drop(self, entity_id: str, run: Run) -> None:
        runs = self._runs.get(entity_id, {})
        runs.pop(run, None)
        if not runs:
            self._runs.pop(entity_id, None)

    @callback
    def _forget(self, _now: datetime) -> None:
        oldest = dt_util.utcnow() - FORGET_AFTER
        for entity_id, runs in list(self._runs.items()):
            for run, waiting in list(runs.items()):
                if waiting.started < oldest:
                    self._drop(entity_id, run)


def _failed_steps(trace: dict[str, Any]) -> list[tuple[tuple[str, int], dict[str, Any]]]:
    """The steps of a trace that called an action and raised, each with its path and position as key."""
    return [
        ((path, index), step)
        for path, steps in trace.get("trace", {}).items()
        for index, step in enumerate(steps)
        if step.get("error") and isinstance((step.get("result") or {}).get("params"), dict)
    ]


def _sent_by(records: list[NotificationRecord], params: dict[str, Any]) -> NotificationRecord | None:
    """The notification a step's action call sent: the same action and the same text, else none."""
    action = f"{params.get('domain')}.{params.get('service')}"
    texts = {str(value).strip() for value in (params.get("service_data") or {}).values() if isinstance(value, str)}
    return next(
        (
            record
            for record in records
            if record.message.strip() in texts
            and (
                action in (record.channel, record.group)
                or (action == "notify.send_message" and record.source == "notify")
            )
        ),
        None,
    )
