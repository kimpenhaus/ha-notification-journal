"""Tests of the import from the recorder on first setup, and of removing the journal with the integration."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.notification_journal.const import DATABASE_FILE, DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.models import OriginKind
from custom_components.notification_journal.store import SCHEMA_VERSION, Query

USER = uuid4().hex
BUTTONS = {"actions": [{"action": "CLOSE_GARAGE", "title": "Close"}]}


@pytest.fixture
def mock_recorder_before_hass(async_setup_recorder_instance) -> None:
    """Let the recorder start before Home Assistant, as the tests of the import need it."""


def _notify(hass: HomeAssistant, service: str, message: str, context: Context, **data) -> None:
    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {"domain": "notify", "service": service, "service_data": {"message": message, **data}},
        context=context,
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _records(entry: MockConfigEntry):
    store = entry.runtime_data.store
    await store.async_flush()
    return (await store.async_query(Query(newest_first=False))).records


async def test_first_setup_imports_what_the_recorder_holds(recorder_mock, hass: HomeAssistant) -> None:
    automation = Context()
    hass.bus.async_fire(
        "automation_triggered", {"name": "Garage open", "entity_id": "automation.garage_open"}, context=automation
    )
    _notify(hass, "mobile_app_phone", "The garage is open", automation, title="Garage", data=BUTTONS)
    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {
            "domain": "tts",
            "service": "speak",
            "service_data": {"message": "Dinner", "media_player_entity_id": "media_player.kitchen"},
        },
        context=Context(),
    )
    _notify(hass, "mobile_app_phone", "Sent by hand", Context(user_id=USER))
    _notify(hass, "mobile_app_phone", "From an integration", Context())
    hass.bus.async_fire(
        EVENT_CALL_SERVICE, {"domain": "light", "service": "turn_on", "service_data": {}}, context=Context()
    )
    hass.bus.async_fire("mobile_app_notification_action", {"action": "CLOSE_GARAGE"}, context=Context(user_id=USER))
    await async_wait_recording_done(hass)

    entry = await _setup(hass)
    records = await _records(entry)

    assert [(r.source, r.message, r.origin.kind) for r in records] == [
        ("notify", "The garage is open", OriginKind.AUTOMATION),
        ("speech", "Dinner", OriginKind.UNKNOWN),
        ("notify", "Sent by hand", OriginKind.USER),
        ("notify", "From an integration", OriginKind.UNKNOWN),
    ]
    garage = records[0]
    assert (garage.origin.entity_id, garage.origin.name, garage.title) == (
        "automation.garage_open",
        "Garage open",
        "Garage",
    )
    assert all(record.origin.imported for record in records)
    assert [answer.action for answer in garage.answers] == ["CLOSE_GARAGE"]
    assert records[2].origin.user_id == USER
    assert garage.time < records[1].time < records[2].time

    _notify(hass, "mobile_app_phone", "Live", Context())
    await hass.async_block_till_done()
    live = (await _records(entry))[-1]
    assert (live.message, live.origin.imported) == ("Live", False)


async def test_member_calls_of_a_group_join_its_imported_record(recorder_mock, hass: HomeAssistant) -> None:
    for name in ("phone_anna", "phone_ben"):
        hass.services.async_register("notify", name, lambda call: None)
    group = {"platform": "group", "name": "family", "services": [{"action": "phone_anna"}, {"action": "phone_ben"}]}
    assert await async_setup_component(hass, "notify", {"notify": [group]})
    await hass.services.async_call("notify", "family", {"message": "Dinner"}, blocking=True)
    await hass.services.async_call("notify", "phone_ben", {"message": "Alone"}, blocking=True)
    await async_wait_recording_done(hass)

    entry = await _setup(hass)
    records = await _records(entry)

    assert [(r.message, r.group) for r in records] == [("Dinner", "notify.family"), ("Alone", None)]
    assert sorted(call.channel for call in records[0].inner_calls) == ["notify.phone_anna", "notify.phone_ben"]


async def test_an_existing_journal_imports_nothing(recorder_mock, hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    _notify(hass, "mobile_app_phone", "While unloaded", Context())
    await async_wait_recording_done(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert await _records(entry) == []


async def test_an_interrupted_import_goes_on_after_what_it_got_to(recorder_mock, hass: HomeAssistant) -> None:
    _notify(hass, "mobile_app_phone", "First", Context())
    await async_wait_recording_done(hass)
    entry = await _setup(hass)
    assert [r.message for r in await _records(entry)] == ["First"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    _notify(hass, "mobile_app_phone", "Second", Context())
    await async_wait_recording_done(hass)
    hass.config_entries.async_update_entry(entry, data={"import_before": dt_util.utcnow().timestamp()})

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert [r.message for r in await _records(entry)] == ["First", "Second"]
    assert "import_before" not in entry.data


async def test_a_failing_event_is_skipped(recorder_mock, hass: HomeAssistant) -> None:
    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {"domain": "telegram_bot", "service": "send_message", "service_data": {"message": "x", "chat_id": "@channel"}},
        context=Context(),
    )
    _notify(hass, "mobile_app_phone", "After it", Context())
    await async_wait_recording_done(hass)

    entry = await _setup(hass)

    assert [r.message for r in await _records(entry)] == ["After it"]


async def test_a_newer_journal_stays_when_the_integration_is_removed(
    recorder_mock, hass: HomeAssistant, config_dir: Path
) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    database = config_dir / DATABASE_FILE
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()

    await hass.config_entries.async_remove(entry.entry_id)

    assert database.exists()


async def test_removing_the_integration_removes_its_journal(
    recorder_mock, hass: HomeAssistant, config_dir: Path
) -> None:
    entry = await _setup(hass)
    database = config_dir / DATABASE_FILE
    copy = config_dir / f"{DATABASE_FILE}.bak-v4"
    other = config_dir / f"{DATABASE_FILE}.mine"
    copy.write_bytes(b"")
    other.write_bytes(b"")

    await hass.config_entries.async_remove(entry.entry_id)

    assert not database.exists()
    assert not copy.exists()
    assert other.exists()
