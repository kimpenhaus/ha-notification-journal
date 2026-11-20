"""Tests of what automations get: the events, the query action and today's sensors."""

import asyncio
from datetime import timedelta

import pytest
from homeassistant.auth.models import User
from homeassistant.core import Context, Event, HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import (
    CONF_NON_ADMIN_VISIBILITY,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_FAILED,
    EVENT_RECORDED,
    SERVICE_QUERY,
)
from custom_components.notification_journal.models import (
    Call,
    NotificationRecord,
    Origin,
    OriginKind,
    Recipient,
    RecipientKind,
    Status,
)

GARAGE = Origin(kind=OriginKind.AUTOMATION, entity_id="automation.garage", name="Garage door")


def _person(user: User, name: str) -> Recipient:
    return Recipient(kind=RecipientKind.PERSON, id=f"person.{name.lower()}", name=name, user_id=user.id)


def _record(record_id: str, message: str, recipients: list[Recipient], **kw) -> NotificationRecord:
    return NotificationRecord(
        id=record_id,
        time=dt_util.utcnow() - kw.pop("age", timedelta(0)),
        source="notify",
        channel=kw.pop("channel", "notify.phone"),
        title=kw.pop("title", None),
        message=message,
        data=kw.pop("data", None),
        recipients=recipients,
        origin=GARAGE,
        context_id=f"ctx-{record_id}",
        **kw,
    )


async def _setup(hass: HomeAssistant, **options: object) -> RuntimeData:
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _settle(hass: HomeAssistant, runtime: RuntimeData) -> None:
    await runtime.store.async_flush()
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_recorded_event_carries_the_notification(hass: HomeAssistant, hass_admin_user: User) -> None:
    runtime = await _setup(hass)
    hass.states.async_set("person.anna", "home", {"friendly_name": "Anna M."})
    events: list[Event] = async_capture_events(hass, EVENT_RECORDED)

    runtime.store.add(
        _record("a", "Door open", [_person(hass_admin_user, "Anna")], title="Garage", data={"data": {"tag": "garage"}})
    )
    await _settle(hass, runtime)

    assert len(events) == 1
    data = events[0].data
    assert (data["id"], data["title"], data["message"], data["status"], data["tag"]) == (
        "a",
        "Garage",
        "Door open",
        "sent",
        "garage",
    )
    assert data["recipients"] == [{"id": "person.anna", "name": "Anna M."}]
    assert data["origin"] == {"key": "automation.garage", "name": "Garage door"}


async def test_a_notification_sent_during_an_import_is_reported(hass: HomeAssistant, hass_admin_user: User) -> None:
    runtime = await _setup(hass)
    await _settle(hass, runtime)
    events: list[Event] = async_capture_events(hass, EVENT_RECORDED)
    importing, done = asyncio.Event(), asyncio.Event()

    async def import_() -> None:
        async with runtime.store.async_batch():
            runtime.store.add(_record("old", "Imported", []))
            importing.set()
            await done.wait()

    batch = asyncio.get_running_loop().create_task(import_())
    await importing.wait()
    runtime.store.add(_record("new", "Door open", [_person(hass_admin_user, "Anna")]))
    await _settle(hass, runtime)
    done.set()
    await batch
    await _settle(hass, runtime)

    assert [event.data["id"] for event in events] == ["new"]


async def test_failed_event_names_what_failed(hass: HomeAssistant, hass_admin_user: User) -> None:
    runtime = await _setup(hass)
    anna = _person(hass_admin_user, "Anna")
    calls = [Call("notify.phone_anna", [anna], "c1"), Call("notify.phone_ben", [], "c2")]
    runtime.store.add(
        _record("family", "Dinner", [anna], channel="notify.family", group="notify.family", inner_calls=calls)
    )
    await _settle(hass, runtime)
    events: list[Event] = async_capture_events(hass, EVENT_FAILED)

    runtime.store.mark_failed("family", "notify.phone_ben", "push failed")
    await _settle(hass, runtime)

    assert len(events) == 1
    assert events[0].data["status"] == "partial"
    assert events[0].data["failed_calls"] == [{"channel": "notify.phone_ben", "error": "push failed"}]


async def _query(hass: HomeAssistant, user: User | None = None, **data: object) -> dict:
    context = Context(user_id=user.id if user else None)
    return await hass.services.async_call(
        DOMAIN, SERVICE_QUERY, data, blocking=True, return_response=True, context=context
    )


async def _fill(hass: HomeAssistant, runtime: RuntimeData, admin: User, reader: User) -> None:
    runtime.store.add(_record("admin", "for admin", [_person(admin, "Anna")], age=timedelta(minutes=2)))
    runtime.store.add(
        _record("reader", "for reader", [_person(reader, "Ben")], status=Status.FAILED, age=timedelta(minutes=1))
    )
    await _settle(hass, runtime)


async def test_query_returns_what_the_caller_may_see(
    hass: HomeAssistant, hass_admin_user: User, hass_read_only_user: User
) -> None:
    runtime = await _setup(hass)
    await _fill(hass, runtime, hass_admin_user, hass_read_only_user)

    everything = await _query(hass)
    assert [r["id"] for r in everything["records"]] == ["reader", "admin"]
    assert everything["total"] == 2
    assert [r["id"] for r in (await _query(hass, hass_admin_user, newest_first=False))["records"]] == [
        "admin",
        "reader",
    ]
    assert [r["id"] for r in (await _query(hass, hass_read_only_user))["records"]] == ["reader"]
    assert [r["id"] for r in (await _query(hass, status="failed"))["records"]] == ["reader"]
    assert [r["id"] for r in (await _query(hass, text="admin", limit=1))["records"]] == ["admin"]
    since = (dt_util.now() - timedelta(seconds=90)).replace(tzinfo=None).isoformat()
    assert [r["id"] for r in (await _query(hass, since=since))["records"]] == ["reader"]


async def test_query_is_refused_when_users_see_nothing(hass: HomeAssistant, hass_read_only_user: User) -> None:
    await _setup(hass, **{CONF_NON_ADMIN_VISIBILITY: "none"})

    with pytest.raises(Unauthorized):
        await _query(hass, hass_read_only_user)


async def test_sensors_count_today(hass: HomeAssistant, hass_admin_user: User) -> None:
    runtime = await _setup(hass)
    registry = er.async_get(hass)
    entry_id = hass.config_entries.async_entries(DOMAIN)[0].entry_id
    today = registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_notifications_today")
    failed = registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_failed_today")
    assert today is not None
    assert failed is not None
    assert hass.states.get(today).state == "0"

    anna = [_person(hass_admin_user, "Anna")]
    runtime.store.add(_record("a", "Door open", anna))
    runtime.store.add(_record("b", "Window open", anna, status=Status.FAILED))
    runtime.store.add(_record("old", "Yesterday", anna, age=timedelta(days=2)))
    await _settle(hass, runtime)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=15))
    await hass.async_block_till_done()

    assert (hass.states.get(today).state, hass.states.get(failed).state) == ("2", "1")
