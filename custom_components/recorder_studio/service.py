"""Glue between the pure core and a running Home Assistant."""
from __future__ import annotations

import logging
from pathlib import Path
import shutil
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import ATTR_REFRESH_SECONDS, DOMAIN, GENERATED_FILE
from .core import alerts, db_stats, history, suggestions, tree, yaml_writer
from .live import async_apply_live
from .storage import async_save

ALERT_IDS = ("disk_low", "disk_filling", "db_growth")
LEARN_MORE = "https://github.com/r3mcos3/recorder-studio#alerts"

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


async def async_persist(hass: HomeAssistant) -> dict[str, Any]:
    """Save our storage, regenerate the YAML file and apply it to the running recorder where possible.

    Only what the recorder cannot change while running (database URL, commit interval, or a configuration.yaml that
    does not include our file yet) still needs a restart.
    """
    await async_save(hass)
    await async_write_yaml(hass)
    return await async_apply_and_track(hass)


async def async_apply_and_track(hass: HomeAssistant) -> dict[str, Any]:
    result = await async_apply_live(hass)
    hass.data[DOMAIN]["pending_restart"] = bool(result["restart"])
    hass.data[DOMAIN]["live"] = result
    return result


async def async_analyze(hass: HomeAssistant, full: bool = True) -> dict[str, Any]:
    path = db_path(hass)
    d = _data(hass)
    previous = d.get("stats") or {}
    now = time.time()
    # The per-entity attribute sizes are expensive; measure them at most once per ATTR_REFRESH_SECONDS.
    want_attrs = full and now - float(previous.get("attr_tried") or 0) > ATTR_REFRESH_SECONDS
    save = full
    try:
        stats = await hass.async_add_executor_job(db_stats.analyze, path, full, want_attrs)
        if full:
            stats["full_at"] = stats["generated_at"]
            stats["attr_tried"] = now if want_attrs else previous.get("attr_tried")
            if stats.get("attr_bytes") is None:  # not measured this time (or aborted): keep the last result
                stats["attr_bytes"] = previous.get("attr_bytes")
        else:  # light run: keep the expensive numbers from the last full analysis
            for key in ("tables", "free_bytes", "full_at", "attr_bytes", "attr_tried"):
                stats[key] = previous.get(key)
            stats["tables"] = stats["tables"] or []
            stats["free_bytes"] = stats["free_bytes"] or 0
        d["history"], new_day = history.record_snapshot(
            d.get("history") or [], dt_util.now().date().isoformat(), stats["db_size_bytes"], stats["total_records"], stats.get("recent_total", 0)
        )
        save = save or new_day
    except Exception as err:  # noqa: BLE001
        stats = {"entity_counts": {}, "total_records": 0, "db_path": str(path), "db_size_bytes": 0, "generated_at": None, "error": str(err)}
    d["stats"] = stats
    if save:  # light runs happen every few seconds; do not rewrite the storage file each time
        await async_save(hass)
    return stats


def known_entity_ids(hass: HomeAssistant) -> set[str]:
    reg = er.async_get(hass)
    return set(reg.entities) | {s.entity_id for s in hass.states.async_all()}


