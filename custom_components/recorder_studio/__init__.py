"""Recorder Studio: manage the Home Assistant recorder from a modern sidebar panel."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import service, websocket_api
from .const import DOMAIN
from .panel import async_remove_panel, async_setup_panel
from .storage import async_load

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if service.is_sqlite(hass) is False:
        _LOGGER.error("Recorder Studio supports SQLite only; the recorder uses another backend.")
        return False
    await async_load(hass)
    domain = hass.data[DOMAIN]
    domain["pending_restart"] = False
    # Never create/overwrite the generated file on startup if the user has not configured anything yet,
    # so installing the integration alone changes nothing on disk.
    if not domain.get("ws_registered"):
        websocket_api.async_register(hass)
        domain["ws_registered"] = True
    if not domain.get("panel_registered"):
        await async_setup_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async_remove_panel(hass)
    return True
