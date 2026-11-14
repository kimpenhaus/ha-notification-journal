"""Find out what sent a notification."""

from __future__ import annotations

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.trace import trace_id_get

from .models import Origin, OriginKind

KINDS = {"automation": OriginKind.AUTOMATION, "script": OriginKind.SCRIPT}


def resolve_origin(hass: HomeAssistant, context: Context) -> Origin:
    """Return the origin of a service call that is running right now.

    Home Assistant keeps the trace of the running automation or script in a context variable; it
    is still set while the listeners of the call_service event run, also for the calls a notify
    group makes for its members.
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
    return Origin(kind=OriginKind.UNKNOWN)
