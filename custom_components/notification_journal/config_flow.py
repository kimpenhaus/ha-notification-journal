"""Config and options flow of the Notification Journal integration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_EXCLUDED_CHANNELS,
    CONF_MAX_ENTRIES,
    CONF_NON_ADMIN_VISIBILITY,
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    CONF_RECORD_NOTIFY,
    CONF_RECORD_PERSISTENT,
    CONF_RECORD_SPEECH,
    CONF_RECORD_TELEGRAM,
    CONF_RETENTION_DAYS,
    CONF_SHOW_IN_SIDEBAR,
    DEFAULT_OPTIONS,
    DOMAIN,
    MAX_MAX_ENTRIES,
    MAX_RETENTION_DAYS,
    MIN_MAX_ENTRIES,
    MIN_RETENTION_DAYS,
    PANEL_ICON,
    TITLE,
    Visibility,
)
from .recipients import excludable_channels, qualify_channel

OPEN_SECTION = "sources"


class NotificationJournalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the integration; there is only one instance."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm and create the entry with the default options."""
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={}, options=deepcopy(DEFAULT_OPTIONS))
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NotificationJournalOptionsFlow:
        """Return the options flow."""
        return NotificationJournalOptionsFlow()


class NotificationJournalOptionsFlow(OptionsFlowWithReload):
    """Change what is recorded and for how long; the form groups the options in sections, they are stored flat."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            options = {key: value for part in user_input.values() for key, value in part.items()}
            options[CONF_RETENTION_DAYS] = int(options[CONF_RETENTION_DAYS])
            options[CONF_MAX_ENTRIES] = int(options[CONF_MAX_ENTRIES])
            for key in (CONF_PANEL_TITLE, CONF_PANEL_ICON):
                if value := str(options.pop(key, None) or "").strip():
                    options[key] = value
            return self.async_create_entry(data=options)

        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        current[CONF_EXCLUDED_CHANNELS] = [qualify_channel(c) for c in current[CONF_EXCLUDED_CHANNELS]]
        schema = self._schema(current[CONF_EXCLUDED_CHANNELS])
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, {str(key): current for key in schema.schema}),
        )

    def _schema(self, excluded: list[str]) -> vol.Schema:
        sections = {
            OPEN_SECTION: {
                vol.Required(CONF_RECORD_NOTIFY): selector.BooleanSelector(),
                vol.Required(CONF_RECORD_PERSISTENT): selector.BooleanSelector(),
                vol.Required(CONF_RECORD_SPEECH): selector.BooleanSelector(),
                vol.Required(CONF_RECORD_TELEGRAM): selector.BooleanSelector(),
                vol.Optional(CONF_EXCLUDED_CHANNELS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sorted(excludable_channels(self.hass) | set(excluded)),
                        multiple=True,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            },
            "retention": {
                vol.Required(CONF_RETENTION_DAYS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_RETENTION_DAYS,
                        max=MAX_RETENTION_DAYS,
                        step=1,
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="d",
                    )
                ),
                vol.Required(CONF_MAX_ENTRIES): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_MAX_ENTRIES, max=MAX_MAX_ENTRIES, step=1, mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
            },
            "access": {
                vol.Required(CONF_NON_ADMIN_VISIBILITY): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[visibility.value for visibility in Visibility],
                        translation_key=CONF_NON_ADMIN_VISIBILITY,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            },
            "sidebar": {
                vol.Required(CONF_SHOW_IN_SIDEBAR): selector.BooleanSelector(),
                vol.Optional(CONF_PANEL_TITLE): selector.TextSelector(),
                vol.Optional(CONF_PANEL_ICON): selector.IconSelector(
                    selector.IconSelectorConfig(placeholder=PANEL_ICON)
                ),
            },
        }
        return vol.Schema(
            {
                vol.Required(name): section(vol.Schema(fields), {"collapsed": name != OPEN_SECTION})
                for name, fields in sections.items()
            }
        )
