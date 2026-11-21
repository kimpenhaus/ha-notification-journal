"""Tests of sending any notification again to targets an administrator picks."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.notification_journal import RuntimeData, send
from custom_components.notification_journal.const import DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.models import NotificationRecord, OriginKind, Status
from custom_components.notification_journal.store import Query

COMPANION = frozenset({"notify.mobile_app_anna", "notify.mobile_app_ben"})


def _service(hass: HomeAssistant, domain: str, name: str, error: str | None = None) -> list[dict]:
    """An action that records what it received, and fails with the error if one is given."""
    received: list[dict] = []

    async def handle(call: ServiceCall) -> None:
        received.append(dict(call.data))
        if error:
            raise HomeAssistantError(error)

    hass.services.async_register(domain, name, handle)
    return received


async def _setup(hass: HomeAssistant) -> RuntimeData:
    hass.states.async_set("notify.kitchen_display", "unknown", {"friendly_name": "Kitchen display"})
    hass.states.async_set("media_player.kitchen", "idle", {"friendly_name": "Kitchen speaker"})
    hass.states.async_set("assist_satellite.office", "idle", {"friendly_name": "Office satellite"})
    hass.states.async_set("tts.cloud", "unknown", {"friendly_name": "Cloud"})
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


async def _records(hass: HomeAssistant, runtime: RuntimeData) -> list[NotificationRecord]:
    await hass.async_block_till_done()
    await runtime.store.async_flush()
    return (await runtime.store.async_query(Query(newest_first=False, limit=1000))).records


async def _send(client, record_id: str, *targets: dict) -> dict:
    await client.send_json_auto_id({"type": f"{DOMAIN}/send", "record_id": record_id, "targets": list(targets)})
    return await client.receive_json()


async def _companion_notification(hass: HomeAssistant, runtime: RuntimeData) -> NotificationRecord:
    data = {"message": "Door open", "title": "Door", "data": {"tag": "door", "actions": [{"action": "OPEN"}]}}
    await hass.services.async_call("notify", "mobile_app_anna", data, blocking=True)
    [record] = await _records(hass, runtime)
    return record


async def test_a_sent_notification_goes_again_to_a_notify_entity_with_title_and_message(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    sent = _service(hass, "notify", "send_message")
    runtime = await _setup(hass)
    with patch.object(send, "companion_channels", return_value=COMPANION):
        original = await _companion_notification(hass, runtime)

        result = await _send(
            await hass_ws_client(hass), original.id, {"kind": "notify_entity", "entity_id": "notify.kitchen_display"}
        )

    assert result["success"], result
    assert sent == [{"message": "Door open", "title": "Door", "entity_id": "notify.kitchen_display"}]
    _, again = await _records(hass, runtime)
    assert (again.resent_from, again.origin.kind, again.status) == (original.id, OriginKind.USER, Status.SENT)


async def test_the_companion_app_gets_image_buttons_and_tag_again(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    ben = _service(hass, "notify", "mobile_app_ben")
    family = _service(hass, "notify", "family")
    runtime = await _setup(hass)
    with patch.object(send, "companion_channels", return_value=COMPANION):
        original = await _companion_notification(hass, runtime)

        result = await _send(
            await hass_ws_client(hass),
            original.id,
            {"kind": "notify_action", "service": "mobile_app_ben"},
            {"kind": "notify_action", "service": "family"},
        )

    assert result["success"], result
    assert ben == [{"message": "Door open", "title": "Door", "data": {"tag": "door", "actions": [{"action": "OPEN"}]}}]
    assert family == [{"message": "Door open", "title": "Door"}]


async def test_a_speaker_and_a_satellite_get_the_message(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    speak = _service(hass, "tts", "speak")
    announce = _service(hass, "assist_satellite", "announce")
    runtime = await _setup(hass)
    original = await _companion_notification(hass, runtime)

    result = await _send(
        await hass_ws_client(hass),
        original.id,
        {"kind": "speak", "engine": "tts.cloud", "entity_id": "media_player.kitchen"},
        {"kind": "announce", "entity_id": "assist_satellite.office"},
    )

    assert result["success"], result
    speaker = {"entity_id": "tts.cloud", "media_player_entity_id": "media_player.kitchen", "message": "Door open"}
    assert speak == [speaker]
    assert announce == [{"entity_id": "assist_satellite.office", "message": "Door open"}]
    records = await _records(hass, runtime)
    assert [(record.source, record.resent_from) for record in records[1:]] == [
        ("speech", original.id),
        ("speech", original.id),
    ]


async def test_a_spoken_notification_is_sent_as_its_text(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    display = _service(hass, "notify", "send_message")
    runtime = await _setup(hass)
    data = {"message": "TTS", "data": {"tts_text": "Dinner is ready"}}
    await hass.services.async_call("notify", "mobile_app_anna", data, blocking=True)
    [original] = await _records(hass, runtime)

    result = await _send(
        await hass_ws_client(hass), original.id, {"kind": "notify_entity", "entity_id": "notify.kitchen_display"}
    )

    assert result["success"], result
    assert display[0]["message"] == "Dinner is ready"


async def test_a_target_that_fails_fails_its_notification(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    _service(hass, "notify", "broken", error="Push server unreachable")
    runtime = await _setup(hass)
    original = await _companion_notification(hass, runtime)

    _service(hass, "notify", "mobile_app_ben")
    targets = [{"kind": "notify_action", "service": "broken"}, {"kind": "notify_action", "service": "mobile_app_ben"}]

    result = await _send(await hass_ws_client(hass), original.id, *targets)

    assert result["result"] == {"errors": ["Push server unreachable", None]}
    statuses = {record.channel: (record.status, record.error) for record in (await _records(hass, runtime))[1:]}
    assert statuses == {
        "notify.broken": (Status.FAILED, "Push server unreachable"),
        "notify.mobile_app_ben": (Status.SENT, None),
    }


async def test_only_administrators_send(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    display = _service(hass, "notify", "send_message")
    runtime = await _setup(hass)
    original = await _companion_notification(hass, runtime)
    client = await hass_ws_client(hass, hass_read_only_access_token)

    result = await _send(client, original.id, {"kind": "notify_entity", "entity_id": "notify.kitchen_display"})
    await client.send_json_auto_id({"type": f"{DOMAIN}/targets"})
    listed = await client.receive_json()

    assert (result["error"]["code"], listed["error"]["code"]) == ("unauthorized", "unauthorized")
    assert display == []


async def test_the_targets_are_listed_by_kind(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    _service(hass, "notify", "mobile_app_anna")
    _service(hass, "notify", "send_message")
    _service(hass, "notify", "persistent_notification")
    await _setup(hass)
    client = await hass_ws_client(hass)

    with patch.object(send, "companion_channels", return_value=COMPANION):
        await client.send_json_auto_id({"type": f"{DOMAIN}/targets"})
        result = (await client.receive_json())["result"]

    assert result["same_medium"] is False
    assert result["notify_entity"] == [{"entity_id": "notify.kitchen_display", "name": "Kitchen display"}]
    assert result["notify_action"] == [{"service": "mobile_app_anna", "name": "mobile_app_anna", "companion": True}]
    assert result["engines"] == [{"entity_id": "tts.cloud", "name": "Cloud"}]
    assert result["speak"] == [{"entity_id": "media_player.kitchen", "name": "Kitchen speaker"}]
    assert result["announce"] == [{"entity_id": "assist_satellite.office", "name": "Office satellite"}]


async def test_a_phone_is_listed_once_by_its_companion_action_named_like_its_device(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    _service(hass, "notify", "mobile_app_ben")
    await _setup(hass)
    anna = MockConfigEntry(domain="mobile_app", title="alaska", data={"device_id": "phone-1"})
    ben = MockConfigEntry(domain="mobile_app", title="Ben's phone ", data={"device_id": "phone-2"})
    anna.add_to_hass(hass)
    ben.add_to_hass(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=anna.entry_id, identifiers={("mobile_app", "phone-1")}, name="alaska"
    )
    devices.async_update_device(device.id, name_by_user="Anna's phone")
    er.async_get(hass).async_get_or_create(
        "notify", "mobile_app", "phone-1", config_entry=anna, device_id=device.id, suggested_object_id="anna"
    )
    hass.states.async_set("notify.anna", "unknown", {"friendly_name": "Anna's phone"})
    entries = {"mobile_app_anna": anna, "mobile_app_ben": ben}
    client = await hass_ws_client(hass)

    with (
        patch.object(send, "companion_channels", return_value=COMPANION),
        patch.object(send, "mobile_app_entry", side_effect=lambda _, service: entries[service]),
    ):
        await client.send_json_auto_id({"type": f"{DOMAIN}/targets"})
        result = (await client.receive_json())["result"]

    assert result["notify_action"] == [
        {"service": "mobile_app_anna", "name": "Anna's phone", "companion": True},
        {"service": "mobile_app_ben", "name": "Ben's phone", "companion": True},
    ]
    assert result["notify_entity"] == [{"entity_id": "notify.kitchen_display", "name": "Kitchen display"}]


async def test_the_targets_say_whether_the_companion_app_gets_the_data(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    runtime = await _setup(hass)
    client = await hass_ws_client(hass)
    with patch.object(send, "companion_channels", return_value=COMPANION):
        original = await _companion_notification(hass, runtime)
        await client.send_json_auto_id({"type": f"{DOMAIN}/targets", "record_id": original.id})
        result = (await client.receive_json())["result"]

    assert result["same_medium"] is True


async def test_the_bell_and_send_message_are_no_targets(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "mobile_app_anna")
    bell = _service(hass, "notify", "persistent_notification")
    runtime = await _setup(hass)
    original = await _companion_notification(hass, runtime)

    result = await _send(
        await hass_ws_client(hass), original.id, {"kind": "notify_action", "service": "persistent_notification"}
    )

    assert result["error"]["code"] == "invalid_format"
    assert bell == []


async def test_a_command_to_the_companion_app_is_not_sent_again(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _service(hass, "notify", "telegram")
    display = _service(hass, "notify", "send_message")
    runtime = await _setup(hass)
    await hass.services.async_call("notify", "telegram", {"message": "clear_notification"}, blocking=True)
    [original] = await _records(hass, runtime)

    result = await _send(
        await hass_ws_client(hass), original.id, {"kind": "notify_entity", "entity_id": "notify.kitchen_display"}
    )

    assert result["error"]["code"] == "not_supported"
    assert display == []
