"""WebSocket commands the panel uses: list, get, facets and live updates."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import CONF_NON_ADMIN_VISIBILITY, DEFAULT_OPTIONS, DOMAIN, SIGNAL_CHANGED, Visibility
from .models import NotificationRecord, RecipientKind, Status
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
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_delete)
    websocket_api.async_register_command(hass, ws_archive)


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
    hass: HomeAssistant, record: NotificationRecord, people: dict[str, State] | None = None
) -> dict[str, Any]:
    """Return a record as the panel uses it: people with their current name and picture, and the path to its trace."""
    result = record.as_dict()
    if people is None:
        people = _people(hass)
    for recipient in [*result["recipients"], *(r for call in result["inner_calls"] for r in call["recipients"])]:
        if recipient["kind"] == RecipientKind.PERSON and (state := people.get(recipient["id"])):
            recipient["name"] = state.name
            recipient["picture"] = state.attributes.get("entity_picture")
    origin = record.origin
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
        vol.Optional("since"): cv.datetime,
        vol.Optional("until"): cv.datetime,
        vol.Optional("user_id"): str,
        vol.Optional("newest_first", default=True): bool,
        vol.Optional("group_by"): vol.In([GROUP_BY_ORIGIN]),
        vol.Optional("archived", default=False): bool,
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=MAX_LIMIT)),
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
    }
)
@websocket_api.async_response
async def ws_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """List notifications, newest first unless asked otherwise."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, user_id = scope
    page = await store.async_query(
        Query(
            user_id=user_id,
            text=msg.get("text"),
            channel=msg.get("channel"),
            origin_entity_id=msg.get("origin"),
            status=Status(msg["status"]) if "status" in msg else None,
            since=msg.get("since"),
            until=msg.get("until"),
            newest_first=msg["newest_first"],
            group_by_origin=msg.get("group_by") == GROUP_BY_ORIGIN,
            archive_user_id=connection.user.id,
            archived=msg["archived"],
            limit=msg["limit"],
            offset=msg["offset"],
            with_counts=msg["offset"] == 0,
        )
    )
    people = _people(hass)
    result: dict[str, Any] = {"records": [serialize(hass, r, people) for r in page.records]}
    if page.total is not None:
        result["total"] = page.total
    if page.groups is not None:
        result["groups"] = page.groups
    connection.send_result(msg["id"], result)


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
    connection.send_result(msg["id"], serialize(hass, record))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/facets", vol.Optional("user_id"): str})
@websocket_api.async_response
async def ws_facets(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return what the filters can offer: channels, groups, origins and, for administrators, people."""
    if (scope := _store_and_scope(hass, connection, msg)) is None:
        return
    store, user_id = scope
    facets: dict[str, Any] = await store.async_facets(user_id)
    facets["people"] = (
        [
            {"id": state.attributes["user_id"], "name": state.name, "picture": state.attributes.get("entity_picture")}
            for state in hass.states.async_all("person")
            if state.attributes.get("user_id")
        ]
        if connection.user.is_admin
        else []
    )
    connection.send_result(msg["id"], facets)


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
                websocket_api.event_message(msg["id"], {"change": change, "record": serialize(hass, record)})
            )

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_CHANGED, _forward)
    connection.send_result(msg["id"])


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
