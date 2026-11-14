"""Record the notifications Home Assistant shows under the bell in the sidebar."""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components import persistent_notification
from homeassistant.components.persistent_notification import Notification, UpdateType
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from ..models import NotificationRecord, Origin, OriginKind, Recipient, RecipientKind, Status
from ..origin import resolve_origin
from ..recipients import NOTIFY_DOMAIN
from ..store import NotificationStore

PN_DOMAIN = persistent_notification.DOMAIN
CREATE_SERVICES = {(PN_DOMAIN, "create"), (NOTIFY_DOMAIN, PN_DOMAIN), (NOTIFY_DOMAIN, "send_message")}
DISMISS_SERVICES = {(PN_DOMAIN, "dismiss"), (PN_DOMAIN, "dismiss_all")}
SERVICE_WINDOW = 1.0
EVERYONE = Recipient(kind=RecipientKind.EVERYONE, id=PN_DOMAIN, name="Home Assistant")


@dataclass(frozen=True, slots=True)
class _ServiceCall:
    domain: str
    service: str
    context: Context
    started: float


_service_call: ContextVar[_ServiceCall | None] = ContextVar("notification_journal_pn_call", default=None)


def _current(hass: HomeAssistant) -> dict[str, Notification]:
    """Return the notifications under the bell right now; the integration offers no public getter."""
    return dict(hass.data.get(PN_DOMAIN) or {})


class PersistentNotificationSource:
    """Record every notification under the bell, and when and by whom it was dismissed or replaced.

    The integration reports a notification without the context of the call that created or dismissed
    it. Its services run right after the call_service event, in the same asyncio context, so the
    listener of that event leaves the call in a context variable for the update that follows.
    """

    name = PN_DOMAIN

    def __init__(self, hass: HomeAssistant, store: NotificationStore) -> None:
        """Bind the source to Home Assistant and the store."""
        self._hass = hass
        self._store = store
        self._open: dict[str, tuple[str, datetime]] = {}

    async def async_start(self) -> CALLBACK_TYPE:
        """Catch up with the notifications under the bell, then follow their changes."""
        self._open = await self._store.async_open_records(self.name)
        remove_calls = self._hass.bus.async_listen(EVENT_CALL_SERVICE, self._handle_call, event_filter=_is_relevant)
        remove_updates = persistent_notification.async_register_callback(self._hass, self._handle_update)
        self._catch_up(_current(self._hass))

        @callback
        def _stop() -> None:
            remove_calls()
            remove_updates()

        return _stop

    @callback
    def _handle_call(self, event: Event) -> None:
        _service_call.set(
            _ServiceCall(
                domain=event.data["domain"],
                service=event.data["service"],
                context=event.context,
                started=time.monotonic(),
            )
        )

    @callback
    def _handle_update(self, update_type: UpdateType, notifications: dict[str, Notification]) -> None:
        if update_type in (UpdateType.ADDED, UpdateType.UPDATED):
            context, origin = self._cause(CREATE_SERVICES)
            for notification in notifications.values():
                self._add(notification, context, origin)
        elif update_type is UpdateType.REMOVED:
            _, origin = self._cause(DISMISS_SERVICES)
            for notification_id in notifications:
                self._close(notification_id, Status.DISMISSED, origin)

    @callback
    def _catch_up(self, current: dict[str, Notification]) -> None:
        """Record what appeared and close what disappeared while the integration was not running."""
        system = Origin(kind=OriginKind.SYSTEM)
        for notification_id in [ref for ref in self._open if ref not in current]:
            self._close(notification_id, Status.DISMISSED, system)
        for notification_id, notification in current.items():
            known = self._open.get(notification_id)
            if known is None or known[1] != notification["created_at"]:
                self._add(notification, Context(), system)

    def _cause(self, services: set[tuple[str, str]]) -> tuple[Context, Origin]:
        """Return the context and origin of the service call behind an update, or those of Home Assistant itself."""
        call = _service_call.get()
        if (
            call is not None
            and (call.domain, call.service) in services
            and time.monotonic() - call.started < SERVICE_WINDOW
        ):
            return call.context, resolve_origin(self._hass, call.context)
        context = Context()
        origin = resolve_origin(self._hass, context)
        return context, origin if origin.kind is not OriginKind.UNKNOWN else Origin(kind=OriginKind.SYSTEM)

    def _add(self, notification: Notification, context: Context, origin: Origin) -> None:
        notification_id = notification["notification_id"]
        self._close(notification_id, Status.REPLACED, origin)
        record = NotificationRecord(
            id=ulid_now(),
            time=notification["created_at"],
            source=self.name,
            channel=PN_DOMAIN,
            title=notification["title"],
            message=notification["message"],
            data=None,
            recipients=[EVERYONE],
            origin=origin,
            context_id=context.id,
            source_ref=notification_id,
        )
        self._store.add(record)
        self._open[notification_id] = (record.id, record.time)

    def _close(self, notification_id: str, status: Status, origin: Origin) -> None:
        if (known := self._open.pop(notification_id, None)) is not None:
            self._store.set_status(known[0], status, dt_util.utcnow(), origin)


@callback
def _is_relevant(event_data: dict[str, str]) -> bool:
    return event_data.get("domain") in (PN_DOMAIN, NOTIFY_DOMAIN)
