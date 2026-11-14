"""Tests of recording the notifications under the bell (persistent_notification)."""

from homeassistant.auth.models import User
from homeassistant.components import persistent_notification
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import CONF_RECORD_PERSISTENT, DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.models import NotificationRecord, OriginKind, RecipientKind, Status
from custom_components.notification_journal.store import Query


async def _setup(hass: HomeAssistant, **options: object) -> MockConfigEntry:
    assert await async_setup_component(hass, "persistent_notification", {})
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _records(runtime: RuntimeData) -> list[NotificationRecord]:
    await runtime.store.async_flush()
    return (await runtime.store.async_query(Query(limit=1000, newest_first=False))).records


async def test_created_by_a_user_is_recorded_for_everyone(hass: HomeAssistant, hass_admin_user: User) -> None:
    entry = await _setup(hass)

    await hass.services.async_call(
        "persistent_notification",
        "create",
        {"title": "Backup", "message": "See [the log](/config/logs)", "notification_id": "backup"},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )

    (record,) = await _records(entry.runtime_data)
    assert (record.source, record.channel, record.source_ref) == (
        "persistent_notification",
        "persistent_notification",
        "backup",
    )
    assert (record.title, record.message) == ("Backup", "See [the log](/config/logs)")
    assert record.status is Status.SENT
    assert record.origin.kind is OriginKind.USER
    assert record.origin.user_id == hass_admin_user.id
    assert [r.kind for r in record.recipients] == [RecipientKind.EVERYONE]
    assert record.visible_to("any-user")


async def test_created_by_home_assistant_itself(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    persistent_notification.async_create(hass, "New devices discovered", "Discovered", "config_entry_discovery")
    await hass.async_block_till_done()

    (record,) = await _records(entry.runtime_data)
    assert record.origin.kind is OriginKind.SYSTEM
    assert record.source_ref == "config_entry_discovery"


async def test_dismissing_records_when_and_by_whom(hass: HomeAssistant, hass_admin_user: User) -> None:
    entry = await _setup(hass)
    persistent_notification.async_create(hass, "Login attempt failed", None, "http-login")
    await hass.async_block_till_done()

    await hass.services.async_call(
        "persistent_notification",
        "dismiss",
        {"notification_id": "http-login"},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )

    (record,) = await _records(entry.runtime_data)
    assert record.status is Status.DISMISSED
    assert record.status_time is not None
    assert record.status_by is not None
    assert record.status_by.kind is OriginKind.USER
    assert record.status_by.user_id == hass_admin_user.id


async def test_dismissed_by_home_assistant(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    persistent_notification.async_create(hass, "Discovered", None, "discovery")
    await hass.async_block_till_done()

    persistent_notification.async_dismiss(hass, "discovery")
    await hass.async_block_till_done()

    (record,) = await _records(entry.runtime_data)
    assert record.status is Status.DISMISSED
    assert record.status_by is not None
    assert record.status_by.kind is OriginKind.SYSTEM


async def test_creating_the_same_id_again_adds_a_record_and_replaces_the_first(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    persistent_notification.async_create(hass, "First attempt", "Login failed", "http-login")
    await hass.async_block_till_done()
    persistent_notification.async_create(hass, "Second attempt", "Login failed", "http-login")
    await hass.async_block_till_done()

    first, second = await _records(entry.runtime_data)
    assert (first.message, first.status) == ("First attempt", Status.REPLACED)
    assert first.status_time is not None
    assert (second.message, second.status) == ("Second attempt", Status.SENT)


async def test_notify_persistent_notification_gives_two_records(hass: HomeAssistant, hass_admin_user: User) -> None:
    assert await async_setup_component(hass, "notify", {})
    entry = await _setup(hass)

    await hass.services.async_call(
        "notify",
        "persistent_notification",
        {"message": "Washing machine done", "title": "Laundry"},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )

    records = await _records(entry.runtime_data)
    assert sorted(r.source for r in records) == ["notify", "persistent_notification"]
    bell = next(r for r in records if r.source == "persistent_notification")
    assert bell.origin.kind is OriginKind.USER
    assert bell.message == "Washing machine done"


async def test_option_turns_recording_off(hass: HomeAssistant) -> None:
    entry = await _setup(hass, **{CONF_RECORD_PERSISTENT: False})

    persistent_notification.async_create(hass, "Not recorded", None, "off")
    await hass.async_block_till_done()

    assert await _records(entry.runtime_data) == []


async def test_reload_catches_up_without_duplicates(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "persistent_notification", {})
    persistent_notification.async_create(hass, "Before the integration", None, "early")
    persistent_notification.async_create(hass, "Gone while unloaded", None, "gone")
    await hass.async_block_till_done()
    entry = await _setup(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    persistent_notification.async_dismiss(hass, "gone")
    persistent_notification.async_create(hass, "While unloaded", None, "late")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    records = {r.source_ref: r for r in await _records(entry.runtime_data)}
    assert sorted(records) == ["early", "gone", "late"]
    assert records["early"].status is Status.SENT
    assert records["gone"].status is Status.DISMISSED
    assert records["gone"].status_by is not None
    assert records["gone"].status_by.kind is OriginKind.SYSTEM
    assert records["late"].status is Status.SENT


async def test_every_user_sees_the_bell(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    await _setup(hass)
    persistent_notification.async_create(hass, "Update available", "Update", "update")
    await hass.async_block_till_done()
    await hass.config_entries.async_loaded_entries(DOMAIN)[0].runtime_data.store.async_flush()

    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": f"{DOMAIN}/list"})
    result = (await client.receive_json())["result"]
    assert [r["message"] for r in result["records"]] == ["Update available"]
    assert result["records"][0]["recipients"][0]["kind"] == "everyone"
