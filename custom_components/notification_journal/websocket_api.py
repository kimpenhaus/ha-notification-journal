"""WebSocket commands the panel uses: list, get, facets, statistics and live updates."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.group.notify import add_defaults
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import CONF_NON_ADMIN_VISIBILITY, DEFAULT_OPTIONS, DOMAIN, SIGNAL_CHANGED, Visibility
from .models import NotificationRecord, RecipientKind, Status
from .origin import OriginNames, origin_key
from .recipients import NOTIFY_DOMAIN, SEND_MESSAGE, member_defaults
from .sources import ATTR_MESSAGE, ATTR_TITLE
from .sources.notify import resend
from .statistics import FAILED, PERIOD_KINDS, period, summarize
from .store import NotificationStore, Query

MAX_LIMIT = 200
ERR_NOT_LOADED = "not_loaded"
TRACE_DOMAINS = ("automation", "script")
GROUP_BY_ORIGIN = "origin"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the commands once."""
    websocket_api.async_register_command(hass, ws_list)
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_facets)
    websocket_api.async_register_command(hass, ws_statistics)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_delete)
    websocket_api.async_register_command(hass, ws_archive)
    websocket_api.async_register_command(hass, ws_resend)


def _store_and_scope(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[NotificationStore, str | None] | None:
    """Return the store and the user the caller is limited to, or send an error and return None."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "Notification Journal is not set up")
        return None
    entry = entries[0]
    user = connection.user
    if user.is_admin:
        return entry.runtime_data.store, msg.get("user_id")
    visibility = {**DEFAULT_OPTIONS, **entry.options}[CONF_NON_ADMIN_VISIBILITY]
    if visibility == Visibility.NONE:
        connection.send_error(msg["id"], websocket_api.ERR_UNAUTHORIZED, "Only administrators see the history")
        return None
    return entry.runtime_data.store, user.id


def _people(hass: HomeAssistant) -> dict[str, State]:
    return {state.entity_id: state for state in hass.states.async_all("person")}


def serialize(
    hass: HomeAssistant,
    record: NotificationRecord,
    people: dict[str, State] | None = None,
    names: OriginNames | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Return a record as the panel uses it: people and origins with their current names, and the path to its trace.

    A caller limited to one user sees only that user's answers to the buttons. Pass `people` and `names` when
    serializing several records, so each person and origin is looked up once.
    """
    result = record.as_dict()
    if user_id is not None:
        result["answers"] = [answer for answer in result["answers"] if answer["user_id"] == user_id]
    if people is None:
        people = _people(hass)
    for recipient in [*result["recipients"], *(r for call in result["inner_calls"] for r in call["recipients"])]:
        if recipient["kind"] == RecipientKind.PERSON and (state := people.get(recipient["id"])):
            recipient["name"] = state.name
            recipient["picture"] = state.attributes.get("entity_picture")
    if names is None:
        names = OriginNames(hass)
    origin = record.origin
    result["origin"]["name"] = names.name(origin_key(origin), origin.name)
    if record.status_by is not None:
        result["status_by"]["name"] = names.name(origin_key(record.status_by), record.status_by.name)
    result["trace_path"] = None
    if origin.trace_key and origin.run_id:
        domain, _, item_id = origin.trace_key.partition(".")
        if domain in TRACE_DOMAINS:
            result["trace_path"] = f"/config/{domain}/trace/{item_id}?run_id={origin.run_id}"
    return result


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/list",
        vol.Optional("text"): str,
        vol.Optional("channel"): str,
        vol.Optional("origin"): str,
        vol.Optional("status"): vol.In([status.value for status in Status]),
        vol.Optional("tag"): str,
        vol.Optional("since"): cv.datetime,
        vol.Optional("until"): cv.datetime,
        vol.Optional("user_id"): str,
        vol.Optional("newest_first", default=True): bool,
        vol.Optional("group_by"): vol.In([GROUP_BY_ORIGIN]),
        vol.Optional("archived", default=False): bool,
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=MAX_LIMIT)),
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
        vol.Optional("days", default=False): bool,
        vol.Optional("time_zone"): str,
    }
)
@websocket_api.async_response
async def ws_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """List notifications, newest first unless asked otherwise."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, user_id = scope
    zone = await _time_zone(msg.get("time_zone")) if msg["days"] else None
    page = await store.async_query(
        Query(
            user_id=user_id,
            text=msg.get("text"),
            channel=msg.get("channel"),
            origin=msg.get("origin"),
            status=Status(msg["status"]) if "status" in msg else None,
            tag=msg.get("tag"),
            since=msg.get("since"),
            until=msg.get("until"),
            newest_first=msg["newest_first"],
            group_by_origin=msg.get("group_by") == GROUP_BY_ORIGIN,
            archive_user_id=connection.user.id,
            archived=msg["archived"],
            limit=msg["limit"],
            offset=msg["offset"],
            with_counts=msg["offset"] == 0,
            days_in=zone,
        )
    )
    people = _people(hass)
    names = OriginNames(hass)
    result: dict[str, Any] = {"records": [serialize(hass, r, people, names, user_id=user_id) for r in page.records]}
    if page.total is not None:
        result["total"] = page.total
    if page.groups is not None:
        result["groups"] = page.groups
    if page.days is not None and zone is not None:
        result["days"] = [_day(day, count, zone) for day, count in page.days]
    connection.send_result(msg["id"], result)


def _day(day: date, count: int, zone: tzinfo) -> dict[str, Any]:
    """A day of the list with its notifications and its bounds, local midnight to local midnight."""
    return {
        "day": day.isoformat(),
        "since": datetime.combine(day, time.min, zone).isoformat(),
        "until": datetime.combine(day + timedelta(days=1), time.min, zone).isoformat(),
        "count": count,
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get", vol.Required("record_id"): str})
@websocket_api.async_response
async def ws_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return one notification with everything recorded about it."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, user_id = scope
    record = await store.async_get(msg["record_id"])
    if record is None or (user_id is not None and not record.visible_to(user_id)):
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Notification not found")
        return
    connection.send_result(msg["id"], serialize(hass, record, user_id=user_id))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/facets", vol.Optional("user_id"): str})
@websocket_api.async_response
async def ws_facets(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return what the filters can offer: the origins that sent notifications, by current name.

    Origins without a name of their own (a user by hand, Home Assistant, unknown) come without one;
    the panel names them.
    """
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, user_id = scope
    facets = await store.async_facets(user_id)
    names = OriginNames(hass)
    origins = [{"id": o["id"], "name": names.name(o["id"], o["name"])} for o in facets["origins"]]
    origins.sort(key=lambda o: (o["name"] or o["id"] or "").casefold())
    connection.send_result(msg["id"], {"origins": origins})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/statistics",
        vol.Required("period"): vol.In(PERIOD_KINDS),
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0, max=1000)),
        vol.Optional("first_weekday", default=0): vol.All(int, vol.Range(min=0, max=6)),
        vol.Optional("time_zone"): str,
        vol.Optional("user_id"): str,
    }
)
@websocket_api.async_response
async def ws_statistics(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return the statistics of a day, week, month or year, offset periods back, in the caller's time zone.

    A week starts on first_weekday (Monday 0 to Sunday 6). Origins carry their current name, else the one stored with
    their newest notification; origins without a name of their own come without one.
    """
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, user_id = scope
    zone = await _time_zone(msg.get("time_zone"))
    current = period(msg["period"], msg["offset"], msg["first_weekday"], dt_util.now(zone))
    counted = await store.async_statistics(
        user_id,
        (current.start.timestamp(), current.end.timestamp()),
        (current.compare_start.timestamp(), current.compare_end.timestamp()),
    )
    result = await hass.async_add_executor_job(summarize, counted.rows, counted.previous, current, zone)
    names = OriginNames(hass)
    for origin in result["origins"]:
        origin["name"] = names.name(origin["key"], counted.names.get(origin["key"]))
    connection.send_result(
        msg["id"],
        {
            "period": current.kind,
            "start": current.start.isoformat(),
            "end": current.end.isoformat(),
            "has_older": counted.oldest is not None and counted.oldest < current.start.timestamp(),
            "comparable": counted.counting_since is not None
            and counted.counting_since <= current.compare_start.timestamp(),
            "kept_since": None
            if counted.kept_since is None
            else dt_util.utc_from_timestamp(counted.kept_since).isoformat(),
            **result,
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@websocket_api.async_response
async def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Send every new or changed notification the caller may see while subscribed, across reloads of the entry."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    _, user_id = scope

    @callback
    def _forward(change: str, record_id: str, record: NotificationRecord | None) -> None:
        if user_id is not None and _non_admins_see_nothing(hass):
            return
        if record is None:
            connection.send_message(websocket_api.event_message(msg["id"], {"change": change, "record_id": record_id}))
        elif user_id is None or record.visible_to(user_id):
            connection.send_message(
                websocket_api.event_message(
                    msg["id"], {"change": change, "record": serialize(hass, record, user_id=user_id)}
                )
            )

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_CHANGED, _forward)
    connection.send_result(msg["id"])


async def _time_zone(name: str | None) -> tzinfo:
    """Return the time zone the caller sees, loaded without blocking; Home Assistant's own if none or unknown."""
    if name:
        try:
            if (zone := await dt_util.async_get_time_zone(name)) is not None:
                return zone
        except ValueError:
            pass
    return dt_util.get_default_time_zone()


def _non_admins_see_nothing(hass: HomeAssistant) -> bool:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return bool(entries) and {**DEFAULT_OPTIONS, **entries[0].options}[CONF_NON_ADMIN_VISIBILITY] == Visibility.NONE


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/delete", vol.Required("record_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete one notification for every recipient; administrators only."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, _ = scope
    if not await store.async_delete(msg["record_id"]):
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Notification not found")
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/resend", vol.Required("record_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_resend(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Send a failed notify notification again to what failed; administrators only."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, _ = scope
    record = await store.async_get(msg["record_id"])
    if record is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Notification not found")
        return
    if record.source != NOTIFY_DOMAIN or record.status not in FAILED:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_SUPPORTED, "Only a failed notify notification")
        return
    errors = []
    for service, data in _calls_again(hass, record):
        context = connection.context(msg)
        with resend(context.id, record.id) as sent:
            try:
                await hass.services.async_call(NOTIFY_DOMAIN, service, data, blocking=True, context=context)
            except (HomeAssistantError, vol.Invalid) as err:
                errors.append(str(err))
                if sent.sent is not None:
                    store.mark_failed(sent.sent, None, str(err))
    if errors:
        connection.send_error(msg["id"], websocket_api.ERR_HOME_ASSISTANT_ERROR, "; ".join(errors))
        return
    connection.send_result(msg["id"])


def _calls_again(hass: HomeAssistant, record: NotificationRecord) -> list[tuple[str, dict[str, Any]]]:
    """The notify calls that send a failed notification again: to each failed member of a group once, else as it
    was; notify entities through send_message, which takes text only."""
    failed = list(dict.fromkeys(call.channel for call in record.inner_calls if call.error and not call.group))
    text = {ATTR_MESSAGE: record.message, **({ATTR_TITLE: record.title} if record.title else {})}
    calls = []
    for channel in failed or [record.channel]:
        targets = channel.split(", ")
        if all(hass.states.get(target) is not None for target in targets):
            calls.append((SEND_MESSAGE, {**text, ATTR_ENTITY_ID: targets}))
            continue
        service = channel.removeprefix(f"{NOTIFY_DOMAIN}.")
        data = {**text, **deepcopy(record.data or {})}
        if record.group:
            for defaults in member_defaults(hass, record.group.removeprefix(f"{NOTIFY_DOMAIN}."), service):
                add_defaults(data, defaults)
        calls.append((service, data))
    return calls


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/archive",
        vol.Required("record_ids"): vol.All([str], vol.Length(min=1, max=MAX_LIMIT)),
        vol.Optional("archived", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_archive(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Archive notifications for the caller, or restore them; it changes only the caller's own view."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, visible_to = scope
    changed = await store.async_set_archived(
        msg["record_ids"], connection.user.id, archived=msg["archived"], visible_to=visible_to
    )
    connection.send_result(msg["id"], {"changed": changed})
