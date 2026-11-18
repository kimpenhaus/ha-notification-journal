"""Tests of failing a notification whose action raised inside an automation or script."""

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.models import NotificationRecord, Status
from custom_components.notification_journal.store import Query


@pytest.fixture
def phones(hass: HomeAssistant) -> None:
    """notify.broken raises like an integration that cannot send, notify.phone sends."""

    async def broken(call: ServiceCall) -> None:
        raise HomeAssistantError("Chat not found")

    hass.services.async_register("notify", "broken", broken)
    hass.services.async_register("notify", "phone", lambda call: None)


async def _setup(hass: HomeAssistant) -> RuntimeData:
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


async def _records(hass: HomeAssistant, runtime: RuntimeData) -> dict[str, NotificationRecord]:
    await runtime.store.async_flush()
    await hass.async_block_till_done(wait_background_tasks=True)
    await runtime.store.async_flush()
    return {record.message: record for record in (await runtime.store.async_query(Query())).records}


def _notify(service: str, message: str, **step) -> dict:
    return {"action": f"notify.{service}", "data": {"message": message}, **step}


async def test_a_raising_step_of_an_automation_fails_its_notification(hass: HomeAssistant, phones: None) -> None:
    runtime = await _setup(hass)
    automation = {
        "id": "door",
        "alias": "Door",
        "triggers": {"trigger": "event", "event_type": "go"},
        "actions": [_notify("phone", "Sent"), _notify("broken", "Lost")],
    }
    assert await async_setup_component(hass, "automation", {"automation": [automation]})

    hass.bus.async_fire("go")
    records = await _records(hass, runtime)

    assert (records["Lost"].status, records["Lost"].error) == (Status.FAILED, "Chat not found")
    assert records["Sent"].status == Status.SENT


async def test_a_step_that_continues_on_error_fails_its_notification(hass: HomeAssistant, phones: None) -> None:
    runtime = await _setup(hass)
    script = {"sequence": [_notify("broken", "Lost", continue_on_error=True), _notify("phone", "After")]}
    assert await async_setup_component(hass, "script", {"script": {"evening": script}})

    await hass.services.async_call("script", "evening", blocking=True)
    records = await _records(hass, runtime)

    assert records["Lost"].status == Status.FAILED
    assert records["After"].status == Status.SENT


async def test_only_the_notification_with_the_failed_text_fails(hass: HomeAssistant, phones: None) -> None:
    runtime = await _setup(hass)
    script = {
        "sequence": [
            _notify("broken", "First", continue_on_error=True),
            _notify("broken", "Second", continue_on_error=True),
        ]
    }
    hass.services.async_remove("notify", "broken")
    calls: list[str] = []

    async def broken_once(call: ServiceCall) -> None:
        calls.append(call.data["message"])
        if len(calls) == 2:
            raise HomeAssistantError("Chat not found")

    hass.services.async_register("notify", "broken", broken_once)
    assert await async_setup_component(hass, "script", {"script": {"twice": script}})

    await hass.services.async_call("script", "twice", blocking=True)
    records = await _records(hass, runtime)

    assert (records["First"].status, records["Second"].status) == (Status.SENT, Status.FAILED)
