"""Tests of the WebSocket commands and who sees what."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.notification_journal import RuntimeData
from custom_components.notification_journal.const import CONF_NON_ADMIN_VISIBILITY, DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.models import (
    Answer,
    Call,
    NotificationRecord,
    Origin,
    OriginKind,
    Recipient,
    RecipientKind,
    Status,
)
from custom_components.notification_journal.origin import OriginNames

GARAGE = Origin(
    kind=OriginKind.AUTOMATION,
    entity_id="automation.garage",
    name="Garage door",
    trace_key="automation.1700000000",
    run_id="abc123",
)


def _person(user: User, name: str) -> Recipient:
    return Recipient(kind=RecipientKind.PERSON, id=f"person.{name.lower()}", name=name, user_id=user.id)


def _record(record_id: str, message: str, recipients: list[Recipient], **kw) -> NotificationRecord:
    return NotificationRecord(
        id=record_id,
        time=dt_util.utcnow() - kw.pop("age", timedelta(0)),
        source="notify",
        channel=kw.pop("channel", "notify.phone"),
        title=None,
        message=message,
        data=kw.pop("data", None),
        recipients=recipients,
        origin=kw.pop("origin", GARAGE),
        context_id=f"ctx-{record_id}",
        **kw,
    )


async def _setup(hass: HomeAssistant, **options: object) -> RuntimeData:
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _fill(runtime: RuntimeData, admin: User, reader: User) -> None:
    runtime.store.add(_record("admin", "for admin", [_person(admin, "Anna")], age=timedelta(minutes=3)))
    runtime.store.add(_record("reader", "for reader", [_person(reader, "Ben")], age=timedelta(minutes=2)))
    runtime.store.add(
        _record(
            "family",
            "for both",
            [],
            group="notify.family",
            channel="notify.family",
            status=Status.FAILED,
            age=timedelta(minutes=1),
            inner_calls=[
                Call("notify.phone_anna", [_person(admin, "Anna")], "c1"),
                Call("notify.phone_ben", [_person(reader, "Ben")], "c2"),
            ],
        )
    )
    await runtime.store.async_flush()


async def _call(client, **msg):
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_admin_lists_everything_with_filters(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User, hass_read_only_user: User
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    client = await hass_ws_client(hass)

    result = (await _call(client, type=f"{DOMAIN}/list"))["result"]
    assert [r["id"] for r in result["records"]] == ["family", "reader", "admin"]
    assert result["total"] == 3

    by_user = await _call(client, type=f"{DOMAIN}/list", user_id=hass_read_only_user.id)
    assert [r["id"] for r in by_user["result"]["records"]] == ["family", "reader"]
    failed = await _call(client, type=f"{DOMAIN}/list", status="failed")
    assert [r["id"] for r in failed["result"]["records"]] == ["family"]
    text = await _call(client, type=f"{DOMAIN}/list", text="admin")
    assert [r["id"] for r in text["result"]["records"]] == ["admin"]
    oldest = await _call(client, type=f"{DOMAIN}/list", newest_first=False, limit=1, offset=1)
    assert [r["id"] for r in oldest["result"]["records"]] == ["reader"]


async def test_record_carries_exact_trace_path(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User, hass_read_only_user: User
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    client = await hass_ws_client(hass)

    record = (await _call(client, type=f"{DOMAIN}/get", record_id="family"))["result"]
    assert record["trace_path"] == "/config/automation/trace/1700000000?run_id=abc123"
    assert [c["channel"] for c in record["inner_calls"]] == ["notify.phone_anna", "notify.phone_ben"]


async def test_user_sees_only_own_notifications(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: User,
    hass_read_only_user: User,
    hass_read_only_access_token: str,
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    client = await hass_ws_client(hass, hass_read_only_access_token)

    listed = await _call(client, type=f"{DOMAIN}/list", user_id=hass_admin_user.id)
    assert [r["id"] for r in listed["result"]["records"]] == ["family", "reader"]
    assert (await _call(client, type=f"{DOMAIN}/get", record_id="reader"))["success"]
    other = await _call(client, type=f"{DOMAIN}/get", record_id="admin")
    assert other["error"]["code"] == "not_found"


async def test_non_admins_see_nothing_when_configured(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    await _setup(hass, **{CONF_NON_ADMIN_VISIBILITY: "none"})
    client = await hass_ws_client(hass, hass_read_only_access_token)

    response = await _call(client, type=f"{DOMAIN}/list")
    assert response["error"]["code"] == "unauthorized"


async def test_facets(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: User,
    hass_read_only_user: User,
    hass_read_only_access_token: str,
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    hass.states.async_set("person.ben", "home", {"user_id": hass_read_only_user.id, "friendly_name": "Ben"})

    admin = (await _call(await hass_ws_client(hass), type=f"{DOMAIN}/facets"))["result"]
    assert admin == {"origins": [{"id": "automation.garage", "name": "Garage door"}]}

    reader = (await _call(await hass_ws_client(hass, hass_read_only_access_token), type=f"{DOMAIN}/facets"))["result"]
    assert reader == {"origins": [{"id": "automation.garage", "name": "Garage door"}]}


async def test_subscribe_sends_new_and_changed_records(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: User,
    hass_read_only_user: User,
    hass_read_only_access_token: str,
) -> None:
    runtime = await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    assert (await _call(client, type=f"{DOMAIN}/subscribe"))["success"]

    runtime.store.add(_record("hidden", "for admin", [_person(hass_admin_user, "Anna")]))
    runtime.store.add(_record("group", "Dinner", [], group="notify.family"))
    await runtime.store.async_flush()
    await hass.async_block_till_done()
    runtime.store.add_inner_call("group", Call("notify.phone_ben", [_person(hass_read_only_user, "Ben")], "c"))
    await runtime.store.async_flush()
    await hass.async_block_till_done()

    event = await client.receive_json()
    assert (event["event"]["change"], event["event"]["record"]["id"]) == ("updated", "group")
    assert len(event["event"]["record"]["inner_calls"]) == 1


async def test_people_show_their_current_name_and_picture(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User, hass_read_only_user: User
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    hass.states.async_set("person.ben", "home", {"friendly_name": "Benjamin", "entity_picture": "/ben.png"})
    client = await hass_ws_client(hass)

    record = (await _call(client, type=f"{DOMAIN}/get", record_id="family"))["result"]
    assert [(r["name"], r["picture"]) for r in record["inner_calls"][1]["recipients"]] == [("Benjamin", "/ben.png")]
    assert record["inner_calls"][0]["recipients"][0]["name"] == "Anna"


async def test_list_grouped_by_origin(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User, hass_read_only_user: User
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    client = await hass_ws_client(hass)

    result = (await _call(client, type=f"{DOMAIN}/list", group_by="origin", newest_first=False))["result"]
    assert [r["id"] for r in result["records"]] == ["admin", "reader", "family"]
    assert result["groups"] == {"automation.garage": 3}
    assert "groups" not in (await _call(client, type=f"{DOMAIN}/list"))["result"]


async def test_admin_deletes_a_notification_for_everyone(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: User,
    hass_read_only_user: User,
    hass_read_only_access_token: str,
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    assert (await _call(reader, type=f"{DOMAIN}/subscribe"))["success"]
    admin = await hass_ws_client(hass)

    denied = await _call(reader, type=f"{DOMAIN}/delete", record_id="family")
    assert denied["error"]["code"] == "unauthorized"
    assert (await _call(admin, type=f"{DOMAIN}/delete", record_id="family"))["success"]
    assert (await _call(admin, type=f"{DOMAIN}/delete", record_id="family"))["error"]["code"] == "not_found"

    event = await reader.receive_json()
    assert event["event"] == {"change": "removed", "record_id": "family"}
    remaining = (await _call(admin, type=f"{DOMAIN}/list", text="both"))["result"]
    assert remaining["total"] == 0
    assert [r["id"] for r in (await _call(reader, type=f"{DOMAIN}/list"))["result"]["records"]] == ["reader"]


async def test_archive_changes_only_the_callers_view(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: User,
    hass_read_only_user: User,
    hass_read_only_access_token: str,
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    admin = await hass_ws_client(hass)

    archived = await _call(reader, type=f"{DOMAIN}/archive", record_ids=["family", "admin"])
    assert archived["result"] == {"changed": 1}
    assert [r["id"] for r in (await _call(reader, type=f"{DOMAIN}/list"))["result"]["records"]] == ["reader"]
    in_archive = (await _call(reader, type=f"{DOMAIN}/list", archived=True))["result"]
    assert [r["id"] for r in in_archive["records"]] == ["family"]
    assert (await _call(admin, type=f"{DOMAIN}/list"))["result"]["total"] == 3

    restored = await _call(reader, type=f"{DOMAIN}/archive", record_ids=["family"], archived=False)
    assert restored["result"] == {"changed": 1}
    assert (await _call(reader, type=f"{DOMAIN}/list"))["result"]["total"] == 2


async def test_subscription_survives_a_reload_of_the_entry(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User
) -> None:
    runtime = await _setup(hass)
    client = await hass_ws_client(hass)
    assert (await _call(client, type=f"{DOMAIN}/subscribe"))["success"]
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data is not runtime
    entry.runtime_data.store.add(_record("after", "After reload", [_person(hass_admin_user, "Anna")]))
    await entry.runtime_data.store.async_flush()
    await hass.async_block_till_done()

    event = await client.receive_json()
    assert (event["event"]["change"], event["event"]["record"]["id"]) == ("added", "after")


async def test_only_the_first_page_carries_the_counts(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User, hass_read_only_user: User
) -> None:
    runtime = await _setup(hass)
    await _fill(runtime, hass_admin_user, hass_read_only_user)
    client = await hass_ws_client(hass)

    first = (await _call(client, type=f"{DOMAIN}/list", limit=1, group_by="origin"))["result"]
    second = (await _call(client, type=f"{DOMAIN}/list", limit=1, offset=1, group_by="origin"))["result"]

    assert first["total"] > 1 and "groups" in first
    assert len(second["records"]) == 1
    assert "total" not in second and "groups" not in second


async def test_user_sees_only_own_answers(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: User,
    hass_read_only_user: User,
    hass_read_only_access_token: str,
) -> None:
    runtime = await _setup(hass)
    both = [_person(hass_admin_user, "Anna"), _person(hass_read_only_user, "Ben")]
    runtime.store.add(_record("window", "Window open", both, data={"data": {"actions": [{"action": "DONE"}]}}))
    for user in (hass_admin_user, hass_read_only_user):
        await runtime.store.async_add_answer("notify", Answer(action="DONE", time=dt_util.utcnow(), user_id=user.id))

    async def answered(client) -> list[str]:
        (record,) = (await _call(client, type=f"{DOMAIN}/list"))["result"]["records"]
        return [answer["user_id"] for answer in record["answers"]]

    assert await answered(await hass_ws_client(hass)) == [hass_admin_user.id, hass_read_only_user.id]
    assert await answered(await hass_ws_client(hass, hass_read_only_access_token)) == [hass_read_only_user.id]


def _automation(entity_id: str, name: str) -> Origin:
    return Origin(kind=OriginKind.AUTOMATION, entity_id=entity_id, name=name)


async def test_origins_show_their_current_name(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User
) -> None:
    runtime = await _setup(hass)
    anna = [_person(hass_admin_user, "Anna")]
    registered = er.async_get(hass).async_get_or_create("script", "script", "away", suggested_object_id="away")
    er.async_get(hass).async_update_entity(registered.entity_id, name="Leaving home")
    runtime.store.add(_record("renamed", "a", anna, age=timedelta(minutes=4)))
    runtime.store.add(
        _record("deleted", "b", anna, origin=_automation("automation.old", "Old lamp"), age=timedelta(minutes=3))
    )
    runtime.store.add(
        _record("registry", "c", anna, origin=_automation(registered.entity_id, "Away"), age=timedelta(minutes=2))
    )
    runtime.store.add(
        _record(
            "integration", "d", anna, origin=Origin(kind=OriginKind.INTEGRATION, name="Journal", integration=DOMAIN)
        )
    )
    await runtime.store.async_flush()
    hass.states.async_set("automation.garage", "on", {"friendly_name": "Garage gate"})
    client = await hass_ws_client(hass)

    records = (await _call(client, type=f"{DOMAIN}/list", newest_first=False))["result"]["records"]
    assert [r["origin"]["name"] for r in records] == ["Garage gate", "Old lamp", "Leaving home", "Notification Journal"]
    assert (await _call(client, type=f"{DOMAIN}/get", record_id="renamed"))["result"]["origin"]["name"] == "Garage gate"


async def test_facets_name_origins_by_current_or_newest_name(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User
) -> None:
    runtime = await _setup(hass)
    anna = [_person(hass_admin_user, "Anna")]
    runtime.store.add(
        _record("first", "a", anna, origin=_automation("automation.old", "First name"), age=timedelta(minutes=3))
    )
    runtime.store.add(
        _record("second", "b", anna, origin=_automation("automation.old", "Second name"), age=timedelta(minutes=2))
    )
    runtime.store.add(_record("garage", "c", anna, age=timedelta(minutes=1)))
    await runtime.store.async_flush()
    hass.states.async_set("automation.garage", "on", {"friendly_name": "Garage gate"})

    facets = (await _call(await hass_ws_client(hass), type=f"{DOMAIN}/facets"))["result"]
    assert facets == {
        "origins": [{"id": "automation.garage", "name": "Garage gate"}, {"id": "automation.old", "name": "Second name"}]
    }


async def test_each_origin_is_looked_up_once_per_request(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_admin_user: User
) -> None:
    runtime = await _setup(hass)
    for number in range(20):
        runtime.store.add(_record(f"n{number}", "Garage open", [_person(hass_admin_user, "Anna")]))
    await runtime.store.async_flush()
    client = await hass_ws_client(hass)

    with patch.object(OriginNames, "_lookup", autospec=True, return_value="Garage gate") as lookup:
        records = (await _call(client, type=f"{DOMAIN}/list"))["result"]["records"]
    assert len(records) == 20
    assert {r["origin"]["name"] for r in records} == {"Garage gate"}
    assert lookup.call_count == 1
