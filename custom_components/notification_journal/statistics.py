"""Counts of the notifications sent per quarter hour, and the statistics the panel shows from them.

The counts outlive the notifications themselves: purging, archiving or deleting a notification leaves them
unchanged. One row holds a quarter hour, an origin and whose view it counts for: ALL for administrators, EVERYONE
for the bell and announcements, else a user. A user's view adds their rows to those of EVERYONE, so a notification
that also reached everyone counts only under EVERYONE. Quarter hours, because every time zone is a whole number of
them away from UTC: each slot lies within one local hour, day, month and year.
"""

from __future__ import annotations

import calendar
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any, Literal

from .models import EVERYONE, Answer, NotificationRecord, Origin
from .origin import origin_key

ALL = ""
"""The user id of the rows that count every notification once, for administrators."""

BURST_SIZE = 5
BURST_WINDOW = 600
"""In each view, a burst starts with the BURST_SIZE-th notification of one origin within BURST_WINDOW seconds."""

NIGHT_FROM = 22
NIGHT_UNTIL = 7
HOUR = 3600
SLOT = 900

PeriodKind = Literal["day", "week", "month", "year"]
PERIOD_KINDS: tuple[PeriodKind, ...] = ("day", "week", "month", "year")

COUNTS_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS notification_counts (
        user_id TEXT NOT NULL,
        slot INTEGER NOT NULL,
        origin TEXT NOT NULL,
        notifications INTEGER NOT NULL DEFAULT 0,
        with_buttons INTEGER NOT NULL DEFAULT 0,
        answered INTEGER NOT NULL DEFAULT 0,
        bursts INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, slot, origin)
    ) WITHOUT ROWID""",
    "CREATE INDEX IF NOT EXISTS notification_counts_slot ON notification_counts (slot)",
)

UPSERT_COUNTS = """
INSERT INTO notification_counts (user_id, slot, origin, notifications, with_buttons, answered, bursts)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (user_id, slot, origin) DO UPDATE SET
    notifications = notifications + excluded.notifications,
    with_buttons = with_buttons + excluded.with_buttons,
    answered = answered + excluded.answered,
    bursts = bursts + excluded.bursts
"""

Counts = tuple[int, int, int, int]
"""notifications, with buttons, answered, bursts started."""


def group_key(origin: Origin) -> str:
    """Return the key an origin is counted and grouped under (`origin_key` in the database)."""
    return origin_key(origin) or origin.kind.value


def slot_of(stamp: float) -> int:
    """Return the start of the quarter hour a moment in seconds since the epoch falls in."""
    return int(stamp) - int(stamp) % SLOT


def has_buttons(data: dict[str, Any] | None) -> bool:
    """Return whether a notification offered actionable buttons."""
    inner = data.get("data") if isinstance(data, dict) else None
    return isinstance(inner, dict) and bool(inner.get("actions"))


def view_keys(users: Iterable[str]) -> set[str]:
    """Return the user ids a notification counts for besides ALL: EVERYONE alone once it reached everyone."""
    users = set(users)
    return {EVERYONE} if EVERYONE in users else users


def contributions(bursts: Mapping[str, bool], buttons: bool, answers: list[Answer]) -> dict[str, Counts]:
    """Return what one notification adds to the rows of each view it counts for.

    bursts has the views (ALL and those of `view_keys`) and whether the notification starts a burst in each. A
    user's row counts only that user's answer, the same as the panel shows; EVERYONE's row counts none, as nobody
    may see another user's answer.
    """
    answered_by = {answer.user_id for answer in answers}
    result: dict[str, Counts] = {}
    for view, burst in bursts.items():
        answered = bool(answers) if view == ALL else view in answered_by
        result[view] = (1, int(buttons), int(answered), int(burst))
    return result


def difference(before: dict[str, Counts], after: dict[str, Counts]) -> dict[str, Counts]:
    """Return what changes in each view's row when a notification's contributions change."""
    result = {}
    for user in before.keys() | after.keys():
        old = before.get(user, (0, 0, 0, 0))
        new = after.get(user, (0, 0, 0, 0))
        if old != new:
            result[user] = (new[0] - old[0], new[1] - old[1], new[2] - old[2], new[3] - old[3])
    return result


def counts_of(record: NotificationRecord, bursts: Mapping[str, bool]) -> dict[str, Counts]:
    """Return what a stored notification adds to the rows of the views in bursts."""
    return contributions(bursts, has_buttons(record.data), record.answers)


class BurstWindow:
    """Find where bursts start in notifications that arrive in order of time, per view and origin."""

    def __init__(self) -> None:
        """Start without notifications."""
        self._times: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def add(self, view: str, key: str, time: float) -> bool:
        """Add a notification of a view; return whether it starts a burst there."""
        times = self._times[(view, key)]
        while times and times[0] <= time - BURST_WINDOW:
            times.popleft()
        times.append(time)
        return len(times) == BURST_SIZE


@dataclass(slots=True)
class Period:
    """A day, week, month or year in the user's time zone, the part of the period before it to compare with, and
    its buckets: hours of a day, days of a week or month, months of a year."""

    kind: PeriodKind
    start: datetime
    end: datetime
    compare_start: datetime
    compare_end: datetime
    buckets: list[datetime] = field(default_factory=list)


def _midnight(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, moment.day, tzinfo=moment.tzinfo)


def _add_months(moment: datetime, months: int) -> datetime:
    month = moment.year * 12 + moment.month - 1 + months
    return datetime(month // 12, month % 12 + 1, 1, tzinfo=moment.tzinfo)


def _shift_days(moment: datetime, days: int) -> datetime:
    """Return the local midnight `days` after moment's date, also across a change of daylight saving time."""
    date = moment.date() + timedelta(days=days)
    return datetime(date.year, date.month, date.day, tzinfo=moment.tzinfo)


