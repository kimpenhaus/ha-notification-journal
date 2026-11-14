"""The sidebar panel: the scripts the browser loads, the icon and the place in the sidebar."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    FRONTEND_URL,
    ICONSET_URL,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_MODULE_URL,
    PANEL_TITLES,
    PANEL_URL_PATH,
    TITLE,
)

FRONTEND_DIR = Path(__file__).parent / "frontend"
SCRIPTS = ("panel.js", "iconset.js")


class PanelScriptView(HomeAssistantView):
    """Serve the panel's scripts so that browsers revalidate them and pick up a deployment without restart."""

    url = FRONTEND_URL + "/{filename}"
    name = f"{DOMAIN}:frontend"
    requires_auth = False

    async def get(self, request: web.Request, filename: str) -> web.StreamResponse:
        """Return a bundled script."""
        if filename not in SCRIPTS:
            raise web.HTTPNotFound
        script = FRONTEND_DIR / filename
        if not await request.app[KEY_HASS].async_add_executor_job(script.is_file):
            raise web.HTTPNotFound
        return web.FileResponse(script, headers={"Cache-Control": "no-cache"})


@callback
def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the scripts and load the icon set with every frontend, so the sidebar can show the icon."""
    hass.http.register_view(PanelScriptView())
    frontend.add_extra_js_url(hass, ICONSET_URL)


@callback
def async_register_panel(
    hass: HomeAssistant,
    *,
    require_admin: bool,
    show_in_sidebar: bool = True,
    title: str | None = None,
    icon: str | None = None,
) -> None:
    """Register the panel; hidden from the sidebar it stays reachable under its path.

    `panel_custom.async_register_panel` cannot hide a panel from the sidebar, so this registers the same
    custom panel with the frontend directly.
    """
    language = (hass.config.language or "en").split("-")[0]
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=title or PANEL_TITLES.get(language, TITLE),
        sidebar_icon=icon or PANEL_ICON,
        frontend_url_path=PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": PANEL_COMPONENT,
                "module_url": PANEL_MODULE_URL,
                "embed_iframe": False,
                "trust_external": False,
            }
        },
        require_admin=require_admin,
        show_in_sidebar=show_in_sidebar,
    )


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """Take the panel out of the sidebar."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
