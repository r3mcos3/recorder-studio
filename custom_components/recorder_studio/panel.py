from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PANEL_ICON, PANEL_PATH, PANEL_TITLE, STATIC_URL, VERSION

_FRONTEND = Path(__file__).parent / "frontend"


async def async_setup_panel(hass: HomeAssistant) -> None:
    # Static dir serves panel + vendored lit; the panel imports ./vendor/lit.js relatively.
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(_FRONTEND), cache_headers=False)])
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_PATH,
        config={
            "_panel_custom": {
                "name": "recorder-studio-panel",
                "module_url": f"{STATIC_URL}/recorder-studio-panel.js?v={VERSION}",
                "trust_external": False,
            }
        },
        require_admin=True,
    )
    hass.data[DOMAIN]["panel_registered"] = True


def async_remove_panel(hass: HomeAssistant) -> None:
    if hass.data.get(DOMAIN, {}).pop("panel_registered", None):
        frontend.async_remove_panel(hass, PANEL_PATH)
