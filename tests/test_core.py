import sqlite3

import pytest
import yaml

from core import db_stats, migration, tree, yaml_writer
from core.rules import parse_manual_rules

OPTS = {"purge_keep_days": 14, "auto_purge": True, "auto_repack": False, "commit_interval": 5}


# ---- rules -----------------------------------------------------------------
def test_rules_roundtrip_and_cleanup():
    r = parse_manual_rules("exclude:\n  domains: [b, a, a, ' ']\n  entity_globs: ['*_uptime']\n")
    assert r == {"exclude": {"domains": ["a", "b"], "entity_globs": ["*_uptime"]}}


@pytest.mark.parametrize(
    "text",
    ["exclude:\n  entities: [sensor.x]", "foo: {}", "exclude: [a]", "exclude:\n  domains: a", "- x", "a: [", "include:\n  event_types: [x]"],
)
def test_rules_rejects(text):
    with pytest.raises(ValueError):
        parse_manual_rules(text)


def test_rules_empty():
    assert parse_manual_rules("") == {}
    assert parse_manual_rules("# nothing\n") == {}


# ---- yaml writer -----------------------------------------------------------
def test_render_basic_is_valid_yaml():
    out = yaml_writer.render_yaml(OPTS, ["sensor.b", "sensor.a", "sensor.a"], [])
    data = yaml.safe_load(out)
    assert data["purge_keep_days"] == 14 and data["auto_repack"] is False
    assert data["exclude"] == {"entities": ["sensor.a", "sensor.b"]}
    assert "include" not in data


def test_render_empty_exclude():
    assert yaml.safe_load(yaml_writer.render_yaml(OPTS, [], []))["exclude"] == {}


def test_render_glob_with_star_is_quoted():
    out = yaml_writer.render_yaml(OPTS, [], [], "exclude:\n  entity_globs: ['*_uptime']")
    assert yaml.safe_load(out)["exclude"]["entity_globs"] == ["*_uptime"]


def test_rescued_only_with_filter():
    # without a domain/glob filter include.entities would become an allowlist -> must be omitted
    assert "include" not in yaml.safe_load(yaml_writer.render_yaml(OPTS, [], ["sensor.keep"]))
    out = yaml.safe_load(yaml_writer.render_yaml(OPTS, [], ["sensor.keep"], "exclude:\n  domains: [sensor]"))
    assert out["include"] == {"entities": ["sensor.keep"]}


def test_invalid_rules_never_written():
    out = yaml.safe_load(yaml_writer.render_yaml(OPTS, ["sensor.a"], [], "exclude:\n  entities: [x]"))
    assert out["exclude"] == {"entities": ["sensor.a"]}


def test_atomic_write(tmp_path):
    p = tmp_path / "sub" / "r.yaml"
    yaml_writer.atomic_write(p, "a: 1\n")
    yaml_writer.atomic_write(p, "a: 2\n")
    assert p.read_text() == "a: 2\n"
    assert [f.name for f in p.parent.iterdir()] == ["r.yaml"]  # no temp leftovers


# ---- db stats --------------------------------------------------------------
def test_resolve_db_path():
    assert str(db_stats.resolve_db_path("/cfg", None)) == "/cfg/home-assistant_v2.db"
    assert str(db_stats.resolve_db_path("/cfg", "sqlite:///x.db")) == "/cfg/x.db"
    assert str(db_stats.resolve_db_path("/cfg", "sqlite:////abs/x.db?timeout=5")) == "/abs/x.db"
    assert str(db_stats.resolve_db_path("/cfg", "mysql://u@h/db")) == "/cfg/home-assistant_v2.db"


def test_analyze_counts_and_size(synthetic_db):
    s = db_stats.analyze(synthetic_db)
    assert s["total_records"] == 100
    assert list(s["entity_counts"])[0] == "sensor.a"  # sorted by count desc
    assert s["db_size_bytes"] > 0


def test_analyze_is_read_only(synthetic_db):
    db_stats.analyze(synthetic_db)
    conn = sqlite3.connect(f"file:{synthetic_db}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM states")
    conn.close()
    assert db_stats.analyze(synthetic_db)["total_records"] == 100


def test_analyze_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        db_stats.analyze(tmp_path / "nope.db")


