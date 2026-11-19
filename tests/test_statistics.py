"""Tests of the hourly counts and the statistics built from them."""

import sqlite3
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.notification_journal.const import DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.models import (
    Answer,
    Call,
    NotificationRecord,
    Origin,
    OriginKind,
    Recipient,
    RecipientKind,
)
from custom_components.notification_journal.statistics import period, summarize, year_start
from custom_components.notification_journal.store import NotificationStore, _fill_counts

BERLIN = ZoneInfo("Europe/Berlin")
KOLKATA = ZoneInfo("Asia/Kolkata")
ANNA = Recipient(kind=RecipientKind.PERSON, id="person.anna", name="Anna", user_id="user-anna")
BEN = Recipient(kind=RecipientKind.PERSON, id="person.ben", name="Ben", user_id="user-ben")
BELL = Recipient(kind=RecipientKind.EVERYONE, id="persistent_notification", name="Notifications")
GARAGE = Origin(kind=OriginKind.AUTOMATION, entity_id="automation.garage", name="Garage door")
SERVER = Origin(kind=OriginKind.INTEGRATION, name="Server watch", integration="server_watch")
BUTTONS = {"data": {"actions": [{"action": "CLOSE", "title": "Close"}]}}
ALL_TIME = ((0.0, 4e9), (0.0, 0.0))


