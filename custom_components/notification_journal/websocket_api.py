"""WebSocket commands the panel uses: list, get, facets, statistics and live updates."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

import voluptuous as vol
from homeassistant.auth.models import User
from homeassistant.components import websocket_api
from homeassistant.components.group.notify import add_defaults
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant, State, callback
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import CONF_NON_ADMIN_VISIBILITY, DEFAULT_OPTIONS, DOMAIN, SIGNAL_CHANGED, Visibility
from .models import CHANNEL_SEPARATOR, NotificationRecord, RecipientKind
from .origin import OriginNames, origin_key
from .recipients import NOTIFY_DOMAIN, SEND_MESSAGE, member_defaults
from .send import TARGET, SendCall, calls, targets, titled
from .sources.notify import is_command, resend
from .statistics import FAILED, PERIOD_KINDS, period, summarize
from .store import NotificationStore, Query, StatusFilter

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
    websocket_api.async_register_command(hass, ws_targets)
    websocket_api.async_register_command(hass, ws_send)


FILTERS = {
    vol.Optional("text"): cv.string,
    vol.Optional("channel"): cv.string,
    vol.Optional("origin"): cv.string,
    vol.Optional("status"): vol.In([status.value for status in StatusFilter]),
    vol.Optional("tag"): cv.string,
    vol.Optional("since"): cv.datetime,
    vol.Optional("until"): cv.datetime,
    vol.Optional("newest_first", default=True): cv.boolean,
    vol.Optional("limit", default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_LIMIT)),
}
"""The filters of the list, shared by the command and the query action."""


def filters(data: dict[str, Any]) -> dict[str, Any]:
    """Return the fields of a `Query` for validated FILTERS; a time without a zone is Home Assistant's."""
    return {
        "text": data.get("text"),
        "channel": data.get("channel"),
        "origin": data.get("origin"),
        "status": StatusFilter(data["status"]) if "status" in data else None,
        "tag": data.get("tag"),
        "since": dt_util.as_utc(data["since"]) if "since" in data else None,
        "until": dt_util.as_utc(data["until"]) if "until" in data else None,
        "newest_first": data["newest_first"],
        "limit": data["limit"],
    }


def loaded_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the integration's entry while it is loaded."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0] if entries else None


def non_admins_see_nothing(entry: ConfigEntry) -> bool:
    """Return whether users who are no administrators may see nothing of the journal."""
    return {**DEFAULT_OPTIONS, **entry.options}[CONF_NON_ADMIN_VISIBILITY] == Visibility.NONE


def scope_of(entry: ConfigEntry, user: User, context: Context | None = None) -> str | None:
    """Return the user a caller is limited to, none for an administrator; raise Unauthorized when they see nothing."""
    if user.is_admin:
        return None
    if non_admins_see_nothing(entry):
        raise Unauthorized(context=context)
    return user.id


def _store_and_scope(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[NotificationStore, str | None] | None:
    """Return the store and the user the caller is limited to, or send an error and return None."""
    if (entry := loaded_entry(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "Notification Journal is not set up")
        return None
    try:
        user_id = scope_of(entry, connection.user)
    except Unauthorized:
        connection.send_error(msg["id"], websocket_api.ERR_UNAUTHORIZED, "Only administrators see the history")
        return None
    return entry.runtime_data.store, msg.get("user_id") if user_id is None else user_id


def current_people(hass: HomeAssistant) -> dict[str, State]:
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
        people = current_people(hass)
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
        **FILTERS,
        vol.Optional("user_id"): str,
        vol.Optional("group_by"): vol.In([GROUP_BY_ORIGIN]),
        vol.Optional("archived", default=False): bool,
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
            **filters(msg),
            group_by_origin=msg.get("group_by") == GROUP_BY_ORIGIN,
            archive_user_id=connection.user.id,
            archived=msg["archived"],
            offset=msg["offset"],
            with_counts=msg["offset"] == 0,
            days_in=zone,
        )
    )
    people = current_people(hass)
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
    return (entry := loaded_entry(hass)) is not None and non_admins_see_nothing(entry)


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
    sent = await _send_each(hass, store, lambda: connection.context(msg), record.id, _calls_again(hass, record))
    if errors := [error for error in sent if error]:
        connection.send_error(msg["id"], websocket_api.ERR_HOME_ASSISTANT_ERROR, "; ".join(errors))
        return
    connection.send_result(msg["id"])


async def _send_each(
    hass: HomeAssistant,
    store: NotificationStore,
    new_context: Callable[[], Context],
    record_id: str,
    sends: list[SendCall],
) -> list[str | None]:
    """Make the calls at once, each in its own context, recorded as sending the notification again; return the error of
    each call or None. A call that raises fails the notification it made."""

    async def send(call: SendCall) -> str | None:
        context = new_context()
        with resend(context.id, record_id) as sent:
            try:
                await hass.services.async_call(call.domain, call.service, call.data, blocking=True, context=context)
            except Exception as err:  # every target on its own, whatever its integration raises
                error = str(err) or type(err).__name__
                if sent.sent is not None:
                    store.mark_failed(sent.sent, None, error)
                return error
        return None

    return list(await asyncio.gather(*(send(call) for call in sends)))


def _calls_again(hass: HomeAssistant, record: NotificationRecord) -> list[SendCall]:
    """The notify calls that send a failed notification again: to each failed member of a group once, else as it
    was; notify entities through send_message, which takes text only."""
    failed = list(dict.fromkeys(call.channel for call in record.inner_calls if call.error and not call.group))
    found = []
    for channel in failed or [record.channel]:
        entities = channel.split(CHANNEL_SEPARATOR)
        if all(hass.states.get(entity) is not None for entity in entities):
            found.append(
                SendCall(NOTIFY_DOMAIN, SEND_MESSAGE, {**titled(record, record.message), ATTR_ENTITY_ID: entities})
            )
            continue
        service = channel.removeprefix(f"{NOTIFY_DOMAIN}.")
        data = {**titled(record, record.message), **deepcopy(record.data or {})}
        if record.group:
            for defaults in member_defaults(hass, record.group.removeprefix(f"{NOTIFY_DOMAIN}."), service):
                add_defaults(data, defaults)
        found.append(SendCall(NOTIFY_DOMAIN, service, data))
    return found


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/targets", vol.Optional("record_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_targets(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """What a notification can be sent to, and whether the Companion app gets its data too; administrators only."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, _ = scope
    record = await store.async_get(msg["record_id"]) if "record_id" in msg else None
    connection.send_result(msg["id"], targets(hass, record))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/send",
        vol.Required("record_id"): str,
        vol.Required("targets"): vol.All([TARGET], vol.Length(min=1, max=MAX_LIMIT)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_send(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Send a notification again to the chosen targets, each call on its own; return the error of each target or None.
    Administrators only."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, _ = scope
    record = await store.async_get(msg["record_id"])
    if record is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Notification not found")
        return
    if is_command(record.message):
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_SUPPORTED, "A command to the Companion app is no message"
        )
        return
    sends = calls(hass, record, msg["targets"])
    errors = await _send_each(hass, store, lambda: connection.context(msg), record.id, sends)
    connection.send_result(msg["id"], {"errors": errors})


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