def _entity_rows(hass: HomeAssistant) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Every known entity with the registry details the tree and the suggestions need, plus device names."""
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    seen: dict[str, dict[str, Any]] = {}
    for e in ent_reg.entities.values():
        state = hass.states.get(e.entity_id)
        seen[e.entity_id] = {
            "entity_id": e.entity_id,
            "name": e.name or e.original_name or e.entity_id,
            "device_id": e.device_id,
            "platform": e.platform,
            "category": getattr(e.entity_category, "value", e.entity_category),
            "device_class": e.device_class or e.original_device_class,
            "state_class": state.attributes.get("state_class") if state else None,
        }
    for s in hass.states.async_all():  # entities without registry entry
        seen.setdefault(
            s.entity_id,
            {
                "entity_id": s.entity_id,
                "name": s.attributes.get("friendly_name") or s.entity_id,
                "device_id": None,
                "platform": "",
                "category": None,
                "device_class": s.attributes.get("device_class"),
                "state_class": s.attributes.get("state_class"),
            },
        )
    # Iterating the registry yields DeviceEntry objects on current HA (device ids on older versions);
    # async_get_devices() without filters does not return all devices.
    all_devices = list(dev_reg.devices)
    if all_devices and isinstance(all_devices[0], str):
        all_devices = [dev_reg.devices[i] for i in all_devices]
    names = {d.id: (d.name_by_user or d.name or "") for d in all_devices}
    return list(seen.values()), names


def entity_sizes(hass: HomeAssistant) -> dict[str, int]:
    return db_stats.estimate_entity_bytes(_data(hass).get("stats") or {})


def build_tree(hass: HomeAssistant) -> list[dict[str, Any]]:
    rows, names = _entity_rows(hass)
    devices = [{"id": i, "name": n} for i, n in names.items()]
    stats = _data(hass).get("stats") or {}
    return tree.build_tree(
        devices, rows, set(_data(hass)["excluded_entities"]), stats.get("entity_counts", {}), stats.get("total_records"), entity_sizes(hass)
    )


def build_suggestions(hass: HomeAssistant) -> dict[str, Any]:
    d = _data(hass)
    stats = d.get("stats") or {}
    if not stats.get("entity_counts"):
        return {"items": [], "total_found": 0, "save_bytes": 0, "save_percent": 0.0, "dismissed": len(d["dismissed"])}
    rows, names = _entity_rows(hass)
    for r in rows:
        r["device"] = names.get(r.get("device_id"), "")
    return suggestions.suggest(rows, stats, entity_sizes(hass), set(d["excluded_entities"]), set(d["dismissed"]))


async def async_disk(hass: HomeAssistant) -> tuple[int | None, int | None]:
    """(total, free) bytes of the disk the database lives on."""

    def _usage() -> tuple[int | None, int | None]:
        try:
            u = shutil.disk_usage(db_path(hass).parent)
            return u.total, u.free
        except OSError:
            return None, None

    return await hass.async_add_executor_job(_usage)


async def async_growth(hass: HomeAssistant) -> dict[str, Any]:
    d = _data(hass)
    stats = d.get("stats") or {}
    total, free = await async_disk(hass)
    info = history.trend(d.get("history") or [], free)
    info.update(
        recent_total=int(stats.get("recent_total") or 0),
        bytes_per_day=db_stats.estimate_daily_bytes(stats, entity_sizes(hass)),
        disk_total=total,
        disk_free=free,
        snapshots=len(d.get("history") or []),
    )
    return info


async def async_check_alerts(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Create or clear the Repairs issues for low disk space and fast growth."""
    d = _data(hass)
    stats = d.get("stats") or {}
    if stats.get("error") or not stats.get("db_size_bytes"):
        return []
    total, free = await async_disk(hass)
    issues = alerts.evaluate(d["alerts"], db_size=stats["db_size_bytes"], disk_total=total, disk_free=free, history=d.get("history") or [])
    active = {i["id"] for i in issues}
    for issue in issues:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue["id"],
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR if issue["severity"] == "error" else ir.IssueSeverity.WARNING,
            translation_key=issue["id"],
            translation_placeholders=issue["placeholders"],
            learn_more_url=LEARN_MORE,
        )
    for issue_id in ALERT_IDS:
        if issue_id not in active:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    hass.data[DOMAIN]["active_alerts"] = sorted(active)
    return issues


async def async_backup_status(hass: HomeAssistant) -> dict[str, Any]:
    """Age of the newest Home Assistant backup, or {"known": False} when it cannot be determined."""
    try:
        from homeassistant.components.backup import async_get_manager

        manager = async_get_manager(hass)
        backups, _errors = await manager.async_get_backups()
        dates = [b.date for b in backups.values()]
    except Exception:  # noqa: BLE001 - backup integration missing or API changed: stay quiet, never block
        return {"known": False}
    return {"known": True, **alerts.backup_age(dates)}