def period(kind: PeriodKind, offset: int, first_weekday: int, now: datetime) -> Period:
    """Return the period of a kind, offset periods before the one now is in; now carries the time zone.

    first_weekday counts from Monday (0) to Sunday (6). The comparison covers as much of the previous period as
    has passed of this one, so a running week is compared with the same days and hours of the week before.
    """
    today = _midnight(now)
    if kind == "day":
        start = _shift_days(today, -offset)
        end = _shift_days(start, 1)
        previous = _shift_days(start, -1)
    elif kind == "week":
        this_week = _shift_days(today, -((today.weekday() - first_weekday) % 7))
        start = _shift_days(this_week, -7 * offset)
        end = _shift_days(start, 7)
        previous = _shift_days(start, -7)
    elif kind == "month":
        start = _add_months(today, -offset)
        end = _add_months(start, 1)
        previous = _add_months(start, -1)
    else:
        start = datetime(today.year - offset, 1, 1, tzinfo=today.tzinfo)
        end = datetime(start.year + 1, 1, 1, tzinfo=today.tzinfo)
        previous = datetime(start.year - 1, 1, 1, tzinfo=today.tzinfo)
    elapsed = min(now, end) - start
    result = Period(kind=kind, start=start, end=end, compare_start=previous, compare_end=min(previous + elapsed, start))
    if kind == "day":
        result.buckets = _hours(start, end)
    elif kind == "week":
        result.buckets = [_shift_days(start, n) for n in range(7)]
    elif kind == "month":
        result.buckets = [_shift_days(start, n) for n in range(calendar.monthrange(start.year, start.month)[1])]
    else:
        result.buckets = [_add_months(start, n) for n in range(12)]
    return result


def _hours(start: datetime, end: datetime) -> list[datetime]:
    """Return the starts of the local hours from start to end, 23 or 25 on a day daylight saving time changes."""
    return [
        datetime.fromtimestamp(stamp, start.tzinfo)
        for stamp in range(int(start.timestamp()), int(end.timestamp()), HOUR)
    ]


def bucket_index(kind: PeriodKind, start: datetime, local: datetime) -> int:
    """Return the bucket a local moment falls in."""
    if kind == "day":
        return int((local.timestamp() - start.timestamp()) // HOUR)
    if kind in ("week", "month"):
        return (local.date() - start.date()).days
    return local.month - 1


def year_start(now: datetime, years: int) -> datetime:
    """Return the first moment of the oldest of the last `years` calendar years, in now's time zone."""
    return datetime(now.year - years + 1, 1, 1, tzinfo=now.tzinfo)


def summarize(rows: Iterable[tuple[int, str, int, int, int, int]], current: Period, zone: tzinfo) -> dict[str, Any]:
    """Turn rows (slot, origin, notifications, with buttons, answered, bursts) into what the panel shows.

    Rows before the period count as the comparison; only those within the compared part of it should be passed.
    """
    start = current.start.timestamp()
    end = current.end.timestamp()
    buckets: list[dict[str, int]] = [defaultdict(int) for _ in current.buckets]
    heatmap = [[0] * 24 for _ in range(7)]
    totals = {"notifications": 0, "with_buttons": 0, "answered": 0, "bursts": 0, "night": 0}
    previous_total = 0
    origins: dict[str, dict[str, int]] = defaultdict(
        lambda: {"notifications": 0, "previous": 0, "with_buttons": 0, "answered": 0, "bursts": 0, "night": 0}
    )
    for slot, origin, notifications, with_buttons, answered, bursts in rows:
        entry = origins[origin]
        if not start <= slot < end:
            previous_total += notifications
            entry["previous"] += notifications
            continue
        local = datetime.fromtimestamp(slot, zone)
        index = bucket_index(current.kind, current.start, local)
        if 0 <= index < len(buckets):
            buckets[index][origin] += notifications
        heatmap[local.weekday()][local.hour] += notifications
        night = notifications if local.hour >= NIGHT_FROM or local.hour < NIGHT_UNTIL else 0
        for counts in (totals, entry):
            counts["notifications"] += notifications
            counts["with_buttons"] += with_buttons
            counts["answered"] += answered
            counts["bursts"] += bursts
            counts["night"] += night
    return {
        "totals": totals,
        "previous": {"notifications": previous_total},
        "buckets": [
            {"start": moment.isoformat(), "counts": dict(counts)}
            for moment, counts in zip(current.buckets, buckets, strict=True)
        ],
        "heatmap": heatmap,
        "origins": sorted(
            # A row can drop to zero when a notification later also reached everyone.
            (
                {"key": key, **values}
                for key, values in origins.items()
                if values["notifications"] or values["previous"]
            ),
            key=lambda item: (-item["notifications"], -item["previous"], item["key"]),
        ),
    }
