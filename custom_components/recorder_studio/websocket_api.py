"""Admin-only websocket API used by the panel."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from . import service
from .const import CONFIG_FILE, DOMAIN, GENERATED_FILE, LEGACY_FILE, READ_ONLY_MODE, VERSION
from .core import db_stats, migration
from .core.rules import parse_manual_rules
from .storage import async_save

T = f"{DOMAIN}/"


def _d(hass: HomeAssistant) -> dict:
    return hass.data[DOMAIN]["data"]


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


async def _config_info(hass: HomeAssistant) -> dict[str, Any]:
    text = await hass.async_add_executor_job(_read, Path(hass.config.path(CONFIG_FILE))) or ""
    info = migration.inspect_configuration(text, GENERATED_FILE)
    legacy = await hass.async_add_executor_job(_read, Path(hass.config.path(LEGACY_FILE)))
    info["legacy_file_present"] = legacy is not None
    return info


def _summary(hass: HomeAssistant) -> dict[str, Any] | None:
    stats = _d(hass).get("stats")
    if not stats:
        return None
    return db_stats.summarize(stats, _d(hass)["excluded_entities"], service.known_entity_ids(hass))


def _need_stats(hass: HomeAssistant) -> dict[str, Any]:
    return _d(hass).get("stats") or {"entity_counts": {}, "total_records": 0, "db_size_bytes": 0}


@callback
def async_register(hass: HomeAssistant) -> None:
    for cmd in (
        ws_get_state, ws_set_recorded, ws_save_settings, ws_analyze, ws_preview_purge, ws_purge,
        ws_repack, ws_restart, ws_remove_orphans, ws_migration_sources, ws_migration_preview, ws_migration_import,
        ws_save_alerts, ws_dismiss_suggestions, ws_backup_status,
    ):
        websocket_api.async_register_command(hass, cmd)


@websocket_api.websocket_command({vol.Required("type"): T + "get_state"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_get_state(hass, connection, msg):
    d = _d(hass)
    files = await hass.async_add_executor_job(db_stats.file_sizes, service.db_path(hass))
    connection.send_result(
        msg["id"],
        {
            "version": VERSION,
            "db_files": files,
            "sqlite": service.is_sqlite(hass),
            "options": d["options"],
            "rules_text": d["rules_text"],
            "tree": service.build_tree(hass),
            "summary": _summary(hass),
            "suggestions": service.build_suggestions(hass),
            "growth": await service.async_growth(hass),
            "alerts": {**d["alerts"], "active": hass.data[DOMAIN].get("active_alerts", [])},
            "config": await _config_info(hass),
            "pending_restart": hass.data[DOMAIN].get("pending_restart", False),
            "live": hass.data[DOMAIN].get("live"),
            "yaml_file": GENERATED_FILE,
            "read_only": READ_ONLY_MODE,
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): T + "set_recorded", vol.Required("entity_ids"): [str], vol.Required("recorded"): bool}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_recorded(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    d = _d(hass)
    current = set(d["excluded_entities"])
    ids = {e.strip() for e in msg["entity_ids"] if e.strip()}
    current = current - ids if msg["recorded"] else current | ids
    d["excluded_entities"] = sorted(current)
    # rescued entities only matter while excluded by a domain/glob rule; keep it consistent
    d["rescued_entities"] = sorted(set(d["rescued_entities"]) - ids) if not msg["recorded"] else d["rescued_entities"]
    live = await service.async_persist(hass)
    connection.send_result(msg["id"], {"excluded": len(d["excluded_entities"]), "summary": _summary(hass), "live": live})


@websocket_api.websocket_command(
    {
        vol.Required("type"): T + "save_settings",
        vol.Required("purge_keep_days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3650)),
        vol.Required("auto_purge"): bool,
        vol.Required("auto_repack"): bool,
        vol.Required("commit_interval"): vol.All(vol.Coerce(int), vol.Range(min=0, max=86400)),
        vol.Required("rules_text"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_settings(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    try:
        parse_manual_rules(msg["rules_text"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_rules", str(err))
        return
    d = _d(hass)
    for key in ("purge_keep_days", "auto_purge", "auto_repack", "commit_interval"):
        d["options"][key] = msg[key]
    d["rules_text"] = msg["rules_text"]
    live = await service.async_persist(hass)
    connection.send_result(msg["id"], {"ok": True, "live": live})


@websocket_api.websocket_command({vol.Required("type"): T + "analyze", vol.Optional("light", default=False): bool})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_analyze(hass, connection, msg):
    await service.async_analyze(hass, full=not msg["light"])
    connection.send_result(msg["id"], {"summary": _summary(hass), "tree": service.build_tree(hass)})


def _purge_targets(hass: HomeAssistant, msg: dict) -> list[str]:
    if msg["kind"] == "excluded":
        return list(_d(hass)["excluded_entities"])
    return sorted(set(msg.get("entity_ids", [])))


_PURGE_SCHEMA = {
    vol.Required("kind"): vol.In(["retention", "excluded", "entities"]),
    vol.Optional("entity_ids"): [str],
}


@websocket_api.websocket_command({vol.Required("type"): T + "preview_purge", **_PURGE_SCHEMA})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_preview_purge(hass, connection, msg):
    if msg["kind"] == "retention":
        connection.send_result(msg["id"], {"keep_days": _d(hass)["options"]["purge_keep_days"]})
        return
    ids = _purge_targets(hass, msg)
    connection.send_result(msg["id"], db_stats.estimate_impact(_need_stats(hass), ids))


@websocket_api.websocket_command(
    {vol.Required("type"): T + "purge", vol.Required("confirm"): True, vol.Optional("repack", default=False): bool, **_PURGE_SCHEMA}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_purge(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    if msg["kind"] == "retention":
        await hass.services.async_call(
            "recorder", "purge", {"keep_days": _d(hass)["options"]["purge_keep_days"], "repack": msg["repack"]}, blocking=True
        )
        connection.send_result(msg["id"], {"queued": True})
        return
    ids = _purge_targets(hass, msg)
    if not ids:
        connection.send_error(msg["id"], "nothing_to_purge", "No entities selected.")
        return
    await hass.services.async_call("recorder", "purge_entities", {"entity_id": ids, "keep_days": 0}, blocking=True)
    if msg["repack"]:
        await hass.services.async_call("recorder", "purge", {"keep_days": _d(hass)["options"]["purge_keep_days"], "repack": True})
    connection.send_result(msg["id"], {"queued": True, "entities": len(ids)})


@websocket_api.websocket_command({vol.Required("type"): T + "repack", vol.Required("confirm"): True})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_repack(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    await hass.services.async_call("recorder", "purge", {"keep_days": _d(hass)["options"]["purge_keep_days"], "repack": True})
    connection.send_result(msg["id"], {"queued": True})


@websocket_api.websocket_command({vol.Required("type"): T + "restart", vol.Required("confirm"): True})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_restart(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    # homeassistant.restart validates the config first and refuses on errors.
    try:
        await hass.services.async_call("homeassistant", "restart", {}, blocking=False)
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "restart_failed", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): T + "remove_orphans"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_remove_orphans(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    s = _summary(hass)
    orphans = set(s["orphan_exclusions"]) if s else set()
    d = _d(hass)
    d["excluded_entities"] = sorted(set(d["excluded_entities"]) - orphans)
    d["rescued_entities"] = sorted(set(d["rescued_entities"]) - orphans)
    live = await service.async_persist(hass)
    connection.send_result(msg["id"], {"removed": len(orphans), "summary": _summary(hass), "live": live})


@websocket_api.websocket_command(
    {
        vol.Required("type"): T + "save_alerts",
        vol.Required("enabled"): bool,
        vol.Required("free_percent"): vol.All(vol.Coerce(int), vol.Range(min=1, max=90)),
        vol.Required("growth_percent"): vol.All(vol.Coerce(int), vol.Range(min=5, max=1000)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_alerts(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    d = _d(hass)
    d["alerts"] = {"enabled": msg["enabled"], "free_percent": msg["free_percent"], "growth_percent": msg["growth_percent"]}
    await async_save(hass)
    await service.async_check_alerts(hass)  # applies immediately, no restart needed
    connection.send_result(msg["id"], {"active": hass.data[DOMAIN].get("active_alerts", [])})


@websocket_api.websocket_command(
    {vol.Required("type"): T + "dismiss_suggestions", vol.Optional("entity_ids", default=[]): [str], vol.Optional("reset", default=False): bool}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_dismiss_suggestions(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    d = _d(hass)
    d["dismissed"] = [] if msg["reset"] else sorted(set(d["dismissed"]) | {e.strip() for e in msg["entity_ids"] if e.strip()})
    await async_save(hass)
    connection.send_result(msg["id"], {"suggestions": service.build_suggestions(hass)})


@websocket_api.websocket_command({vol.Required("type"): T + "backup_status"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_backup_status(hass, connection, msg):
    connection.send_result(msg["id"], await service.async_backup_status(hass))


# ---- migration -------------------------------------------------------------
_SOURCE = {
    vol.Required("source"): vol.All(str, vol.Match(r"^(configuration|legacy|paste|file:.{1,200})$")),
    vol.Optional("text"): vol.All(str, vol.Length(max=200_000)),
}


def _load_source(config_dir: Path, source: str, text: str | None, config_text: str) -> tuple[dict[str, Any] | None, str]:
    """Return (parsed import, label) for one migration source. Raises ValueError for bad input."""
    if source == "configuration":
        return migration.inspect_configuration(config_text, GENERATED_FILE).get("imported"), CONFIG_FILE
    if source == "paste":
        return migration.parse_text(text or ""), "pasted YAML"
    rel = LEGACY_FILE if source == "legacy" else source[len("file:"):]
    path = migration.safe_config_path(config_dir, rel)
    return migration.parse_text(path.read_text(encoding="utf-8")), rel


async def _load_import(hass: HomeAssistant, msg: dict) -> tuple[dict[str, Any] | None, str]:
    config_dir = Path(hass.config.config_dir)
    config_text = await hass.async_add_executor_job(_read, config_dir / CONFIG_FILE) or ""
    return await hass.async_add_executor_job(_load_source, config_dir, msg["source"], msg.get("text"), config_text)


@websocket_api.websocket_command({vol.Required("type"): T + "migration_sources"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_migration_sources(hass, connection, msg):
    config_dir = Path(hass.config.config_dir)
    config_text = await hass.async_add_executor_job(_read, config_dir / CONFIG_FILE) or ""
    sources = await hass.async_add_executor_job(migration.discover_sources, config_dir, GENERATED_FILE, config_text, LEGACY_FILE)
    connection.send_result(msg["id"], {"sources": sources})


@websocket_api.websocket_command({vol.Required("type"): T + "migration_preview", **_SOURCE})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_migration_preview(hass, connection, msg):
    try:
        imp, label = await _load_import(hass, msg)
    except (ValueError, OSError) as err:
        connection.send_error(msg["id"], "nothing_to_import", str(err))
        return
    if imp is None:
        connection.send_error(msg["id"], "nothing_to_import", "No recorder configuration found at that source.")
        return
    cfg = await _config_info(hass)
    text = await hass.async_add_executor_job(_read, Path(hass.config.path(CONFIG_FILE))) or ""
    after = migration.activate(text, GENERATED_FILE)
    note = ""
    if msg["source"].startswith("file:") and label != str(cfg.get("include_target", "")).strip().strip("'\""):
        note = (
            f"{label} is not changed by Recorder Studio. After activation, remove its recorder: section yourself, "
            "otherwise Home Assistant reports a duplicate recorder configuration."
        )
    connection.send_result(
        msg["id"],
        {
            "import": {**imp, "excluded_count": len(imp["excluded_entities"])},
            "label": label,
            "note": note,
            "config_state": cfg["state"],
            "diff": migration.diff_text(text, after, CONFIG_FILE) if cfg["state"] != "active" else "",
            "current_excluded": len(_d(hass)["excluded_entities"]),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): T + "migration_import", vol.Required("confirm"): True, vol.Optional("merge", default=False): bool, **_SOURCE}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_migration_import(hass, connection, msg):
    if READ_ONLY_MODE:
        connection.send_error(msg["id"], "read_only", "Recorder Studio is in read-only mode: write actions are disabled.")
        return
    try:
        imp, _label = await _load_import(hass, msg)
    except (ValueError, OSError) as err:
        connection.send_error(msg["id"], "nothing_to_import", str(err))
        return
    if imp is None:
        connection.send_error(msg["id"], "nothing_to_import", "No recorder configuration found at that source.")
        return
    d = _d(hass)
    warnings = list(imp["warnings"])
    if msg["merge"]:
        merged, extra = migration.merge_import(
            {"options": d["options"], "excluded_entities": d["excluded_entities"], "rescued_entities": d["rescued_entities"], "rules_text": d["rules_text"]},
            imp,
        )
        d["options"].update(merged["options"])
        d["excluded_entities"], d["rescued_entities"], d["rules_text"] = merged["excluded_entities"], merged["rescued_entities"], merged["rules_text"]
        warnings += extra
    else:
        d["options"].update(imp["options"])
        d["excluded_entities"] = imp["excluded_entities"]
        d["rescued_entities"] = imp["rescued_entities"]
        d["rules_text"] = imp["rules_text"]
    live = await service.async_persist(hass)
    connection.send_result(msg["id"], {"warnings": warnings, "excluded": len(d["excluded_entities"]), "live": live})
