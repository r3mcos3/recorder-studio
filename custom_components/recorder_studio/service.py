"""Glue between the pure core and a running Home Assistant."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN, GENERATED_FILE
from .core import db_stats, tree, yaml_writer
from .storage import async_save

_LOGGER = logging.getLogger(__name__)


def _data(hass: HomeAssistant) -> dict:
    return hass.data[DOMAIN]["data"]


def recorder_db_url(hass: HomeAssistant) -> str | None:
    try:
        from homeassistant.components.recorder import get_instance

        return getattr(get_instance(hass), "db_url", None)
    except Exception:  # noqa: BLE001 - recorder not (yet) loaded
        return None


def is_sqlite(hass: HomeAssistant) -> bool | None:
    url = recorder_db_url(hass)
    return None if not url else url.lower().startswith("sqlite")


def db_path(hass: HomeAssistant) -> Path:
    return db_stats.resolve_db_path(hass.config.config_dir, recorder_db_url(hass))


def generated_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(GENERATED_FILE))


async def async_write_yaml(hass: HomeAssistant) -> None:
    d = _data(hass)
    content = yaml_writer.render_yaml(d["options"], d["excluded_entities"], d["rescued_entities"], d["rules_text"])
    await hass.async_add_executor_job(yaml_writer.atomic_write, generated_path(hass), content)


async def async_persist(hass: HomeAssistant) -> None:
    """Save our storage and regenerate the YAML file (restart needed for recorder to apply it)."""
    await async_save(hass)
    await async_write_yaml(hass)
    hass.data[DOMAIN]["pending_restart"] = True


async def async_analyze(hass: HomeAssistant) -> dict[str, Any]:
    path = db_path(hass)
    try:
        stats = await hass.async_add_executor_job(db_stats.analyze, path)
    except Exception as err:  # noqa: BLE001
        stats = {"entity_counts": {}, "total_records": 0, "db_path": str(path), "db_size_bytes": 0, "generated_at": None, "error": str(err)}
    _data(hass)["stats"] = stats
    await async_save(hass)
    return stats


def known_entity_ids(hass: HomeAssistant) -> set[str]:
    reg = er.async_get(hass)
    return set(reg.entities) | {s.entity_id for s in hass.states.async_all()}


def build_tree(hass: HomeAssistant) -> list[dict[str, Any]]:
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    seen: dict[str, dict[str, Any]] = {}
    for e in ent_reg.entities.values():
        seen[e.entity_id] = {
            "entity_id": e.entity_id,
            "name": e.name or e.original_name or e.entity_id,
            "device_id": e.device_id,
            "platform": e.platform,
        }
    for s in hass.states.async_all():  # entities without registry entry
        seen.setdefault(
            s.entity_id,
            {"entity_id": s.entity_id, "name": s.attributes.get("friendly_name") or s.entity_id, "device_id": None, "platform": ""},
        )
    # Iterating the registry yields DeviceEntry objects on current HA (device ids on older versions);
    # async_get_devices() without filters does not return all devices.
    all_devices = list(dev_reg.devices)
    if all_devices and isinstance(all_devices[0], str):
        all_devices = [dev_reg.devices[i] for i in all_devices]
    devices = [{"id": d.id, "name": d.name_by_user or d.name} for d in all_devices]
    stats = _data(hass).get("stats") or {}
    return tree.build_tree(devices, list(seen.values()), set(_data(hass)["excluded_entities"]), stats.get("entity_counts", {}), stats.get("total_records"))
