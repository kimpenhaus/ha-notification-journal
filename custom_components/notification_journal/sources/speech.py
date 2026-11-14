"""Record speech announcements: tts.speak on media players and assist_satellite.announce on voice satellites."""

from __future__ import annotations

from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import target
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from ..models import NotificationRecord, Recipient, RecipientKind
from ..origin import resolve_origin
from ..recipients import entity_group_members
from ..store import NotificationStore
from . import TARGET_KEYS, as_list

TTS_DOMAIN = "tts"
SATELLITE_DOMAIN = "assist_satellite"
MEDIA_PLAYER_DOMAIN = "media_player"
SERVICES = {(TTS_DOMAIN, "speak"): MEDIA_PLAYER_DOMAIN, (SATELLITE_DOMAIN, "announce"): SATELLITE_DOMAIN}
ATTR_MESSAGE = "message"
ATTR_MEDIA_PLAYERS = "media_player_entity_id"


class SpeechSource:
    """Record every spoken announcement with text; one without text (only a sound) is no notification."""

    name = "speech"

    def __init__(self, hass: HomeAssistant, store: NotificationStore, *, excluded_channels: set[str]) -> None:
        """Bind the source to Home Assistant and the store."""
        self._hass = hass
        self._store = store
        self._excluded = excluded_channels

    def async_start(self) -> CALLBACK_TYPE:
        """Listen to the calls of tts.speak and assist_satellite.announce."""
        return self._hass.bus.async_listen(EVENT_CALL_SERVICE, self._handle, event_filter=_is_speech)

    @callback
    def _handle(self, event: Event) -> None:
        domain: str = event.data["domain"]
        service: str = event.data["service"]
        data: dict[str, Any] = dict(event.data.get("service_data") or {})
        message = str(data.get(ATTR_MESSAGE) or "").strip()
        if not message:
            return
        channel = f"{domain}.{service}"
        if domain == TTS_DOMAIN:
            targets = {ATTR_ENTITY_ID: as_list(data.get(ATTR_MEDIA_PLAYERS))}
            ignored = {ATTR_MESSAGE, ATTR_MEDIA_PLAYERS, *TARGET_KEYS}
        else:
            targets = {key: data[key] for key in TARGET_KEYS if key in data}
            ignored = {ATTR_MESSAGE, *TARGET_KEYS}
        speakers = self._speakers(targets, SERVICES[(domain, service)])
        if not speakers or self._excluded.intersection({channel, *speakers}):
            return
        extra = {key: value for key, value in data.items() if key not in ignored}
        self._store.add(
            NotificationRecord(
                id=ulid_now(),
                time=dt_util.utcnow(),
                source=self.name,
                channel=channel,
                title=None,
                message=message,
                data=extra or None,
                recipients=[self._recipient(entity_id) for entity_id in speakers],
                origin=resolve_origin(self._hass, event.context),
                context_id=event.context.id,
            )
        )

    def _speakers(self, targets: dict[str, Any], domain: str) -> list[str]:
        """Return the players or satellites a call reaches: areas, devices and labels resolved, groups expanded."""
        selected = target.async_extract_referenced_entity_ids(self._hass, target.TargetSelection(targets))
        pending = sorted(selected.referenced | selected.indirectly_referenced)
        seen: set[str] = set()
        found: list[str] = []
        while pending:
            entity_id = pending.pop(0)
            if entity_id in seen:
                continue
            seen.add(entity_id)
            if (members := entity_group_members(self._hass, entity_id)) is not None:
                pending.extend(members)
            elif entity_id.startswith(f"{domain}."):
                found.append(entity_id)
        return found

    def _recipient(self, entity_id: str) -> Recipient:
        state = self._hass.states.get(entity_id)
        return Recipient(kind=RecipientKind.SPEAKER, id=entity_id, name=state.name if state else entity_id)


@callback
def _is_speech(event_data: dict[str, Any]) -> bool:
    return (event_data.get("domain"), event_data.get("service")) in SERVICES
