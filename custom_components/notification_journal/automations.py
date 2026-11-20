"""What automations get from the journal: events for recorded and failed notifications, and the query action."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from .const import DOMAIN, SERVICE_QUERY
from .models import NotificationRecord, RecipientKind, tag_of
from .origin import OriginNames, origin_key
from .store import Query
from .websocket_api import FILTERS, current_people, filters, loaded_entry, scope_of, serialize


def event_data(hass: HomeAssistant, record: NotificationRecord) -> dict[str, Any]:
    """Return a notification as the events carry it: what it said, to whom, from where, and what failed; people and
    origins with their current names, as the panel shows them."""
    key = origin_key(record.origin)
    recipients = []
    for recipient in record.recipients:
        state = hass.states.get(recipient.id) if recipient.kind is RecipientKind.PERSON else None
        recipients.append({"id": recipient.id, "name": state.name if state else recipient.name})
    return {
        "id": record.id,
        "time": record.time.isoformat(),
        "source": record.source,
        "channel": record.channel,
        "group": record.group,
        "title": record.title,
        "message": record.spoken_text or record.message,
        "recipients": recipients,
        "origin": {"key": key, "name": OriginNames(hass).name(key, record.origin.name)},
        "status": record.status.value,
        "tag": tag_of(record.data),
        "error": record.error,
        "failed_calls": [{"channel": call.channel, "error": call.error} for call in record.inner_calls if call.error],
    }


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the actions once."""

    async def _query(call: ServiceCall) -> ServiceResponse:
        if (entry := loaded_entry(hass)) is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
        user_id = None
        if call.context.user_id is not None:
            if (user := await hass.auth.async_get_user(call.context.user_id)) is None:
                raise Unauthorized(context=call.context)
            user_id = scope_of(entry, user, call.context)
        page = await entry.runtime_data.store.async_query(Query(user_id=user_id, **filters(call.data)))
        people, names = current_people(hass), OriginNames(hass)
        return {
            "records": [serialize(hass, record, people, names, user_id=user_id) for record in page.records],
            "total": page.total,
        }

    hass.services.async_register(
        DOMAIN, SERVICE_QUERY, _query, schema=vol.Schema(FILTERS), supports_response=SupportsResponse.ONLY
    )
