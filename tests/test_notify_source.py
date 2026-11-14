"""Tests of recording notify calls: recipients, groups and origin."""

from types import SimpleNamespace

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import (
    CONF_EXCLUDED_CHANNELS,
    CONF_RECORD_NOTIFY,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.notification_journal.models import NotificationRecord, OriginKind, RecipientKind
from custom_components.notification_journal.store import Query


@pytest.fixture
async def phones(hass: HomeAssistant) -> list[ServiceCall]:
    """Two plain notify actions and a legacy group "family" over both."""
    calls: list[ServiceCall] = []
    for name in ("phone_anna", "phone_ben"):
        hass.services.async_register("notify", name, calls.append)
    assert await async_setup_component(
        hass,
        "notify",
        {
            "notify": [
                {"platform": "group", "name": "family", "services": [{"action": "phone_anna"}, {"action": "phone_ben"}]}
            ]
        },
    )
    await hass.async_block_till_done()
    return calls


@pytest.fixture
async def anna(hass: HomeAssistant) -> str:
    """Anna is a person whose companion app is behind notify.phone_anna."""
    user = await hass.auth.async_create_user("Anna")
    hass.states.async_set("person.anna", "home", {"user_id": user.id, "friendly_name": "Anna"})
    hass.data.setdefault("notify_services", {}).setdefault("mobile_app", []).append(
        SimpleNamespace(registered_targets={"phone_anna": "webhook-anna"})
    )
    MockConfigEntry(domain="mobile_app", data={"webhook_id": "webhook-anna", "user_id": user.id}).add_to_hass(hass)
    return user.id


async def _setup(hass: HomeAssistant, **options: object) -> RuntimeData:
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _records(runtime: RuntimeData) -> list[NotificationRecord]:
    await runtime.store.async_flush()
    return (await runtime.store.async_query(Query(limit=1000))).records


async def _only(runtime: RuntimeData) -> NotificationRecord:
    records = await _records(runtime)
    assert len(records) == 1, records
    return records[0]


async def test_direct_call_records_message_title_and_data(hass: HomeAssistant, phones: list) -> None:
    runtime = await _setup(hass)

    await hass.services.async_call(
        "notify", "phone_ben", {"title": "Garage", "message": "Door open", "data": {"tag": "garage"}}, blocking=True
    )

    record = await _only(runtime)
    assert (record.channel, record.title, record.message) == ("notify.phone_ben", "Garage", "Door open")
    assert record.data == {"data": {"tag": "garage"}}
    assert [(r.kind, r.id) for r in record.recipients] == [(RecipientKind.CHANNEL, "notify.phone_ben")]
    assert record.group is None
    assert record.inner_calls == []


async def test_companion_app_resolves_to_person(hass: HomeAssistant, phones: list, anna: str) -> None:
    runtime = await _setup(hass)

    await hass.services.async_call("notify", "phone_anna", {"message": "Hi"}, blocking=True)

    recipient = (await _only(runtime)).recipients[0]
    assert (recipient.kind, recipient.id, recipient.name, recipient.user_id) == (
        RecipientKind.PERSON,
        "person.anna",
        "Anna",
        anna,
    )


async def test_companion_app_without_person_shows_device_name(hass: HomeAssistant, phones: list) -> None:
    hass.data.setdefault("notify_services", {}).setdefault("mobile_app", []).append(
        SimpleNamespace(registered_targets={"phone_ben": "webhook-ben"})
    )
    MockConfigEntry(
        domain="mobile_app", data={"webhook_id": "webhook-ben", "user_id": "nobody", "device_name": "Ben's phone "}
    ).add_to_hass(hass)
    runtime = await _setup(hass)

    await hass.services.async_call("notify", "phone_ben", {"message": "Hi"}, blocking=True)

    recipient = (await _only(runtime)).recipients[0]
    assert (recipient.kind, recipient.id, recipient.name) == (RecipientKind.CHANNEL, "notify.phone_ben", "Ben's phone")


async def test_group_call_is_one_record_with_inner_calls(hass: HomeAssistant, phones: list, anna: str) -> None:
    runtime = await _setup(hass)

    await hass.services.async_call("notify", "family", {"message": "Dinner"}, blocking=True)
    await hass.async_block_till_done()

    assert len(phones) == 2
    record = await _only(runtime)
    assert record.group == "notify.family"
    assert {r.id for r in record.recipients} == {"person.anna", "notify.phone_ben"}
    assert sorted(call.channel for call in record.inner_calls) == ["notify.phone_anna", "notify.phone_ben"]
    assert record.user_ids == {anna}


async def test_call_from_automation_carries_exact_trace(hass: HomeAssistant, phones: list) -> None:
    runtime = await _setup(hass)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "garage_door",
                "alias": "Garage door",
                "triggers": {"trigger": "event", "event_type": "garage_open"},
                "actions": [
                    {"action": "notify.family", "data": {"message": "Garage open"}},
                    {"action": "notify.phone_ben", "data": {"message": "Close it"}},
                ],
            }
        },
    )
    await hass.async_block_till_done()

    hass.bus.async_fire("garage_open")
    await hass.async_block_till_done()

    records = await _records(runtime)
    assert [r.message for r in records] == ["Close it", "Garage open"]
    run_ids = list(hass.data["trace"]["automation.garage_door"].runs)
    for record in records:
        assert record.origin.kind is OriginKind.AUTOMATION
        assert record.origin.entity_id == "automation.garage_door"
        assert record.origin.name == "Garage door"
        assert record.origin.run_id == run_ids[-1]
    assert len(records[1].inner_calls) == 2
    assert records[0].inner_calls == []