def _record(record_id: str, recipients: list[Recipient], time: datetime | None = None, **kw) -> NotificationRecord:
    return NotificationRecord(
        id=record_id,
        time=time or dt_util.utcnow(),
        source="notify",
        channel=kw.pop("channel", "notify.phone"),
        title=None,
        message=record_id,
        data=kw.pop("data", None),
        recipients=recipients,
        origin=kw.pop("origin", GARAGE),
        context_id=f"ctx-{record_id}",
        **kw,
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[NotificationStore]:
    """An open store in a temporary file."""
    store = NotificationStore(str(tmp_path / "journal.db"))
    await store.async_open()
    yield store
    await store.async_close()


async def _counts(store: NotificationStore, user_id: str | None = None, *, failed: bool = False) -> dict[str, tuple]:
    """Return notifications, with buttons and answered per origin over all time, and failed if asked."""
    await store.async_flush()
    counted = await store.async_statistics(user_id, *ALL_TIME)
    totals: dict[str, list[int]] = {}
    for _slot, origin, *values in counted.rows:
        total = totals.setdefault(origin, [0, 0, 0, 0])
        for index, value in enumerate(values):
            total[index] += value
    return {origin: tuple(values if failed else values[:3]) for origin, values in totals.items()}


async def test_each_view_counts_what_it_may_see(store: NotificationStore) -> None:
    store.add(_record("anna", [ANNA], data=BUTTONS))
    store.add(_record("both", [ANNA, BEN], origin=SERVER))
    store.add(_record("bell", [BELL], origin=Origin(kind=OriginKind.SYSTEM)))

    assert await _counts(store) == {
        "automation.garage": (1, 1, 0),
        "integration.server_watch": (1, 0, 0),
        "system": (1, 0, 0),
    }
    assert await _counts(store, "user-anna") == {
        "automation.garage": (1, 1, 0),
        "integration.server_watch": (1, 0, 0),
        "system": (1, 0, 0),
    }
    assert await _counts(store, "user-ben") == {"integration.server_watch": (1, 0, 0), "system": (1, 0, 0)}


async def test_members_of_a_group_count_when_their_call_arrives(store: NotificationStore) -> None:
    store.add(_record("family", [], group="notify.family", channel="notify.family"))
    store.add_inner_call("family", Call("notify.phone_anna", [ANNA], "c1"))
    store.add_inner_call("family", Call("notify.phone_ben", [BEN], "c2"))
    store.add_inner_call("family", Call("notify.phone_ben_2", [BEN], "c3"))

    assert await _counts(store) == {"automation.garage": (1, 0, 0)}
    assert await _counts(store, "user-anna") == {"automation.garage": (1, 0, 0)}
    assert await _counts(store, "user-ben") == {"automation.garage": (1, 0, 0)}


async def test_reaching_everyone_counts_once_per_user(store: NotificationStore) -> None:
    store.add(_record("mixed", [ANNA], group="notify.all", channel="notify.all"))
    store.add_inner_call("mixed", Call("notify.persistent_notification", [BELL], "c1"))

    assert await _counts(store, "user-anna") == {"automation.garage": (1, 0, 0)}
    assert await _counts(store, "user-ben") == {"automation.garage": (1, 0, 0)}


async def test_answers_count_once_and_per_user(store: NotificationStore) -> None:
    store.add(_record("door", [ANNA, BEN], data=BUTTONS))
    await store.async_flush()
    now = dt_util.utcnow()
    await store.async_add_answer("notify", Answer(action="CLOSE", time=now, user_id="user-anna"))
    await store.async_add_answer("notify", Answer(action="CLOSE", time=now, user_id="user-anna"))
    await store.async_add_answer("notify", Answer(action="CLOSE", time=now, user_id="user-ben"))

    assert await _counts(store) == {"automation.garage": (1, 1, 1)}
    assert await _counts(store, "user-anna") == {"automation.garage": (1, 1, 1)}
    assert await _counts(store, "user-ben") == {"automation.garage": (1, 1, 1)}


async def test_a_burst_is_a_quarter_hour_with_five_from_one_origin_in_a_view(store: NotificationStore) -> None:
    sent = dt_util.as_utc(datetime(2026, 11, 10, 12, 1, tzinfo=BERLIN))
    for minute in range(3):
        store.add(_record(f"anna{minute}", [ANNA], sent + timedelta(minutes=minute)))
    for minute in range(2):
        store.add(_record(f"bell{minute}", [BELL], sent + timedelta(minutes=5 + minute)))
    store.add(_record("next", [ANNA], sent + timedelta(minutes=20)))
    await store.async_flush()
    day = period("day", 0, 0, sent.astimezone(BERLIN))
    span = (day.start.timestamp(), day.end.timestamp())

    def bursts(counted) -> int:
        return summarize(counted.rows, counted.previous, day, BERLIN)["totals"]["bursts"]

    assert bursts(await store.async_statistics(None, span, (0, 0))) == 1
    assert bursts(await store.async_statistics("user-anna", span, (0, 0))) == 1
    assert bursts(await store.async_statistics("user-ben", span, (0, 0))) == 0


async def test_nobody_sees_answers_to_everyone(store: NotificationStore) -> None:
    store.add(_record("bell", [BELL], data=BUTTONS))
    await store.async_flush()
    await store.async_add_answer("notify", Answer(action="CLOSE", time=dt_util.utcnow(), user_id="user-ben"))

    assert await _counts(store) == {"automation.garage": (1, 1, 1)}
    assert await _counts(store, "user-anna") == {"automation.garage": (1, 1, 0)}


async def test_counts_outlive_deleting_and_purging(store: NotificationStore) -> None:
    store.add(_record("old", [ANNA], dt_util.utcnow() - timedelta(days=40)))
    store.add(_record("new", [ANNA]))
    await store.async_flush()
    await store.async_delete("new")
    await store.async_purge(30, 1000, 2)

    assert await _counts(store) == {"automation.garage": (2, 0, 0)}


async def test_counts_are_kept_whole_calendar_years_and_as_long_as_the_notifications(
    store: NotificationStore,
) -> None:
    oldest_kept = year_start(dt_util.now(), 2)
    store.add(_record("before", [ANNA], oldest_kept - timedelta(days=1)))
    store.add(_record("within", [ANNA], oldest_kept + timedelta(days=1)))
    await store.async_flush()

    await store.async_purge(1, 1000, 2)
    assert (await _counts(store))["automation.garage"][0] == 1

    store.add(_record("again", [ANNA], oldest_kept - timedelta(days=1)))
    await store.async_flush()
    await store.async_purge(3650, 1000, 2)
    assert (await _counts(store))["automation.garage"][0] == 2


async def test_a_failure_counts_when_it_is_known(store: NotificationStore) -> None:
    store.add(_record("door", [ANNA]))
    store.add(_record("family", [], group="notify.family", channel="notify.family"))
    store.add_inner_call("family", Call("notify.phone_anna", [ANNA], "c1"))
    store.add_inner_call("family", Call("notify.phone_ben", [BEN], "c2"))
    store.mark_failed("door", None, "Chat not found")
    store.mark_failed("family", "notify.phone_ben", "Error sending notification to Ben")
    store.mark_failed("family", "notify.phone_anna", "Error sending notification to Anna")

    assert await _counts(store, failed=True) == {"automation.garage": (2, 0, 0, 2)}
    assert await _counts(store, "user-ben", failed=True) == {"automation.garage": (1, 0, 0, 1)}


async def test_filling_the_counts_of_older_notifications_matches_counting_them_as_they_come(tmp_path: Path) -> None:
    store = NotificationStore(str(tmp_path / "journal.db"))
    await store.async_open()
    start = dt_util.utcnow() - timedelta(hours=5)
    for minute in range(6):
        store.add(_record(f"b{minute}", [ANNA, BEN], start + timedelta(minutes=minute), data=BUTTONS))
    for minute in range(4):
        store.add(_record(f"a{minute}", [ANNA], start + timedelta(minutes=20 + minute)))
    store.add(_record("group", [], start + timedelta(minutes=25), group="notify.family"))
    store.add_inner_call("group", Call("notify.phone_anna", [ANNA], "g1"))
    store.add(_record("bell", [BELL], start + timedelta(hours=1), origin=Origin(kind=OriginKind.SYSTEM)))
    store.add(_record("family", [], start + timedelta(hours=2), group="notify.family"))
    store.add_inner_call("family", Call("notify.phone_anna", [ANNA], "c1"))
    store.add_inner_call("family", Call("notify.phone_ben", [BEN], "c2"))
    store.mark_failed("family", "notify.phone_ben", "Error sending notification to Ben")
    store.mark_failed("a0", None, "Chat not found")
    await store.async_flush()
    await store.async_add_answer("notify", Answer(action="CLOSE", time=dt_util.utcnow(), user_id="user-ben"))
    expected = {user: await _counts(store, user, failed=True) for user in (None, "user-anna", "user-ben")}
    await store.async_close()

    connection = sqlite3.connect(tmp_path / "journal.db")
    with connection:
        connection.execute("DELETE FROM notification_counts")
        _fill_counts(connection)
    connection.close()
    store = NotificationStore(str(tmp_path / "journal.db"))
    await store.async_open()
    try:
        assert {user: await _counts(store, user, failed=True) for user in (None, "user-anna", "user-ben")} == expected
    finally:
        await store.async_close()


def test_week_starts_on_the_users_first_weekday() -> None:
    now = datetime(2026, 11, 15, 18, 30, tzinfo=BERLIN)

    monday = period("week", 0, 0, now)
    sunday = period("week", 0, 6, now)

    assert (monday.start, monday.end) == (datetime(2026, 11, 9, tzinfo=BERLIN), datetime(2026, 11, 16, tzinfo=BERLIN))
    assert (sunday.start, sunday.end) == (datetime(2026, 11, 15, tzinfo=BERLIN), datetime(2026, 11, 22, tzinfo=BERLIN))
    assert monday.compare_start == datetime(2026, 11, 2, tzinfo=BERLIN)
    assert monday.compare_end == datetime(2026, 11, 8, 18, 30, tzinfo=BERLIN)
    assert len(monday.buckets) == 7


def test_a_day_has_as_many_hours_as_the_clock_shows() -> None:
    spring = period("day", 0, 0, datetime(2026, 3, 29, 12, tzinfo=BERLIN))
    autumn = period("day", 0, 0, datetime(2026, 10, 25, 12, tzinfo=BERLIN))

    assert len(spring.buckets) == 23
    assert len(autumn.buckets) == 25


def test_a_half_hour_time_zone_keeps_its_hours() -> None:
    day = period("day", 0, 0, datetime(2026, 11, 15, 12, tzinfo=KOLKATA))
    midnight = int(datetime(2026, 11, 15, tzinfo=KOLKATA).timestamp())
    half_past = int(datetime(2026, 11, 15, 0, 30, tzinfo=KOLKATA).timestamp())

    summary = summarize(
        [(midnight, "automation.garage", 1, 0, 0, 0), (half_past, "automation.garage", 2, 0, 0, 0)], {}, day, KOLKATA
    )

    assert midnight % 900 == 0
    assert len(day.buckets) == 24
    assert day.buckets[0] == datetime(2026, 11, 15, tzinfo=KOLKATA)
    assert summary["buckets"][0]["counts"] == {"automation.garage": 3}
    assert summary["heatmap"][6][0] == 3


def test_months_and_years_page_back() -> None:
    now = datetime(2026, 1, 15, tzinfo=BERLIN)

    december = period("month", 1, 0, now)
    last_year = period("year", 1, 0, now)

    assert (december.start, december.end) == (datetime(2025, 12, 1, tzinfo=BERLIN), datetime(2026, 1, 1, tzinfo=BERLIN))
    assert len(december.buckets) == 31
    assert december.compare_end == datetime(2025, 12, 1, tzinfo=BERLIN)
    assert last_year.start == datetime(2025, 1, 1, tzinfo=BERLIN)
    assert len(last_year.buckets) == 12


def test_summary_buckets_heatmap_night_and_comparison() -> None:
    week = period("week", 0, 0, datetime(2026, 11, 15, 18, 30, tzinfo=BERLIN))
    tuesday_night = int(datetime(2026, 11, 10, 23, tzinfo=BERLIN).timestamp())
    friday_noon = int(datetime(2026, 11, 13, 12, tzinfo=BERLIN).timestamp())

    summary = summarize(
        [(tuesday_night, "automation.garage", 2, 1, 1, 1), (friday_noon, "integration.server_watch", 6, 0, 0, 0)],
        {"automation.garage": (4, 2)},
        week,
        BERLIN,
    )

    assert summary["totals"] == {
        "notifications": 8,
        "with_buttons": 1,
        "answered": 1,
        "failed": 1,
        "bursts": 1,
        "night": 2,
        "previous": 4,
        "previous_failed": 2,
    }
    assert [bucket["counts"] for bucket in summary["buckets"]][1] == {"automation.garage": 2}
    assert summary["buckets"][4]["counts"] == {"integration.server_watch": 6}
    assert summary["heatmap"][1][23] == 2
    assert [(o["key"], o["notifications"], o["previous"]) for o in summary["origins"]] == [
        ("integration.server_watch", 6, 0),
        ("automation.garage", 2, 4),
    ]


async def _setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _call(client, **msg):
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_statistics_command(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: User,
    hass_read_only_user: User,
    hass_read_only_access_token: str,
) -> None:
    runtime = await _setup(hass)
    admin = Recipient(kind=RecipientKind.PERSON, id="person.anna", name="Anna", user_id=hass_admin_user.id)
    reader = Recipient(kind=RecipientKind.PERSON, id="person.ben", name="Ben", user_id=hass_read_only_user.id)
    gone = Origin(kind=OriginKind.AUTOMATION, entity_id="automation.gone", name="Removed lamp")
    runtime.store.add(_record("garage", [admin], data=BUTTONS))
    runtime.store.add(_record("lamp", [reader], origin=gone))
    runtime.store.add(_record("journal", [reader], origin=Origin(kind=OriginKind.INTEGRATION, integration=DOMAIN)))
    runtime.store.add(_record("hand", [admin], origin=Origin(kind=OriginKind.USER, user_id=hass_admin_user.id)))
    await runtime.store.async_flush()
    hass.states.async_set("automation.garage", "on", {"friendly_name": "Garage gate"})

    client = await hass_ws_client(hass)
    result = (await _call(client, type=f"{DOMAIN}/statistics", period="week", time_zone="UTC"))["result"]
    assert result["period"] == "week"
    assert len(result["buckets"]) == 7
    assert result["totals"]["notifications"] == 4
    assert result["has_older"] is False
    assert result["comparable"] is False
    fallback = (await _call(client, type=f"{DOMAIN}/statistics", period="day", time_zone="../etc/x"))["result"]
    assert fallback["totals"]["notifications"] == 4
    assert result["kept_since"] is not None
    assert {o["key"]: o["name"] for o in result["origins"]} == {
        "automation.garage": "Garage gate",
        "automation.gone": "Removed lamp",
        f"integration.{DOMAIN}": "Notification Journal",
        "user": None,
    }

    reader_result = (
        await _call(
            await hass_ws_client(hass, hass_read_only_access_token),
            type=f"{DOMAIN}/statistics",
            period="year",
            user_id=hass_admin_user.id,
        )
    )["result"]
    assert reader_result["totals"]["notifications"] == 2
    assert {o["key"] for o in reader_result["origins"]} == {"automation.gone", f"integration.{DOMAIN}"}
