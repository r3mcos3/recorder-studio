from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.recorder_studio import service, websocket_api
from custom_components.recorder_studio.const import DOMAIN, VERSION

from .conftest import call


# ---- config flow -------------------------------------------------------------
async def test_config_flow_single_instance(hass, config_dir):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] == "form"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    assert r["type"] == "create_entry"
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert again["type"] == "abort" and again["reason"] == "single_instance_allowed"


# ---- websocket: state, analysis, permissions ---------------------------------
async def test_get_state_before_analysis(ws):
    res = await call(ws, "get_state")
    assert res["success"]
    r = res["result"]
    assert r["version"] == VERSION and r["summary"] is None and r["suggestions"]["items"] == []
    assert r["alerts"]["enabled"] is True and r["pending_restart"] is False


async def test_analyze_fills_summary_growth_and_history(hass, ws):
    res = await call(ws, "analyze")
    s = res["result"]["summary"]
    assert s["total_records"] == 100 and s["recent_total"] == 100
    assert s["top_entities"][0][0] == "sensor.wifi_rssi"
    state = (await call(ws, "get_state"))["result"]
    assert state["growth"]["snapshots"] == 1 and state["growth"]["disk_free"]
    light = await call(ws, "analyze", light=True)
    assert light["result"]["summary"]["total_records"] == 100


async def test_suggestions_come_from_registry_and_stats(hass, ws):
    reg = er.async_get(hass)
    reg.async_get_or_create("sensor", "test", "wifi", suggested_object_id="wifi_rssi", entity_category=er.EntityCategory.DIAGNOSTIC)
    await call(ws, "analyze", light=False)
    items = (await call(ws, "get_state"))["result"]["suggestions"]["items"]
    assert [i["entity_id"] for i in items] == ["sensor.wifi_rssi"] and items[0]["confidence"] == "high"
    dismissed = await call(ws, "dismiss_suggestions", entity_ids=["sensor.wifi_rssi"])
    assert dismissed["result"]["suggestions"]["items"] == []
    reset = await call(ws, "dismiss_suggestions", reset=True)
    assert len(reset["result"]["suggestions"]["items"]) == 1


async def test_non_admin_is_refused(hass, entry, hass_ws_client):
    user = await hass.auth.async_create_user("viewer", group_ids=["system-users"])
    token = await hass.auth.async_create_refresh_token(user, "https://example.com")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    res = await call(client, "get_state")
    assert not res["success"] and res["error"]["code"] == "unauthorized"


# ---- writes ------------------------------------------------------------------
async def test_set_recorded_writes_yaml_and_flags_restart(hass, ws, config_dir):
    res = await call(ws, "set_recorded", entity_ids=["sensor.wifi_rssi"], recorded=False)
    assert res["success"] and res["result"]["excluded"] == 1
    text = (config_dir / "recorder_studio.yaml").read_text()
    assert "sensor.wifi_rssi" in text
    assert (await call(ws, "get_state"))["result"]["pending_restart"] is True
    await call(ws, "set_recorded", entity_ids=["sensor.wifi_rssi"], recorded=True)
    assert "sensor.wifi_rssi" not in (config_dir / "recorder_studio.yaml").read_text()


async def test_read_only_mode_refuses_writes(hass, ws, config_dir):
    with patch.object(websocket_api, "READ_ONLY_MODE", True):
        for type_, payload in (
            ("set_recorded", {"entity_ids": ["sensor.a"], "recorded": False}),
            ("save_alerts", {"enabled": True, "free_percent": 10, "growth_percent": 25}),
            ("dismiss_suggestions", {"entity_ids": ["sensor.a"]}),
            ("purge", {"kind": "retention", "confirm": True}),
        ):
            res = await call(ws, type_, **payload)
            assert not res["success"] and res["error"]["code"] == "read_only", type_
    assert not (config_dir / "recorder_studio.yaml").exists()


async def test_purge_needs_confirm_and_calls_recorder_services(hass, ws):
    calls = async_mock_service(hass, "recorder", "purge_entities")
    refused = await call(ws, "purge", kind="entities", entity_ids=["sensor.wifi_rssi"])
    assert not refused["success"] and not calls  # no confirm: rejected by the schema
    ok = await call(ws, "purge", kind="entities", entity_ids=["sensor.wifi_rssi"], confirm=True)
    assert ok["success"] and calls[0].data == {"entity_id": ["sensor.wifi_rssi"], "keep_days": 0}
    empty = await call(ws, "purge", kind="entities", entity_ids=[], confirm=True)
    assert empty["error"]["code"] == "nothing_to_purge"


