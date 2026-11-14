"""Tests of the sidebar panel and the script it loads."""

from pathlib import Path

import pytest
from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator, WebSocketGenerator

from custom_components.notification_journal import panel
from custom_components.notification_journal.const import (
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
    ICONSET_URL,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_MODULE_URL,
    PANEL_URL_PATH,
)


async def _setup(hass: HomeAssistant, **options: object) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, options={**DEFAULT_OPTIONS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _panels(hass_ws_client: WebSocketGenerator, hass: HomeAssistant) -> dict:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "get_panels"})
    return (await client.receive_json())["result"]


async def test_panel_is_in_the_sidebar_for_everyone(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    hass.config.language = "de"
    await _setup(hass)

    registered = (await _panels(hass_ws_client, hass))[PANEL_URL_PATH]
    assert registered["component_name"] == "custom"
    assert registered["title"] == "Benachrichtigungsverlauf"
    assert registered["require_admin"] is False
    assert registered["show_in_sidebar"] is True
    assert registered["icon"] == PANEL_ICON
    assert ICONSET_URL in hass.data[frontend.DATA_EXTRA_MODULE_URL].urls
    assert registered["config"]["_panel_custom"]["name"] == PANEL_COMPONENT
    assert registered["config"]["_panel_custom"]["module_url"] == PANEL_MODULE_URL


async def test_panel_is_for_admins_only_when_others_see_nothing(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass, **{CONF_NON_ADMIN_VISIBILITY: "none"})

    registered = (await _panels(hass_ws_client, hass))[PANEL_URL_PATH]
    assert registered["title"] == "Notification Journal"
    assert registered["require_admin"] is True


async def test_panel_hidden_from_the_sidebar_stays_registered(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass, **{CONF_SHOW_IN_SIDEBAR: False})

    registered = (await _panels(hass_ws_client, hass))[PANEL_URL_PATH]
    assert registered["show_in_sidebar"] is False
    assert registered["title"] == "Notification Journal"
    assert registered["config"]["_panel_custom"]["module_url"] == PANEL_MODULE_URL


async def test_panel_takes_title_and_icon_from_the_options(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    hass.config.language = "de"
    await _setup(hass, **{CONF_PANEL_TITLE: "Mitteilungen", CONF_PANEL_ICON: "mdi:bell"})

    registered = (await _panels(hass_ws_client, hass))[PANEL_URL_PATH]
    assert registered["title"] == "Mitteilungen"
    assert registered["icon"] == "mdi:bell"


async def test_changed_options_apply_without_restart(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    entry = await _setup(hass)

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "sources": {
                key: True
                for key in (CONF_RECORD_NOTIFY, CONF_RECORD_PERSISTENT, CONF_RECORD_SPEECH, CONF_RECORD_TELEGRAM)
            },
            "retention": {CONF_RETENTION_DAYS: 90, CONF_MAX_ENTRIES: 100000},
            "access": {CONF_NON_ADMIN_VISIBILITY: "own"},
            "sidebar": {CONF_SHOW_IN_SIDEBAR: False, CONF_PANEL_TITLE: "Mitteilungen"},
        },
    )
    await hass.async_block_till_done()

    registered = (await _panels(hass_ws_client, hass))[PANEL_URL_PATH]
    assert registered["show_in_sidebar"] is False
    assert registered["title"] == "Mitteilungen"


async def test_unloading_removes_the_panel(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)

    assert PANEL_URL_PATH not in await _panels(hass_ws_client, hass)


async def test_scripts_are_served_for_revalidation(
    hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "panel.js").write_text("export {};\n")
    (tmp_path / "iconset.js").write_text("// icons\n")
    (tmp_path / "other.js").write_text("// not served\n")
    monkeypatch.setattr(panel, "FRONTEND_DIR", tmp_path)
    await _setup(hass)
    client = await hass_client_no_auth()

    response = await client.get(PANEL_MODULE_URL)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-cache"
    assert "javascript" in response.headers["Content-Type"]
    assert await response.text() == "export {};\n"
    assert await (await client.get(ICONSET_URL)).text() == "// icons\n"
    assert (await client.get("/notification_journal/other.js")).status == 404

    (tmp_path / "panel.js").unlink()
    assert (await client.get(PANEL_MODULE_URL)).status == 404
