"""Tests of recording the messages of the telegram_bot actions."""

from homeassistant.auth.models import User
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import (
    CONF_EXCLUDED_CHANNELS,
    CONF_RECORD_TELEGRAM,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.notification_journal.models import NotificationRecord, OriginKind, RecipientKind
from custom_components.notification_journal.store import Query

SERVICES = ("send_message", "send_photo", "send_poll")


def _bot(hass: HomeAssistant) -> MockConfigEntry:
    """A bot with two allowed chats; the first has its notify entity."""
    bot = MockConfigEntry(
        domain="telegram_bot",
        subentries_data=[
            ConfigSubentryData(
                data={"chat_id": 111}, subentry_type="allowed_chat_ids", title="Family", unique_id="111"
            ),
            ConfigSubentryData(data={"chat_id": 222}, subentry_type="allowed_chat_ids", title="Alex", unique_id="222"),
        ],
    )
    bot.add_to_hass(hass)
    family = next(s for s in bot.subentries.values() if s.title == "Family")
    er.async_get(hass).async_get_or_create(
        "notify",
        "telegram_bot",
        "bot_111",
        config_entry=bot,
        config_subentry_id=family.subentry_id,
        suggested_object_id="family",
    )
    hass.states.async_set("notify.family", "unknown", {"friendly_name": "Family"})
    return bot


async def _setup(hass: HomeAssistant, **options: object) -> RuntimeData:
    for service in SERVICES:
        hass.services.async_register("telegram_bot", service, lambda call: None)
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _records(runtime: RuntimeData) -> list[NotificationRecord]:
    await runtime.store.async_flush()
    return (await runtime.store.async_query(Query(limit=1000))).records


async def _send(hass: HomeAssistant, service: str, data: dict, user_id: str | None = None) -> None:
    await hass.services.async_call("telegram_bot", service, data, blocking=True, context=Context(user_id=user_id))


async def test_message_to_a_notify_entity(hass: HomeAssistant, hass_admin_user: User) -> None:
    _bot(hass)
    runtime = await _setup(hass)

    await _send(
        hass,
        "send_message",
        {"entity_id": "notify.family", "title": "Garage", "message": "Door open", "parse_mode": "html"},
        hass_admin_user.id,
    )

    (record,) = await _records(runtime)
    assert (record.source, record.channel, record.title, record.message) == (
        "telegram_bot",
        "telegram_bot.send_message",
        "Garage",
        "Door open",
    )
    assert [(r.kind, r.id, r.name) for r in record.recipients] == [(RecipientKind.CHAT, "notify.family", "Family")]
    assert record.data == {"parse_mode": "html"}
    assert record.origin.kind is OriginKind.USER


async def test_chat_ids_are_named_after_the_allowed_chats(hass: HomeAssistant) -> None:
    bot = _bot(hass)
    runtime = await _setup(hass)

    await _send(hass, "send_message", {"config_entry_id": bot.entry_id, "chat_id": ["111", 222], "message": "Hello"})

    (record,) = await _records(runtime)
    assert sorted((r.id, r.name) for r in record.recipients) == [
        ("notify.family", "Family"),
        ("telegram_bot.222", "Alex"),
    ]


async def test_without_target_the_first_chat_receives_it(hass: HomeAssistant) -> None:
    _bot(hass)
    runtime = await _setup(hass)

    await _send(hass, "send_message", {"message": "Default"})

    (record,) = await _records(runtime)
    assert [r.name for r in record.recipients] == ["Family"]


async def test_photo_needs_a_caption(hass: HomeAssistant) -> None:
    _bot(hass)
    runtime = await _setup(hass)

    await _send(hass, "send_photo", {"entity_id": "notify.family", "url": "http://camera/snapshot.jpg"})
    await _send(
        hass, "send_photo", {"entity_id": "notify.family", "url": "http://camera/snapshot.jpg", "caption": "Doorbell"}
    )

    (record,) = await _records(runtime)
    assert (record.channel, record.message) == ("telegram_bot.send_photo", "Doorbell")
    assert record.data == {"url": "http://camera/snapshot.jpg"}


async def test_poll_records_the_question(hass: HomeAssistant) -> None:
    _bot(hass)
    runtime = await _setup(hass)

    await _send(hass, "send_poll", {"entity_id": "notify.family", "question": "Pizza?", "options": ["Yes", "No"]})

    (record,) = await _records(runtime)
    assert record.message == "Pizza?"
    assert record.data == {"options": ["Yes", "No"]}


async def test_excluded_chat_is_not_recorded(hass: HomeAssistant) -> None:
    _bot(hass)
    runtime = await _setup(hass, **{CONF_EXCLUDED_CHANNELS: ["notify.family"]})

    await _send(hass, "send_message", {"entity_id": "notify.family", "message": "Hidden"})

    assert await _records(runtime) == []


async def test_option_turns_telegram_off(hass: HomeAssistant) -> None:
    _bot(hass)
    runtime = await _setup(hass, **{CONF_RECORD_TELEGRAM: False})

    await _send(hass, "send_message", {"entity_id": "notify.family", "message": "Off"})

    assert await _records(runtime) == []
