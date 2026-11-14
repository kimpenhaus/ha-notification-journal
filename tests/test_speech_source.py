"""Tests of recording speech announcements: tts.speak and assist_satellite.announce."""

from homeassistant.auth.models import User
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import (
    CONF_EXCLUDED_CHANNELS,
    CONF_RECORD_SPEECH,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.notification_journal.models import NotificationRecord, OriginKind, RecipientKind
from custom_components.notification_journal.store import Query


async def _setup(hass: HomeAssistant, **options: object) -> RuntimeData:
    for domain, service in (("tts", "speak"), ("assist_satellite", "announce")):
        hass.services.async_register(domain, service, lambda call: None)
    hass.states.async_set("media_player.kitchen", "idle", {"friendly_name": "Kitchen speaker"})
    hass.states.async_set("media_player.hall", "idle", {"friendly_name": "Hall speaker"})
    hass.states.async_set("assist_satellite.office", "idle", {"friendly_name": "Office satellite"})
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _records(runtime: RuntimeData) -> list[NotificationRecord]:
    await runtime.store.async_flush()
    return (await runtime.store.async_query(Query(limit=1000))).records


async def _speak(hass: HomeAssistant, players: str) -> None:
    await hass.services.async_call(
        "tts",
        "speak",
        {"entity_id": "tts.cloud", "media_player_entity_id": players, "message": "Dinner is ready"},
        blocking=True,
    )


async def test_tts_speak_records_message_and_speakers(hass: HomeAssistant, hass_admin_user: User) -> None:
    runtime = await _setup(hass)

    await hass.services.async_call(
        "tts",
        "speak",
        {
            "entity_id": "tts.cloud",
            "media_player_entity_id": ["media_player.kitchen", "media_player.hall"],
            "message": "Dinner is ready",
            "language": "en-US",
        },
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )

    (record,) = await _records(runtime)
    assert (record.source, record.channel, record.title, record.message) == (
        "speech",
        "tts.speak",
        None,
        "Dinner is ready",
    )
    assert [(r.kind, r.id, r.name) for r in record.recipients] == [
        (RecipientKind.SPEAKER, "media_player.hall", "Hall speaker"),
        (RecipientKind.SPEAKER, "media_player.kitchen", "Kitchen speaker"),
    ]
    assert record.data == {"language": "en-US"}
    assert record.origin.kind is OriginKind.USER
    assert record.visible_to("any-user")


async def test_media_player_group_is_expanded(hass: HomeAssistant) -> None:
    runtime = await _setup(hass)
    members = {"entity_id": ["media_player.kitchen", "media_player.hall"]}
    hass.states.async_set("media_player.downstairs", "idle", members)

    await _speak(hass, "media_player.downstairs")

    (record,) = await _records(runtime)
    assert sorted(r.id for r in record.recipients) == ["media_player.hall", "media_player.kitchen"]


async def test_announce_on_an_area_resolves_the_satellites(hass: HomeAssistant) -> None:
    runtime = await _setup(hass)
    office = ar.async_get(hass).async_create("Office")
    registry = er.async_get(hass)
    satellite = registry.async_get_or_create("assist_satellite", "esphome", "den", suggested_object_id="den")
    registry.async_update_entity(satellite.entity_id, area_id=office.id)
    hass.states.async_set(satellite.entity_id, "idle")

    await hass.services.async_call(
        "assist_satellite", "announce", {"area_id": office.id, "message": "Meeting in five minutes"}, blocking=True
    )

    (record,) = await _records(runtime)
    assert record.channel == "assist_satellite.announce"
    assert [r.id for r in record.recipients] == [satellite.entity_id]


async def test_announcement_without_text_is_no_notification(hass: HomeAssistant) -> None:
    runtime = await _setup(hass)

    await hass.services.async_call(
        "assist_satellite",
        "announce",
        {"entity_id": "assist_satellite.office", "media_id": "media-source://media_source/local/chime.mp3"},
        blocking=True,
    )

    assert await _records(runtime) == []


async def test_excluded_speaker_is_not_recorded(hass: HomeAssistant) -> None:
    runtime = await _setup(hass, **{CONF_EXCLUDED_CHANNELS: ["media_player.kitchen"]})

    await _speak(hass, "media_player.kitchen")

    assert await _records(runtime) == []


async def test_option_turns_speech_off(hass: HomeAssistant) -> None:
    runtime = await _setup(hass, **{CONF_RECORD_SPEECH: False})

    await _speak(hass, "media_player.kitchen")

    assert await _records(runtime) == []


async def test_data_that_json_cannot_hold_becomes_text(hass: HomeAssistant) -> None:
    runtime = await _setup(hass)

    await hass.services.async_call(
        "tts",
        "speak",
        {"entity_id": "tts.cloud", "media_player_entity_id": "media_player.kitchen", "message": "Hi", "options": {1}},
        blocking=True,
    )

    (record,) = await _records(runtime)
    assert record.data == {"options": "{1}"}