async def test_call_by_user_has_user_origin(hass: HomeAssistant, phones: list) -> None:
    runtime = await _setup(hass)
    user = await hass.auth.async_create_user("Admin")

    await hass.services.async_call(
        "notify", "phone_ben", {"message": "Test"}, blocking=True, context=Context(user_id=user.id)
    )

    origin = (await _only(runtime)).origin
    assert (origin.kind, origin.user_id) == (OriginKind.USER, user.id)


async def test_excluded_channel_is_not_recorded(hass: HomeAssistant, phones: list) -> None:
    runtime = await _setup(hass, **{CONF_EXCLUDED_CHANNELS: ["phone_ben"]})

    await hass.services.async_call("notify", "phone_ben", {"message": "Hidden"}, blocking=True)
    await hass.services.async_call("notify", "phone_anna", {"message": "Shown"}, blocking=True)

    assert (await _only(runtime)).message == "Shown"


async def test_nothing_is_recorded_when_the_source_is_off(hass: HomeAssistant, phones: list) -> None:
    runtime = await _setup(hass, **{CONF_RECORD_NOTIFY: False})

    await hass.services.async_call("notify", "phone_ben", {"message": "x"}, blocking=True)

    assert await _records(runtime) == []


async def test_notify_entity_group_resolves_members(hass: HomeAssistant) -> None:
    runtime = await _setup(hass)
    hass.states.async_set("notify.kitchen_display", "unknown", {"friendly_name": "Kitchen display"})
    hass.states.async_set("notify.hall_display", "unknown", {"friendly_name": "Hall display"})
    hass.states.async_set(
        "notify.displays", "unknown", {"entity_id": ["notify.kitchen_display", "notify.hall_display"]}
    )

    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {
            "domain": "notify",
            "service": "send_message",
            "service_data": {"entity_id": ["notify.displays"], "message": "Rain"},
        },
    )
    await hass.async_block_till_done()

    record = await _only(runtime)
    assert record.group == "notify.displays"
    assert [(r.kind, r.name) for r in record.recipients] == [
        (RecipientKind.ENTITY, "Kitchen display"),
        (RecipientKind.ENTITY, "Hall display"),
    ]


async def test_other_domains_are_ignored(hass: HomeAssistant) -> None:
    runtime = await _setup(hass)
    hass.services.async_register("light", "turn_on", lambda call: None)

    await hass.services.async_call("light", "turn_on", {}, blocking=True)

    assert await _records(runtime) == []


async def test_notify_group_entity_attaches_its_member_call(hass: HomeAssistant) -> None:
    runtime = await _setup(hass)
    hass.states.async_set("notify.kitchen_display", "unknown", {"friendly_name": "Kitchen display"})
    hass.states.async_set("notify.hall_display", "unknown", {"friendly_name": "Hall display"})
    hass.states.async_set(
        "notify.displays", "unknown", {"entity_id": ["notify.kitchen_display", "notify.hall_display"]}
    )
    context = Context()

    for entity_ids in (["notify.displays"], ["notify.kitchen_display", "notify.hall_display"]):
        hass.bus.async_fire(
            EVENT_CALL_SERVICE,
            {
                "domain": "notify",
                "service": "send_message",
                "service_data": {"entity_id": entity_ids, "message": "Rain"},
            },
            context=context,
        )
    await hass.async_block_till_done()

    record = await _only(runtime)
    assert record.group == "notify.displays"
    assert [call.channel for call in record.inner_calls] == ["notify.kitchen_display", "notify.hall_display"]
    assert [[r.name for r in call.recipients] for call in record.inner_calls] == [["Kitchen display"], ["Hall display"]]


async def test_send_message_to_an_area(hass: HomeAssistant) -> None:
    runtime = await _setup(hass)
    kitchen = ar.async_get(hass).async_create("Kitchen")
    registry = er.async_get(hass)
    display = registry.async_get_or_create("notify", "demo", "display", suggested_object_id="kitchen_display")
    registry.async_update_entity(display.entity_id, area_id=kitchen.id)
    hass.states.async_set(display.entity_id, "unknown", {"friendly_name": "Kitchen display"})

    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {"domain": "notify", "service": "send_message", "service_data": {"area_id": kitchen.id, "message": "Tea"}},
    )
    await hass.async_block_till_done()

    record = await _only(runtime)
    assert record.channel == display.entity_id
    assert record.data is None


async def test_excluded_group_drops_its_member_calls_too(hass: HomeAssistant, phones: list) -> None:
    runtime = await _setup(hass, **{CONF_EXCLUDED_CHANNELS: ["notify.family"]})

    await hass.services.async_call("notify", "family", {"message": "Dinner"}, blocking=True)
    await hass.services.async_call("notify", "phone_ben", {"message": "Direct"}, blocking=True)

    assert [r.message for r in await _records(runtime)] == ["Direct"]
