"""Mark a notification failed when the action that sent it reports an error it does not raise.

The Companion app's notify actions catch a push that fails (push server unreachable, timeout, rate limit) and only
log it; the action itself succeeds. The log line is written while the action runs, in the asyncio context of the
call, where the notify source has left which record and channel the call belongs to.
"""

from __future__ import annotations

import logging

from homeassistant.core import CALLBACK_TYPE, HomeAssistant

from .recipients import MOBILE_APP_DOMAIN, NOTIFY_DOMAIN, mobile_app_entry
from .sources.notify import current_call
from .store import NotificationStore

MOBILE_APP_LOGGER = "homeassistant.components.mobile_app.notify"


class _FailureLog(logging.Handler):
    def __init__(self, hass: HomeAssistant, store: NotificationStore) -> None:
        super().__init__(logging.WARNING)
        self._hass = hass
        self._store = store

    def emit(self, record: logging.LogRecord) -> None:
        call = current_call.get()
        if call is not None and _names_target(self._hass, call.channel, message := record.getMessage()):
            self._store.mark_failed(call.record_id, call.channel, message)


def _names_target(hass: HomeAssistant, channel: str, message: str) -> bool:
    """Whether a message names no device, or the device the channel sends to.

    The Companion app names the device in its error; a push it falls back to later, outside of its own call, could
    otherwise be attributed to the call whose context it runs in.
    """
    entry = mobile_app_entry(hass, channel.removeprefix(f"{NOTIFY_DOMAIN}."))
    return (
        entry is None
        or entry.title in message
        or not any(other.title in message for other in hass.config_entries.async_entries(MOBILE_APP_DOMAIN))
    )


def watch_failures(hass: HomeAssistant, store: NotificationStore) -> CALLBACK_TYPE:
    """Start watching the Companion app's log for failed pushes; return how to stop."""
    handler = _FailureLog(hass, store)
    logger = logging.getLogger(MOBILE_APP_LOGGER)
    logger.addHandler(handler)
    return lambda: logger.removeHandler(handler)
