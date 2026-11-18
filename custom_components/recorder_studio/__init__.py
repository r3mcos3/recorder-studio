"""Recorder Studio: manage the Home Assistant recorder from a modern sidebar panel."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from . import service, websocket_api
from .const import ALERT_INTERVAL_HOURS, DOMAIN
from .panel import async_remove_panel, async_setup_panel
from .storage import async_load, async_save

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def _async_handle_apply_config(call: ServiceCall) -> dict:
    """Apply recorder_studio.yaml to the running recorder (used by the Recorder Studio DB add-on)."""
    return await service.async_apply_and_track(call.hass)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.services.async_register(DOMAIN, "apply_config", _async_handle_apply_config, supports_response=SupportsResponse.OPTIONAL)
    entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, "apply_config"))
    if service.is_sqlite(hass) is False:
        # Another backend: the panel and statistics here are SQLite only (the Recorder Studio DB add-on covers those).
        # Only the live-apply service stays available, so the add-on can change recorder settings without a restart.
        _LOGGER.info("Recorder uses a non-SQLite database: Recorder Studio runs without its panel and only offers recorder_studio.apply_config.")
        return True
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

    async def _background_check(_now=None) -> None:
        """Keeps the daily size history growing and the Repairs alerts current while the panel is closed."""
        await service.async_analyze(hass, full=False)  # light, read-only
        await async_save(hass)
        await service.async_check_alerts(hass)

    @callback
    def _kick(_now) -> None:
        hass.async_create_task(_background_check(), "recorder_studio background check")

    entry.async_on_unload(async_track_time_interval(hass, _kick, timedelta(hours=ALERT_INTERVAL_HOURS)))
    entry.async_on_unload(async_call_later(hass, 120, _kick))  # first run shortly after start-up
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async_remove_panel(hass)
    return True