async def test_retention_purge_uses_configured_days(hass, ws):
    calls = async_mock_service(hass, "recorder", "purge")
    await call(ws, "save_settings", purge_keep_days=7, auto_purge=True, auto_repack=False, commit_interval=5, rules_text="")
    await call(ws, "purge", kind="retention", confirm=True)
    assert calls[0].data == {"keep_days": 7, "repack": False}


async def test_invalid_manual_rules_rejected(ws):
    res = await call(ws, "save_settings", purge_keep_days=7, auto_purge=True, auto_repack=False, commit_interval=5, rules_text="exclude:\n  entities: [a.b]")
    assert not res["success"] and res["error"]["code"] == "invalid_rules"


# ---- migration through the API -------------------------------------------------
async def test_migration_preview_import_and_activate(hass, ws, config_dir):
    (config_dir / "configuration.yaml").write_text("recorder:\n  exclude:\n    entities:\n      - sensor.old\n")
    sources = (await call(ws, "migration_sources"))["result"]["sources"]
    assert sources[0]["id"] == "configuration" and sources[0]["excluded"] == 1
    prev = await call(ws, "migration_preview", source="configuration")
    assert prev["result"]["import"]["excluded_count"] == 1 and "recorder_studio.yaml" in prev["result"]["diff"]
    imp = await call(ws, "migration_import", source="configuration", confirm=True)
    assert imp["result"]["excluded"] == 1
    act = await call(ws, "migration_activate", confirm=True)
    assert act["result"]["backup"].startswith("configuration.yaml.recorder_studio_backup_")
    assert "!include recorder_studio.yaml" in (config_dir / "configuration.yaml").read_text()


async def test_migration_rejects_path_escape(ws):
    res = await call(ws, "migration_preview", source="file:../../etc/passwd")
    assert not res["success"]


# ---- alerts ------------------------------------------------------------------
async def test_alerts_create_and_clear_repairs_issue(hass, ws):
    await call(ws, "analyze")
    reg = ir.async_get(hass)
    with patch.object(service, "async_disk", AsyncMock(return_value=(1000, 40))):
        saved = await call(ws, "save_alerts", enabled=True, free_percent=10, growth_percent=25)
    assert saved["result"]["active"] == ["disk_low"]
    issue = reg.async_get_issue(DOMAIN, "disk_low")
    assert issue and issue.translation_key == "disk_low" and issue.severity == ir.IssueSeverity.ERROR
    with patch.object(service, "async_disk", AsyncMock(return_value=(1000, 900))):
        await service.async_check_alerts(hass)
    assert reg.async_get_issue(DOMAIN, "disk_low") is None
    with patch.object(service, "async_disk", AsyncMock(return_value=(1000, 40))):
        off = await call(ws, "save_alerts", enabled=False, free_percent=10, growth_percent=25)
    assert off["result"]["active"] == [] and reg.async_get_issue(DOMAIN, "disk_low") is None


async def test_alert_settings_are_validated(ws):
    res = await call(ws, "save_alerts", enabled=True, free_percent=0, growth_percent=25)
    assert not res["success"]


async def test_background_check_records_history(hass, ws):
    assert hass.data[DOMAIN]["data"]["history"] == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=3))
    await hass.async_block_till_done()
    hist = hass.data[DOMAIN]["data"]["history"]
    assert len(hist) == 1 and hist[0]["records"] == 100


# ---- backup status -------------------------------------------------------------
async def test_backup_status_unknown_without_backup_integration(ws):
    assert (await call(ws, "backup_status"))["result"] == {"known": False}


async def test_backup_status_reads_newest_backup(hass, ws):
    recent = (dt_util.utcnow() - timedelta(hours=5)).isoformat()
    manager = MagicMock()
    manager.async_get_backups = AsyncMock(return_value=({"a": MagicMock(date=recent), "b": MagicMock(date="2020-01-01T00:00:00+00:00")}, {}))
    with patch("homeassistant.components.backup.async_get_manager", return_value=manager):
        res = (await call(ws, "backup_status"))["result"]
    assert res["known"] is True and res["count"] == 2 and 4.9 < res["age_hours"] < 5.1


async def test_backup_status_with_no_backups(hass, ws):
    manager = MagicMock()
    manager.async_get_backups = AsyncMock(return_value=({}, {}))
    with patch("homeassistant.components.backup.async_get_manager", return_value=manager):
        res = (await call(ws, "backup_status"))["result"]
    assert res == {"known": True, "last": None, "age_hours": None, "count": 0}
