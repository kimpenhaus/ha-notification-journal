"""Tests of the SQLite store."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.util import dt as dt_util

from custom_components.notification_journal.models import (
    Call,
    NotificationRecord,
    Origin,
    OriginKind,
    Recipient,
    RecipientKind,
    Status,
)
from custom_components.notification_journal.store import NotificationStore, Query

ANNA = Recipient(kind=RecipientKind.PERSON, id="person.anna", name="Anna", user_id="user-anna")
BEN = Recipient(kind=RecipientKind.PERSON, id="person.ben", name="Ben", user_id="user-ben")
DISPLAY = Recipient(kind=RecipientKind.ENTITY, id="notify.display", name="Kitchen display")
GARAGE = Origin(kind=OriginKind.AUTOMATION, entity_id="automation.garage", name="Garage door", run_id="r1")


def _record(record_id: str, message: str, recipients: list[Recipient], age: timedelta = timedelta(0), **kw):
    return NotificationRecord(
        id=record_id,
        time=dt_util.utcnow() - age,
        source="notify",
        channel=kw.pop("channel", "notify.phone"),
        title=kw.pop("title", None),
        message=message,
        data=kw.pop("data", None),
        recipients=recipients,
        origin=kw.pop("origin", GARAGE),
        context_id=f"ctx-{record_id}",
        **kw,
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[NotificationStore]:
    """An open store in a temporary file."""
    store = NotificationStore(str(tmp_path / "history.db"))
    await store.async_open()
    yield store
    await store.async_close()


async def _ids(store: NotificationStore, **query) -> list[str]:
    await store.async_flush()
    return [r.id for r in (await store.async_query(Query(**query))).records]


async def test_round_trip_keeps_every_field(store: NotificationStore) -> None:
    record = _record(
        "a",
        "Door open",
        [ANNA],
        title="Garage",
        data={"data": {"tag": "garage"}},
        group="notify.family",
        status=Status.FAILED,
        error="rate limited",
        inner_calls=[Call(channel="notify.phone_anna", recipients=[ANNA], context_id="ctx-inner")],
    )
    store.add(record)
    await store.async_flush()

    assert await store.async_get("a") == record


async def test_records_survive_reopening(tmp_path: Path) -> None:
    path = str(tmp_path / "history.db")
    first = NotificationStore(path)
    await first.async_open()
    first.add(_record("a", "kept", [ANNA]))
    await first.async_close()

    second = NotificationStore(path)
    await second.async_open()
    assert await _ids(second) == ["a"]
    await second.async_close()


async def test_newest_first_paging_and_total(store: NotificationStore) -> None:
    for index, age in enumerate([3, 1, 2]):
        store.add(_record(f"r{index}", "x", [ANNA], age=timedelta(minutes=age)))
    await store.async_flush()

    assert await _ids(store) == ["r1", "r2", "r0"]
    assert await _ids(store, newest_first=False) == ["r0", "r2", "r1"]
    page = await store.async_query(Query(limit=2, offset=1))
    assert ([r.id for r in page.records], page.total) == (["r2", "r0"], 3)


async def test_user_sees_only_records_addressed_to_them(store: NotificationStore) -> None:
    store.add(_record("anna", "a", [ANNA]))
    store.add(_record("both", "b", [ANNA, BEN]))
    store.add(_record("display", "c", [DISPLAY]))
    store.add(_record("group", "d", [], inner_calls=[Call("notify.phone_ben", [BEN], "ctx")]))

    assert set(await _ids(store, user_id="user-ben")) == {"both", "group"}
    assert set(await _ids(store, user_id="user-anna")) == {"anna", "both"}


async def test_inner_call_added_later_is_visible_and_searchable(store: NotificationStore) -> None:
    store.add(_record("g", "Dinner", [], group="notify.family"))
    store.add_inner_call("g", Call("notify.phone_ben", [BEN], "ctx-1"))
    store.add_inner_call("g", Call("notify.display", [DISPLAY], "ctx-2"))
    store.add_inner_call("missing", Call("notify.phone_ben", [BEN], "ctx-3"))

    assert await _ids(store, user_id="user-ben") == ["g"]
    assert await _ids(store, text="kitchen") == ["g"]
    record = await store.async_get("g")
    assert [c.channel for c in record.inner_calls] == ["notify.phone_ben", "notify.display"]


async def test_full_text_search(store: NotificationStore) -> None:
    store.add(_record("a", "The garage door is open", [ANNA], title="Garage"))
    store.add(_record("b", "Washing machine finished", [BEN], origin=Origin(kind=OriginKind.UNKNOWN)))

    assert await _ids(store, text="gar") == ["a"]
    assert await _ids(store, text="machine ben") == ["b"]
    assert await _ids(store, text="Garage door") == ["a"]
    assert await _ids(store, text='"quoted') == []


async def test_filters(store: NotificationStore) -> None:
    store.add(_record("a", "x", [ANNA], channel="notify.phone_anna", age=timedelta(days=2)))
    store.add(_record("b", "x", [ANNA], group="notify.family", channel="notify.family", status=Status.FAILED))
    store.add(_record("c", "x", [BEN], origin=Origin(kind=OriginKind.SCRIPT, entity_id="script.night")))

    assert await _ids(store, channel="notify.family") == ["b"]
    assert await _ids(store, status=Status.FAILED) == ["b"]
    assert await _ids(store, origin="script.night") == ["c"]
    assert await _ids(store, origin="automation.garage") == ["b", "a"]
    assert set(await _ids(store, since=dt_util.utcnow() - timedelta(days=1))) == {"b", "c"}
    assert await _ids(store, until=dt_util.utcnow() - timedelta(days=1)) == ["a"]


async def test_group_by_origin_sorts_within_each_origin(store: NotificationStore) -> None:
    alarm = Origin(kind=OriginKind.AUTOMATION, entity_id="automation.alarm", name="Alarm")
    by_hand = Origin(kind=OriginKind.USER, user_id="someone")
    weather = Origin(kind=OriginKind.INTEGRATION, name="Weather Coach", integration="weather_coach")
    tracker = Origin(kind=OriginKind.INTEGRATION, name="Parcel Tracker", integration="parcel_tracker")
    store.add(_record("garage-old", "a", [], age=timedelta(minutes=5)))
    store.add(_record("alarm", "b", [], age=timedelta(minutes=4), origin=alarm))
    store.add(_record("hand", "c", [], age=timedelta(minutes=3), origin=by_hand))
    store.add(_record("weather", "e", [], age=timedelta(minutes=3), origin=weather))
    store.add(_record("tracker", "f", [], age=timedelta(minutes=3), origin=tracker))
    store.add(_record("garage-new", "d", [], age=timedelta(minutes=2)))
    await store.async_flush()

    page = await store.async_query(Query(group_by_origin=True))
    assert [r.id for r in page.records] == ["alarm", "garage-new", "garage-old", "tracker", "weather", "hand"]
    assert page.groups == {
        "automation.alarm": 1,
        "automation.garage": 2,
        "integration.parcel_tracker": 1,
        "integration.weather_coach": 1,
        "user": 1,
    }
    ascending = await _ids(store, group_by_origin=True, newest_first=False, limit=2, offset=1)
    assert ascending == ["garage-old", "garage-new"]
    assert (await store.async_query(Query())).groups is None


async def test_archive_is_per_user(store: NotificationStore) -> None:
    store.add(_record("one", "a", [], age=timedelta(minutes=2)))
    store.add(_record("two", "b", [], age=timedelta(minutes=1)))
    await store.async_flush()

    assert await store.async_set_archived(["one", "missing"], "anna", archived=True, visible_to=None) == 1
    assert await _ids(store, archive_user_id="anna") == ["two"]
    assert await _ids(store, archive_user_id="anna", archived=True) == ["one"]
    assert await _ids(store, archive_user_id="ben") == ["two", "one"]
    assert await store.async_set_archived(["one"], "anna", archived=False, visible_to=None) == 1
    assert await _ids(store, archive_user_id="anna") == ["two", "one"]


async def test_purge_by_age_and_maximum(store: NotificationStore) -> None:
    for index in range(5):
        store.add(_record(f"r{index}", "x", [ANNA], age=timedelta(days=index * 10)))
    await store.async_flush()

    assert await store.async_purge(retention_days=25, max_entries=2, statistics_years=2) == 3
    assert await _ids(store) == ["r0", "r1"]
    assert await _ids(store, user_id="user-anna") == ["r0", "r1"]
    assert await _ids(store, text="x") == ["r0", "r1"]


async def test_backup_pause_holds_writes_until_resumed(store: NotificationStore, tmp_path: Path) -> None:
    store.add(_record("before", "x", [ANNA]))
    await store.async_pause_for_backup()

    assert (tmp_path / "history.db-wal").stat().st_size == 0
    store.add(_record("during", "x", [ANNA]))
    store.resume_after_backup()

    assert await _ids(store) == ["during", "before"]


async def test_search_ignores_words_without_letters_or_digits(store: NotificationStore) -> None:
    store.add(_record("a", "Garage door open", [ANNA]))
    await store.async_flush()

    assert await _ids(store, text="Garage - door") == ["a"]
    assert await _ids(store, text="&") == ["a"]


async def test_purge_tells_listeners(store: NotificationStore) -> None:
    changes: list[tuple[str, str]] = []
    store.async_add_listener(lambda change, record_id: changes.append((change, record_id)))
    store.add(_record("old", "Old", [ANNA], age=timedelta(days=40)))
    await store.async_flush()
    changes.clear()

    assert await store.async_purge(30, 1000, 2) == 1
    assert changes == [("reload", "")]
