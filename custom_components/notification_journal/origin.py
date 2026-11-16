"""Find out what sent a notification."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace

from homeassistant.components.persistent_notification import DOMAIN as PN_DOMAIN
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.frame import MissingIntegrationFrame, get_integration_frame
from homeassistant.helpers.trace import trace_id_get
from homeassistant.loader import IntegrationNotLoaded, async_get_loaded_integration

from .const import DOMAIN, INTEGRATION_KEY_PREFIX
from .models import Origin, OriginKind

KINDS = {"automation": OriginKind.AUTOMATION, "script": OriginKind.SCRIPT}
KIND_KEYS = frozenset(kind.value for kind in OriginKind)
NOT_CALLERS = {DOMAIN, PN_DOMAIN}
"""Integrations on the stack that only pass a notification on: this one, and the bell reporting a change."""

replayed_origins: ContextVar[dict[str, Origin] | None] = ContextVar(
    "notification_journal_replayed_origins", default=None
)
"""Set while events from the recorder are replayed: the automations and scripts that ran, by context; the origin of
a replayed call comes from its recorded context instead of the trace and the call stack of the time."""


def resolve_origin(hass: HomeAssistant, context: Context) -> Origin:
    """Return the origin of a service call that is running right now.

    Home Assistant keeps the trace of the running automation or script in a context variable; it
    is still set while the listeners of the call_service event run, also for the calls a notify
    group makes for its members. Those listeners run inside the call, so without an automation,
    script or user the call stack still holds the integration that made it.
    """
    if (replayed := replayed_origins.get()) is not None:
        return _replayed_origin(replayed, context)
    if (trace_id := trace_id_get()) is not None:
        key, run_id = trace_id
        domain, _, item_id = key.partition(".")
        if domain in KINDS:
            entity_id = er.async_get(hass).async_get_entity_id(domain, domain, item_id)
            state = hass.states.get(entity_id) if entity_id else None
            return Origin(
                kind=KINDS[domain],
                entity_id=entity_id,
                name=state.name if state else item_id,
                trace_key=key,
                run_id=run_id,
                user_id=context.user_id,
            )
    if context.user_id:
        return Origin(kind=OriginKind.USER, user_id=context.user_id)
    return _calling_integration(hass)


def _replayed_origin(origins: dict[str, Origin], context: Context) -> Origin:
    """Return the automation or script that ran in a recorded context with who started it, else the user, else
    an unknown origin; all marked as imported."""
    if (origin := origins.get(context.id)) is not None:
        return replace(origin, user_id=context.user_id)
    if context.user_id:
        return Origin(kind=OriginKind.USER, user_id=context.user_id, imported=True)
    return Origin(kind=OriginKind.UNKNOWN, imported=True)


def _calling_integration(hass: HomeAssistant) -> Origin:
    """Return the custom integration that made the call, Home Assistant for a built-in one, else unknown."""
    try:
        frame = get_integration_frame(exclude_integrations=NOT_CALLERS)
    except MissingIntegrationFrame:
        return Origin(kind=OriginKind.UNKNOWN)
    if not frame.custom_integration:
        return Origin(kind=OriginKind.SYSTEM)
    domain = frame.integration
    return Origin(kind=OriginKind.INTEGRATION, name=_integration_name(hass, domain) or domain, integration=domain)


def _integration_name(hass: HomeAssistant, domain: str) -> str | None:
    try:
        return async_get_loaded_integration(hass, domain).name
    except IntegrationNotLoaded:
        return None


def origin_key(origin: Origin) -> str:
    """Return what identifies an origin across notifications: its automation or script, its integration, else its kind.

    Stored as `origin_key`; the view by origin, the origin filter and the statistics group by it.
    """
    if origin.entity_id:
        return origin.entity_id
    if origin.integration:
        return f"{INTEGRATION_KEY_PREFIX}{origin.integration}"
    return origin.kind.value


class OriginNames:
    """The current names of origins while answering one request.

    Each origin is looked up once, however many notifications it sent, and only in memory: the state machine, the
    entity registry and the loaded integrations.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Start without any names."""
        self._hass = hass
        self._names: dict[str, str | None] = {}

    def name(self, key: str, stored: str | None) -> str | None:
        """Return the current name of the origin with this key, else the stored one; a kind has no name of its own."""
        if key in KIND_KEYS:
            return stored
        if key not in self._names:
            self._names[key] = self._lookup(key)
        return self._names[key] or stored

    def _lookup(self, key: str) -> str | None:
        if key.startswith(INTEGRATION_KEY_PREFIX):
            return _integration_name(self._hass, key.removeprefix(INTEGRATION_KEY_PREFIX))
        if state := self._hass.states.get(key):
            return state.name
        if entry := er.async_get(self._hass).async_get(key):
            return entry.name or entry.original_name
        return None
