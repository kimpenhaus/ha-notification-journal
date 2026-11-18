"""Tests of marking notifications failed from what the Companion app logs while sending them."""

import logging
from contextvars import Context
from unittest.mock import patch

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notification_journal import failures

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.failures import MOBILE_APP_LOGGER
from custom_components.notification_journal.models import NotificationRecord, Status
from custom_components.notification_journal.store import Query

FAILED = "Error sending notification to {}"
RATE_LIMIT = "Rate limit exceeded sending notification to {}"


def _phone(hass: HomeAssistant, name: str, *errors: str, level: int = logging.ERROR) -> None:
    """A notify action that logs like the Companion app's when its push fails, and succeeds all the same."""

    async def send(call: ServiceCall) -> None:
        for error in errors:
            logging.getLogger(MOBILE_APP_LOGGER).log(level, error.format(name))

    hass.services.async_register("notify", name, send)


async def _setup(hass: HomeAssistant) -> RuntimeData:
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _family(hass: HomeAssistant, *, nested: bool = False) -> None:
    def group(name: str, *members: str) -> dict:
        return {"platform": "group", "name": name, "services": [{"action": member} for member in members]}

    groups = [group("family", "phone_anna", "kids"), group("kids", "phone_ben")] if nested else []
    assert await async_setup_component(
        hass, "notify", {"notify": groups or [group("family", "phone_anna", "phone_ben")]}
    )
    await hass.async_block_till_done()


async def _send(hass: HomeAssistant, runtime: RuntimeData, service: str) -> NotificationRecord:
    await hass.services.async_call("notify", service, {"message": "Dinner"}, blocking=True)
    await hass.async_block_till_done()
    await runtime.store.async_flush()
    records = (await runtime.store.async_query(Query())).records
    assert len(records) == 1, records
    return records[0]


async def test_a_logged_push_error_fails_the_notification(hass: HomeAssistant) -> None:
    _phone(hass, "phone_anna", FAILED)
    runtime = await _setup(hass)

    record = await _send(hass, runtime, "phone_anna")

    assert (record.status, record.error) == (Status.FAILED, "Error sending notification to phone_anna")
    assert record.status_time is not None


async def test_a_rate_limit_fails_the_notification(hass: HomeAssistant) -> None:
    _phone(hass, "phone_anna", RATE_LIMIT, level=logging.WARNING)
    runtime = await _setup(hass)

    record = await _send(hass, runtime, "phone_anna")

    assert record.status == Status.FAILED


async def test_one_failed_member_fails_the_group_in_part(hass: HomeAssistant) -> None:
    _phone(hass, "phone_anna", FAILED)
    _phone(hass, "phone_ben")
    await _family(hass)
    runtime = await _setup(hass)

    record = await _send(hass, runtime, "family")

    assert (record.status, record.error) == (Status.PARTIAL, None)
    errors = {call.channel: call.error for call in record.inner_calls}
    assert errors == {"notify.phone_anna": "Error sending notification to phone_anna", "notify.phone_ben": None}


async def test_every_failed_member_fails_the_group(hass: HomeAssistant) -> None:
    _phone(hass, "phone_anna", FAILED)
    _phone(hass, "phone_ben", FAILED)
    await _family(hass)
    runtime = await _setup(hass)

    record = await _send(hass, runtime, "family")

    assert record.status == Status.FAILED
    assert all(call.error for call in record.inner_calls)


async def test_other_log_lines_leave_notifications_alone(hass: HomeAssistant) -> None:
    async def noisy(call: ServiceCall) -> None:
        logging.getLogger("homeassistant.components.other").error("Unrelated")
        logging.getLogger(MOBILE_APP_LOGGER).info("Rate limits: 1 sent")

    hass.services.async_register("notify", "phone_anna", noisy)
    runtime = await _setup(hass)

    record = await _send(hass, runtime, "phone_anna")
    Context().run(logging.getLogger(MOBILE_APP_LOGGER).error, "Outside of any call")
    await hass.async_block_till_done()
    await runtime.store.async_flush()

    assert (await runtime.store.async_get(record.id)).status == Status.SENT


async def test_a_second_error_of_the_same_call_keeps_the_first(hass: HomeAssistant) -> None:
    _phone(hass, "phone_anna", FAILED, "Something else about {}")
    runtime = await _setup(hass)

    record = await _send(hass, runtime, "phone_anna")

    assert record.error == "Error sending notification to phone_anna"


async def test_a_nested_group_fails_once_every_phone_failed(hass: HomeAssistant) -> None:
    _phone(hass, "phone_anna", FAILED)
    _phone(hass, "phone_ben", FAILED)
    await _family(hass, nested=True)
    runtime = await _setup(hass)

    record = await _send(hass, runtime, "family")

    assert record.status == Status.FAILED
    assert [call.channel for call in record.inner_calls if call.group] == ["notify.kids"]


async def test_an_error_naming_another_device_is_not_the_calls(hass: HomeAssistant) -> None:
    anna = MockConfigEntry(domain="mobile_app", title="Anna's phone")
    ben = MockConfigEntry(domain="mobile_app", title="Ben's phone")
    for entry in (anna, ben):
        entry.add_to_hass(hass)

    with patch.object(failures, "mobile_app_entry", return_value=anna):
        assert failures._names_target(
            hass, "notify.mobile_app_annas_phone", "Error sending notification to Anna's phone"
        )
        assert not failures._names_target(
            hass, "notify.mobile_app_annas_phone", "Error sending notification to Ben's phone"
        )
        assert failures._names_target(hass, "notify.mobile_app_annas_phone", "error_sending_notification")
    with patch.object(failures, "mobile_app_entry", return_value=None):
        assert failures._names_target(hass, "notify.mobile_app", "Error sending notification to Ben's phone")
