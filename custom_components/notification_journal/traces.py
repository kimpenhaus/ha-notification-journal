"""Mark a notification failed when the action that sent it raised an error inside an automation or script.

Home Assistant keeps the error of each step in the trace of the run; every notification sent by an automation or
script carries the key and run of that trace. The journal takes note of the run when a source records the
notification, before the action runs, and reads the trace whenever the automation or script writes its state, at the
start and end of each run. Each failed step is used once; a run is forgotten once its trace reads stopped, which Home
Assistant marks a moment after the last state was written, so at a later check, or after a day.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.trace.util import async_get_trace
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .models import NotificationRecord
from .recipients import NOTIFY_DOMAIN, SEND_MESSAGE
from .sources import ATTR_MESSAGE
from .sources.telegram import TELEGRAM_DOMAIN, TEXT_FIELDS
from .store import NotificationStore

FORGET_AFTER = timedelta(days=1)

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
        self._tracking: dict[str, CALLBACK_TYPE] = {}
        self._checking: dict[str, asyncio.Task[None]] = {}
        self._due: set[str] = set()

    def start(self) -> CALLBACK_TYPE:
        """Start waiting; return how to stop."""
        stops = [
            self._store.on_add(self._added),
            async_track_time_interval(self._hass, self._forget, FORGET_AFTER / 24),
        ]

        @callback
        def stop() -> None:
            for remove in [*stops, *self._tracking.values()]:
                remove()
            for task in self._checking.values():
                task.cancel()

        return stop

    @callback
    def _added(self, record: NotificationRecord) -> None:
        origin = record.origin
        if not (origin.entity_id and origin.trace_key and origin.run_id):
            return
        runs = self._runs.setdefault(origin.entity_id, {})
        runs.setdefault((origin.trace_key, origin.run_id), _Waiting(dt_util.utcnow())).records.append(record)
        if origin.entity_id not in self._tracking:
            self._tracking[origin.entity_id] = async_track_state_change_event(
                self._hass, origin.entity_id, self._state_changed
            )

    @callback
    def _state_changed(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        self._due.add(entity_id)
        if entity_id not in self._checking:
            self._checking[entity_id] = self._hass.async_create_task(self._check(entity_id), eager_start=False)

    async def _check(self, entity_id: str) -> None:
        try:
            while entity_id in self._due:
                self._due.discard(entity_id)
                for run, waiting in list(self._runs.get(entity_id, {}).items()):
                    await self._check_run(entity_id, run, waiting)
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
            if (untrack := self._tracking.pop(entity_id, None)) is not None:
                untrack()

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
    """The notification a step's action call sent: the same action and the same text, else none.

    A notification's channel is the action that sent it, except for notify.send_message, whose channel holds the
    notify entities it targets.
    """
    domain, service = params.get("domain"), params.get("service")
    action = f"{domain}.{service}"
    field = TEXT_FIELDS.get(service, ATTR_MESSAGE) if domain == TELEGRAM_DOMAIN else ATTR_MESSAGE
    text = str((params.get("service_data") or {}).get(field) or "").strip()
    sends_message = action == f"{NOTIFY_DOMAIN}.{SEND_MESSAGE}"
    return next(
        (
            record
            for record in records
            if record.message.strip() == text
            and (record.channel == action or (sends_message and record.source == NOTIFY_DOMAIN))
        ),
        None,
    )
