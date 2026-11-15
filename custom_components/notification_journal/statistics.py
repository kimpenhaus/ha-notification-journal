"""Counts of the notifications sent per quarter hour, and the statistics the panel shows from them.

The counts outlive the notifications themselves: purging, archiving or deleting a notification leaves them
unchanged. One row holds a quarter hour, an origin and whose view it counts for: ALL for administrators, EVERYONE
for the bell and announcements, else a user. A user's view adds their rows to those of EVERYONE, so a notification
that also reached everyone counts only under EVERYONE. Quarter hours, because every time zone is a whole number of
them away from UTC: each slot lies within one local hour, day, month and year.
"""

from __future__ import annotations

import calendar
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Any, Literal, get_args

from .models import EVERYONE, Answer, NotificationRecord

ALL = ""
"""The user id of the rows that count every notification once, for administrators."""

BURST_SIZE = 5
"""A quarter hour in which one origin sent at least this many notifications to a view is a burst there."""

NIGHT_FROM = 22
NIGHT_UNTIL = 7
HOUR = 3600
SLOT = 900

PeriodKind = Literal["day", "week", "month", "year"]
PERIOD_KINDS: tuple[PeriodKind, ...] = get_args(PeriodKind)
FIELDS = ("notifications", "with_buttons", "answered", "bursts", "night", "previous")

COUNTS_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS notification_counts (
        user_id TEXT NOT NULL,
        slot INTEGER NOT NULL,
        origin TEXT NOT NULL,
        notifications INTEGER NOT NULL DEFAULT 0,
        with_buttons INTEGER NOT NULL DEFAULT 0,
        answered INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, slot, origin)
    ) WITHOUT ROWID""",
    "CREATE INDEX IF NOT EXISTS notification_counts_slot ON notification_counts (slot)",
)

UPSERT_COUNTS = """
INSERT INTO notification_counts (user_id, slot, origin, notifications, with_buttons, answered)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (user_id, slot, origin) DO UPDATE SET
    notifications = notifications + excluded.notifications,
    with_buttons = with_buttons + excluded.with_buttons,
    answered = answered + excluded.answered
"""

Counts = tuple[int, int, int]
"""notifications, with buttons, answered."""


def slot_of(stamp: float) -> int:
    """Return the start of the quarter hour a moment in seconds since the epoch falls in."""
    return int(stamp) - int(stamp) % SLOT


def has_buttons(data: dict[str, Any] | None) -> bool:
    """Return whether a notification offered actionable buttons."""
    inner = data.get("data") if isinstance(data, dict) else None
    return isinstance(inner, dict) and bool(inner.get("actions"))


def contributions(users: Iterable[str], buttons: bool, answers: list[Answer]) -> dict[str, Counts]:
    """Return what one notification adds to the rows of each view it counts for.

    Besides ALL, those are its users, or EVERYONE alone once it reached everyone. A user's row counts only that
    user's answer, the same as the panel shows; EVERYONE's row counts none, as nobody may see another user's answer.
    """
    users = set(users)
    answered_by = {answer.user_id for answer in answers}
    result: dict[str, Counts] = {ALL: (1, int(buttons), int(bool(answers)))}
    for view in {EVERYONE} if EVERYONE in users else users:
        result[view] = (1, int(buttons), int(view in answered_by))
    return result


def counts_of(record: NotificationRecord | None) -> dict[str, Counts]:
    """Return what a stored notification adds to the rows of each view; nothing for none."""
    if record is None:
        return {}
    return contributions(record.user_ids, has_buttons(record.data), record.answers)


def difference(before: dict[str, Counts], after: dict[str, Counts]) -> dict[str, Counts]:
    """Return what changes in each view's row when a notification's contributions change."""
    result = {}
    for view in before.keys() | after.keys():
        old = before.get(view, (0, 0, 0))
        new = after.get(view, (0, 0, 0))
        if old != new:
            result[view] = (new[0] - old[0], new[1] - old[1], new[2] - old[2])
    return result


@dataclass(slots=True)
class Period:
    """A day, week, month or year in the user's time zone, the part of the period before it to compare with, and
    its buckets: hours of a day, days of a week or month, months of a year."""

    kind: PeriodKind
    start: datetime
    end: datetime
    compare_start: datetime
    compare_end: datetime
    buckets: list[datetime]


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
    zone = now.tzinfo
    if kind == "day":
        start = _shift_days(now, -offset)
        end, previous = _shift_days(start, 1), _shift_days(start, -1)
        buckets = [
            datetime.fromtimestamp(stamp, zone) for stamp in range(int(start.timestamp()), int(end.timestamp()), HOUR)
        ]
    elif kind == "week":
        start = _shift_days(now, -((now.weekday() - first_weekday) % 7) - 7 * offset)
        end, previous = _shift_days(start, 7), _shift_days(start, -7)
        buckets = [_shift_days(start, n) for n in range(7)]
    elif kind == "month":
        start = _add_months(now, -offset)
        end, previous = _add_months(start, 1), _add_months(start, -1)
        buckets = [_shift_days(start, n) for n in range(calendar.monthrange(start.year, start.month)[1])]
    else:
        start = datetime(now.year - offset, 1, 1, tzinfo=zone)
        end, previous = datetime(start.year + 1, 1, 1, tzinfo=zone), datetime(start.year - 1, 1, 1, tzinfo=zone)
        buckets = [_add_months(start, n) for n in range(12)]
    compare_end = min(previous + (min(now, end) - start), start)
    return Period(kind, start, end, previous, compare_end, buckets)


def year_start(now: datetime, years: int) -> datetime:
    """Return the first moment of the oldest of the last `years` calendar years, in now's time zone."""
    return datetime(now.year - years + 1, 1, 1, tzinfo=now.tzinfo)


def summarize(
    rows: Iterable[tuple[int, str, int, int, int]], previous: dict[str, int], current: Period, zone: tzinfo
) -> dict[str, Any]:
    """Turn the rows (slot, origin, notifications, with buttons, answered) of one view within the period, and its
    notifications per origin in the part compared with, into what the panel shows."""
    stamps = [bucket.timestamp() for bucket in current.buckets]
    buckets: list[defaultdict[str, int]] = [defaultdict(int) for _ in stamps]
    heatmap = [[0] * 24 for _ in range(7)]
    origins: defaultdict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
    for origin, notifications in previous.items():
        origins[origin]["previous"] = notifications
    for slot, origin, notifications, with_buttons, answered in rows:
        entry = origins[origin]
        local = datetime.fromtimestamp(slot, zone)
        buckets[bisect_right(stamps, slot) - 1][origin] += notifications
        heatmap[local.weekday()][local.hour] += notifications
        entry["notifications"] += notifications
        entry["with_buttons"] += with_buttons
        entry["answered"] += answered
        entry["bursts"] += notifications >= BURST_SIZE
        if local.hour >= NIGHT_FROM or local.hour < NIGHT_UNTIL:
            entry["night"] += notifications
    # A row drops to zero when a notification later also reached everyone.
    shown = {key: values for key, values in origins.items() if values["notifications"] or values["previous"]}
    return {
        "totals": {name: sum(values[name] for values in shown.values()) for name in FIELDS},
        "buckets": [
            {"start": moment.isoformat(), "counts": dict(counts)}
            for moment, counts in zip(current.buckets, buckets, strict=True)
        ],
        "heatmap": heatmap,
        "origins": sorted(
            ({"key": key, **values} for key, values in shown.items()),
            key=lambda item: (-item["notifications"], -item["previous"], item["key"]),
        ),
    }
