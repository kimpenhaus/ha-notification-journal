"""Tests of sending a failed notification again from the panel."""

import logging

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.failures import MOBILE_APP_LOGGER
from custom_components.notification_journal.models import NotificationRecord, OriginKind, Status
from custom_components.notification_journal.store import Query

LOGGED = "logged"
"""A call the Companion app answers by logging a failed push."""


def _phone(hass: HomeAssistant, name: str, *outcomes: str | Exception) -> list[dict]:
    """A notify action whose calls fail one after the other as given, then succeed; returns what it received."""
    received: list[dict] = []

    async def send(call: ServiceCall) -> None:
        received.append(dict(call.data))
        outcome = outcomes[len(received) - 1] if len(received) <= len(outcomes) else None
        if outcome == LOGGED:
            logging.getLogger(MOBILE_APP_LOGGER).error("Error sending notification to %s", name)
        elif isinstance(outcome, Exception):
            raise outcome

    hass.services.async_register("notify", name, send)
    return received


async def _setup(hass: HomeAssistant) -> RuntimeData:
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _records(hass: HomeAssistant, runtime: RuntimeData) -> list[NotificationRecord]:
    await hass.async_block_till_done()
    await runtime.store.async_flush()
    return (await runtime.store.async_query(Query(newest_first=False))).records


async def _resend(client, record_id: str) -> dict:
    await client.send_json_auto_id({"type": f"{DOMAIN}/resend", "record_id": record_id})
    return await client.receive_json()


async def test_a_failed_notification_is_sent_again_by_hand(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    anna = _phone(hass, "phone_anna", LOGGED)
    runtime = await _setup(hass)
    data = {"message": "Door open", "title": "Door", "data": {"tag": "door"}}
    await hass.services.async_call("notify", "phone_anna", data, blocking=True)
    [failed] = await _records(hass, runtime)

    result = await _resend(await hass_ws_client(hass), failed.id)
    first, again = await _records(hass, runtime)

    assert result["success"], result
    assert (first.status, again.status) == (Status.FAILED, Status.SENT)
    assert again.resent_from == failed.id
    assert again.origin.kind == OriginKind.USER
    assert anna == [data, data]


async def test_only_the_failed_members_of_a_group_get_it_again(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    anna = _phone(hass, "phone_anna", LOGGED)
    ben = _phone(hass, "phone_ben")
    member = {"action": "phone_anna", "data": {"data": {"push": {"sound": "alarm"}}}}
    group = {"platform": "group", "name": "family", "services": [member, {"action": "phone_ben"}]}
    assert await async_setup_component(hass, "notify", {"notify": [group]})
    await hass.async_block_till_done()
    runtime = await _setup(hass)
    await hass.services.async_call("notify", "family", {"message": "Dinner"}, blocking=True)
    [partial] = await _records(hass, runtime)

    result = await _resend(await hass_ws_client(hass), partial.id)
    records = await _records(hass, runtime)

    assert result["success"], result
    assert partial.status == Status.PARTIAL
    assert [(r.channel, r.resent_from) for r in records[1:]] == [("notify.phone_anna", partial.id)]
    assert (len(anna), len(ben)) == (2, 1)
    assert anna[1] == {"message": "Dinner", "data": {"push": {"sound": "alarm"}}}


async def test_a_send_again_that_raises_fails_its_notification(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    _phone(hass, "flaky", LOGGED, HomeAssistantError("Push server unreachable"))
    runtime = await _setup(hass)
    await hass.services.async_call("notify", "flaky", {"message": "Door open"}, blocking=True)
    [failed] = await _records(hass, runtime)

    result = await _resend(await hass_ws_client(hass), failed.id)
    _, again = await _records(hass, runtime)

    assert result["error"]["message"] == "Push server unreachable"
    assert (again.status, again.error, again.resent_from) == (Status.FAILED, "Push server unreachable", failed.id)


async def test_a_sent_notification_is_not_sent_again(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    ben = _phone(hass, "phone_ben")
    runtime = await _setup(hass)
    await hass.services.async_call("notify", "phone_ben", {"message": "Fine"}, blocking=True)
    [fine] = await _records(hass, runtime)

    result = await _resend(await hass_ws_client(hass), fine.id)

    assert result["error"]["code"] == "not_supported"
    assert len(ben) == 1


async def test_only_administrators_send_again(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    anna = _phone(hass, "phone_anna", LOGGED)
    runtime = await _setup(hass)
    await hass.services.async_call("notify", "phone_anna", {"message": "Door open"}, blocking=True)
    [failed] = await _records(hass, runtime)

    result = await _resend(await hass_ws_client(hass, hass_read_only_access_token), failed.id)

    assert result["error"]["code"] == "unauthorized"
    assert len(anna) == 1
