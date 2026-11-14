"""Find out what sent a notification."""

from __future__ import annotations

from homeassistant.components.persistent_notification import DOMAIN as PN_DOMAIN
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.frame import MissingIntegrationFrame, get_integration_frame
from homeassistant.helpers.trace import trace_id_get
from homeassistant.loader import IntegrationNotLoaded, async_get_loaded_integration

from .const import DOMAIN
from .models import Origin, OriginKind

KINDS = {"automation": OriginKind.AUTOMATION, "script": OriginKind.SCRIPT}
NOT_CALLERS = {DOMAIN, PN_DOMAIN}
"""Integrations on the stack that only pass a notification on: this one, and the bell reporting a change."""


def resolve_origin(hass: HomeAssistant, context: Context) -> Origin:
    """Return the origin of a service call that is running right now.

    Home Assistant keeps the trace of the running automation or script in a context variable; it
    is still set while the listeners of the call_service event run, also for the calls a notify
    group makes for its members. Those listeners run inside the call, so without an automation,
    script or user the call stack still holds the integration that made it.
    """
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


def _calling_integration(hass: HomeAssistant) -> Origin:
    """Return the custom integration that made the call, Home Assistant for a built-in one, else unknown."""
    try:
        frame = get_integration_frame(exclude_integrations=NOT_CALLERS)
    except MissingIntegrationFrame:
        return Origin(kind=OriginKind.UNKNOWN)
    if not frame.custom_integration:
        return Origin(kind=OriginKind.SYSTEM)
    domain = frame.integration
    try:
        name = async_get_loaded_integration(hass, domain).name
    except IntegrationNotLoaded:
        name = domain
    return Origin(kind=OriginKind.INTEGRATION, name=name, integration=domain)
