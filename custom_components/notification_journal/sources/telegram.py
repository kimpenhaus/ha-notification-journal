"""Record the messages the Telegram bot integration sends through its own actions."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import target

from ..models import Recipient, RecipientKind
from ..recipients import NOTIFY_DOMAIN, entity_recipient
from ..store import NotificationStore
from . import ATTR_TITLE, TARGET_KEYS, Listener, as_list, new_record

TELEGRAM_DOMAIN = "telegram_bot"
TEXT_FIELDS = {
    "send_message": "message",
    "send_photo": "caption",
    "send_video": "caption",
    "send_animation": "caption",
    "send_voice": "caption",
    "send_document": "caption",
    "send_poll": "question",
}
ATTR_CHAT_ID = "chat_id"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"


class TelegramSource:
    """Record every telegram_bot message with text; a photo or file without a caption is no notification.

    Messages sent with notify.send_message to the bot's notify entities are recorded by the notify source.
    """

    name = TELEGRAM_DOMAIN

    def __init__(self, hass: HomeAssistant, store: NotificationStore, *, excluded_channels: set[str]) -> None:
        """Bind the source to Home Assistant and the store."""
        self._hass = hass
        self._store = store
        self._excluded = excluded_channels

    def listeners(self) -> list[Listener]:
        """The calls of the telegram_bot send actions."""
        return [(EVENT_CALL_SERVICE, self._handle, _is_telegram)]

    @callback
    def _handle(self, event: Event) -> None:
        service: str = event.data["service"]
        data: dict[str, Any] = dict(event.data.get("service_data") or {})
        text_field = TEXT_FIELDS[service]
        message = str(data.get(text_field) or "").strip()
        if not message:
            return
        channel = f"{TELEGRAM_DOMAIN}.{service}"
        chats = self._chats(data)
        if not chats or self._excluded.intersection({channel, *(chat.id for chat in chats)}):
            return
        ignored = {text_field, ATTR_TITLE, ATTR_CHAT_ID, ATTR_CONFIG_ENTRY_ID, *TARGET_KEYS}
        extra = {key: value for key, value in data.items() if key not in ignored}
        self._store.add(
            new_record(
                self._hass,
                event,
                source=self.name,
                channel=channel,
                title=data.get(ATTR_TITLE),
                message=message,
                data=extra,
                recipients=chats,
            )
        )

    def _chats(self, data: dict[str, Any]) -> list[Recipient]:
        """Return the chats a call reaches: notify entities, chat IDs, or the bot's first chat when none is given."""
        found: dict[str, Recipient] = {}
        selected = target.async_extract_referenced_entity_ids(
            self._hass, target.TargetSelection({key: data[key] for key in TARGET_KEYS if key in data})
        )
        for entity_id in sorted(selected.referenced | selected.indirectly_referenced):
            if entity_id.startswith(f"{NOTIFY_DOMAIN}."):
                found[entity_id] = entity_recipient(self._hass, entity_id, RecipientKind.CHAT)
        chat_ids = {int(chat_id) for chat_id in as_list(data.get(ATTR_CHAT_ID))}
        if (chat_ids or not found) and (entry := self._entry(data.get(ATTR_CONFIG_ENTRY_ID))) is not None:
            subentries = list(entry.subentries.values())
            wanted = chat_ids or ({subentries[0].data[ATTR_CHAT_ID]} if subentries else set())
            entities = {
                e.config_subentry_id: e.entity_id
                for e in er.async_entries_for_config_entry(er.async_get(self._hass), entry.entry_id)
                if e.domain == NOTIFY_DOMAIN
            }
            for subentry in subentries:
                if subentry.data.get(ATTR_CHAT_ID) in wanted:
                    chat_id = entities.get(subentry.subentry_id, f"{TELEGRAM_DOMAIN}.{subentry.data[ATTR_CHAT_ID]}")
                    found.setdefault(chat_id, Recipient(kind=RecipientKind.CHAT, id=chat_id, name=subentry.title))
        return list(found.values())

    def _entry(self, entry_id: str | None) -> ConfigEntry | None:
        """Return the bot a call names, or the only one; with several and none named, Telegram refuses the call."""
        if entry_id is not None:
            return self._hass.config_entries.async_get_entry(entry_id)
        entries = self._hass.config_entries.async_entries(TELEGRAM_DOMAIN)
        return entries[0] if len(entries) == 1 else None


@callback
def _is_telegram(event_data: dict[str, Any]) -> bool:
    return event_data.get("domain") == TELEGRAM_DOMAIN and event_data.get("service") in TEXT_FIELDS