def test_analyze_legacy_schema(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE states (state_id INTEGER PRIMARY KEY, entity_id TEXT)")
    c.executemany("INSERT INTO states (entity_id) VALUES (?)", [("a.b",)] * 3)
    c.commit(); c.close()
    assert db_stats.analyze(p)["entity_counts"] == {"a.b": 3}


def test_summarize_and_orphans(synthetic_db):
    stats = db_stats.analyze(synthetic_db)
    known = {"sensor.a", "sensor.b_uptime", "light.kitchen"}
    s = db_stats.summarize(stats, ["sensor.b_uptime", "sensor.ghost", "sensor.gone"], known)
    assert s["obsolete_records"] == 35 and s["current_records"] == 65
    assert s["excluded_with_records"] == 2
    # sensor.gone has records but no longer exists -> not an orphan until its records are gone? it IS in counts
    assert s["orphan_exclusions"] == ["sensor.ghost"]


def test_estimate_impact(synthetic_db):
    stats = db_stats.analyze(synthetic_db)
    imp = db_stats.estimate_impact(stats, ["sensor.a", "light.kitchen"])
    assert imp["records"] == 65 and imp["entities"] == 2
    assert 0 < imp["approx_bytes"] <= stats["db_size_bytes"]


# ---- tree ------------------------------------------------------------------
def test_tree_grouping_and_order():
    devs = [{"id": "d1", "name": "Zeta"}, {"id": "d2", "name": "alpha"}]
    ents = [
        {"entity_id": "sensor.z", "device_id": "d1", "platform": "mqtt"},
        {"entity_id": "light.free"},
        {"entity_id": "sensor.a", "device_id": "d2", "name": "A"},
    ]
    t = tree.build_tree(devs, ents, {"sensor.z"}, {"sensor.z": 7})
    assert [d["name"] for d in t] == ["alpha", "Zeta", "Entities without device"]
    zeta = t[1]
    assert zeta["excluded_count"] == 1 and zeta["records"] == 7
    assert zeta["entities"][0]["recorded"] is False


# ---- migration -------------------------------------------------------------
CFG = """default_config:

# my recorder
recorder:
  purge_keep_days: 7
  db_url: !secret db
  exclude:
    domains:
      - updater
    entities:
      - sensor.x
  include:
    entities:
      - sensor.keep

  weird_option: 1

automation: !include automations.yaml
"""


def test_inspect_inline():
    info = migration.inspect_configuration(CFG, "recorder_studio.yaml")
    assert info["state"] == "inline"
    imp = info["imported"]
    assert imp["options"]["purge_keep_days"] == 7
    assert imp["excluded_entities"] == ["sensor.x"]
    assert imp["rescued_entities"] == ["sensor.keep"]
    assert any("weird_option" in w for w in imp["warnings"])
    assert "automation:" not in info["block"]


def test_inspect_states():
    assert migration.inspect_configuration("a: 1\n", "f.yaml")["state"] == "absent"
    assert migration.inspect_configuration("recorder: !include f.yaml\n", "f.yaml")["state"] == "active"
    assert migration.inspect_configuration("recorder: !include o.yaml\n", "f.yaml")["state"] == "other_include"


def test_allowlist_include_warned():
    imp = migration.parse_recorder_config({"include": {"entities": ["sensor.a"]}})
    assert imp["rescued_entities"] == [] and imp["warnings"]


def test_activate_inline_replaces_and_preserves_rest():
    new = migration.activate(CFG, "recorder_studio.yaml")
    assert "recorder: !include recorder_studio.yaml" in new
    assert "# recorder:" in new and "#   purge_keep_days: 7" in new
    assert "automation: !include automations.yaml" in new
    assert "default_config:" in new
    # the resulting file still parses and has exactly one active recorder key
    data = yaml.load(new, Loader=migration._Loader)
    assert data["recorder"].startswith("!include recorder_studio.yaml")


def test_activate_when_absent_and_idempotent():
    new = migration.activate("a: 1\n", "f.yaml")
    assert new.endswith("recorder: !include f.yaml\n")
    assert migration.activate(new, "f.yaml") == new


def test_activate_other_include_is_replaced():
    assert migration.activate("recorder: !include gui_recorder.yaml\nx: 1\n", "recorder_studio.yaml") == (
        "recorder: !include recorder_studio.yaml\nx: 1\n"
    )


def test_diff():
    d = migration.diff_text("a\n", "b\n")
    assert "-a" in d and "+b" in d


def test_read_legacy_file_with_header_comments():
    text = "# managed\n\nauto_purge: true\npurge_keep_days: 14\nexclude:\n  entities:\n  - sensor.b\n  - sensor.a\n"
    imp = migration.read_legacy_file(text)
    assert imp["excluded_entities"] == ["sensor.a", "sensor.b"]
    assert imp["options"]["purge_keep_days"] == 14


def test_roundtrip_import_then_render():
    imp = migration.inspect_configuration(CFG, "x.yaml")["imported"]
    out = yaml.safe_load(
        yaml_writer.render_yaml({**OPTS, **imp["options"]}, imp["excluded_entities"], imp["rescued_entities"], imp["rules_text"])
    )
    assert out["exclude"]["entities"] == ["sensor.x"] and out["exclude"]["domains"] == ["updater"]
    assert out["include"] == {"entities": ["sensor.keep"]}


def test_tagged_db_url_not_imported():
    info = migration.inspect_configuration(CFG, "x.yaml")["imported"]
    assert "db_url" not in info["options"]
    assert any("db_url" in w for w in info["warnings"])


def test_all_write_commands_are_guarded():
    """Every websocket write handler must start with the READ_ONLY_MODE guard."""
    import re
    from pathlib import Path

    src = (Path(__file__).parent.parent / "custom_components/recorder_studio/websocket_api.py").read_text()
    writers = ["ws_set_recorded", "ws_save_settings", "ws_purge", "ws_repack", "ws_restart",
               "ws_remove_orphans", "ws_migration_import", "ws_migration_activate"]
    for name in writers:
        body = src.split(f"async def {name}(hass, connection, msg):\n", 1)[1][:200]
        assert "READ_ONLY_MODE" in body, name
    # read-only commands must stay usable
    for name in ["ws_get_state", "ws_analyze", "ws_preview_purge", "ws_migration_preview"]:
        body = src.split(f"async def {name}(hass, connection, msg):\n", 1)[1][:150]
        assert "READ_ONLY_MODE" not in body, name
