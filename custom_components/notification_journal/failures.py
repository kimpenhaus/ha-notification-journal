"""Mark a notification failed when the action that sent it reports an error it does not raise.

The Companion app's notify actions catch a push that fails (push server unreachable, timeout, rate limit) and only
log it; the action itself succeeds. The log line is written while the action runs, in the asyncio context of the
call, where the notify source has left which record and channel the call belongs to.
"""

from __future__ import annotations

import logging

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.util import dt as dt_util

from .sources.notify import current_call
from .store import NotificationStore

MOBILE_APP_LOGGER = "homeassistant.components.mobile_app.notify"


class _FailureLog(logging.Handler):
    """Hands every warning or error the mobile app logs during a recorded call to the store."""

    def __init__(self, hass: HomeAssistant, store: NotificationStore) -> None:
        super().__init__(logging.WARNING)
        self._hass = hass
        self._store = store

    def emit(self, record: logging.LogRecord) -> None:
        if (call := current_call.get()) is None:
            return
        self._hass.loop.call_soon_threadsafe(
            self._store.mark_failed, call.record_id, call.channel, record.getMessage(), dt_util.utcnow()
        )


def watch_failures(hass: HomeAssistant, store: NotificationStore) -> CALLBACK_TYPE:
    """Start watching the mobile app's log for failed pushes; return how to stop."""
    handler = _FailureLog(hass, store)
    logger = logging.getLogger(MOBILE_APP_LOGGER)
    logger.addHandler(handler)
    return lambda: logger.removeHandler(handler)
