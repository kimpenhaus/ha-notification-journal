"""Tests of the config flow, the options flow and setting up the entry."""

import json
from pathlib import Path

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notification_journal.const import (
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
    CONF_STATISTICS_YEARS,
    DEFAULT_OPTIONS,
    DOMAIN,
    TITLE,
)

COMPONENT = Path(__file__).parent.parent / "custom_components" / DOMAIN


async def test_user_flow_creates_entry_with_default_options(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["options"] == DEFAULT_OPTIONS


async def test_only_one_instance(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_options_flow_stores_options(hass: HomeAssistant) -> None:
    hass.services.async_register("notify", "mobile_app_phone", lambda call: None)
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "sources": {
                CONF_RECORD_NOTIFY: True,
                CONF_RECORD_PERSISTENT: False,
                CONF_RECORD_SPEECH: False,
                CONF_RECORD_TELEGRAM: False,
                CONF_EXCLUDED_CHANNELS: ["notify.mobile_app_phone"],
            },
            "retention": {CONF_RETENTION_DAYS: 30.0, CONF_MAX_ENTRIES: 5000.0, CONF_STATISTICS_YEARS: 3.0},
            "access": {CONF_NON_ADMIN_VISIBILITY: "none"},
            "sidebar": {CONF_SHOW_IN_SIDEBAR: False, CONF_PANEL_TITLE: " Mitteilungen ", CONF_PANEL_ICON: "mdi:bell"},
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_RECORD_NOTIFY: True,
        CONF_RECORD_PERSISTENT: False,
        CONF_RECORD_SPEECH: False,
        CONF_RECORD_TELEGRAM: False,
        CONF_EXCLUDED_CHANNELS: ["notify.mobile_app_phone"],
        CONF_RETENTION_DAYS: 30,
        CONF_MAX_ENTRIES: 5000,
        CONF_STATISTICS_YEARS: 3,
        CONF_NON_ADMIN_VISIBILITY: "none",
        CONF_SHOW_IN_SIDEBAR: False,
        CONF_PANEL_TITLE: "Mitteilungen",
        CONF_PANEL_ICON: "mdi:bell",
    }
    assert entry.state is ConfigEntryState.LOADED


async def test_options_flow_drops_an_empty_title(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, CONF_PANEL_TITLE: "Mitteilungen"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "sources": {
                CONF_RECORD_NOTIFY: True,
                CONF_RECORD_PERSISTENT: True,
                CONF_RECORD_SPEECH: True,
                CONF_RECORD_TELEGRAM: True,
            },
            "retention": {CONF_RETENTION_DAYS: 90, CONF_MAX_ENTRIES: 100000, CONF_STATISTICS_YEARS: 2},
            "access": {CONF_NON_ADMIN_VISIBILITY: "own"},
            "sidebar": {CONF_SHOW_IN_SIDEBAR: True, CONF_PANEL_TITLE: "  "},
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_PANEL_TITLE not in entry.options
    assert CONF_PANEL_ICON not in entry.options


async def test_options_form_offers_qualified_channels(hass: HomeAssistant) -> None:
    hass.services.async_register("notify", "mobile_app_phone", lambda call: None)
    hass.services.async_register("notify", "send_message", lambda call: None)
    hass.states.async_set("notify.kitchen_display", "unknown")
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, CONF_EXCLUDED_CHANNELS: ["old_service"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    sources = result["data_schema"].schema["sources"]
    assert sources.options == {"collapsed": False}
    key, selector = next((k, v) for k, v in sources.schema.schema.items() if k == CONF_EXCLUDED_CHANNELS)
    assert selector.config["options"] == ["notify.kitchen_display", "notify.mobile_app_phone", "notify.old_service"]
    assert key.description == {"suggested_value": ["notify.old_service"]}
    assert result["data_schema"].schema["sidebar"].options == {"collapsed": True}


def test_translations_match_strings() -> None:
    def keys(node: object, prefix: str = "") -> set[str]:
        if isinstance(node, dict):
            return {key for name, value in node.items() for key in keys(value, f"{prefix}{name}.")}
        return {prefix.rstrip(".")}

    strings = keys(json.loads((COMPONENT / "strings.json").read_text()))
    for language in ("en", "de"):
        translation = keys(json.loads((COMPONENT / "translations" / f"{language}.json").read_text()))
        assert translation == strings, language
