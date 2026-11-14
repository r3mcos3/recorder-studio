// Fake `hass` object that mimics the recorder_studio websocket API with in-memory data.
// Used only by the standalone preview; never shipped to Home Assistant.
export function createMockHass() {
  const rnd = (() => { let s = 42; return () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296); })();
  const devSpec = [
    ["Living room presence sensor", "zha", [["binary_sensor", "occupancy"], ["sensor", "illuminance"], ["sensor", "target_distance_closest"], ["sensor", "uptime"], ["sensor", "linkquality"]]],
    ["Kitchen spots", "mqtt", [["light", "kitchen_spots"], ["sensor", "linkquality"], ["sensor", "uptime"], ["update", "firmware"]]],
    ["Smart meter", "dsmr", [["sensor", "power_consumption"], ["sensor", "power_production"], ["sensor", "gas_total"], ["sensor", "voltage_l1"], ["sensor", "uptime"]]],
    ["Garden outlet", "mqtt", [["switch", "garden_outlet"], ["sensor", "power"], ["sensor", "energy"], ["sensor", "uptime"]]],
    ["Hallway motion", "zha", [["binary_sensor", "motion"], ["sensor", "battery"], ["sensor", "temperature"], ["sensor", "linkquality"]]],
    ["Heat pump", "modbus", [["climate", "heat_pump"], ["sensor", "flow_temp"], ["sensor", "return_temp"], ["sensor", "compressor_freq"], ["sensor", "uptime"]]],
    ["Doorbell G4", "unifiprotect", [["binary_sensor", "doorbell"], ["camera", "doorbell"], ["sensor", "uptime"], ["sensor", "wifi_signal"]]],
    ["Roller shutter back", "mqtt", [["cover", "shutter_back"], ["sensor", "uptime"], ["sensor", "linkquality"]]],
    ["NAS", "synology_dsm", [["sensor", "cpu_utilization"], ["sensor", "memory_utilization"], ["sensor", "uptime"], ["sensor", "volume_used"]]],
    ["Printer Canon TS3700", "ipp", [["sensor", "availability"], ["sensor", "black_ink"], ["sensor", "color_ink"]]],
  ];
  const excludedInit = new Set(["sensor.living_room_uptime", "sensor.kitchen_uptime", "sensor.smart_meter_uptime", "sensor.garden_outlet_uptime", "sensor.nas_uptime", "sensor.doorbell_uptime",
    "sensor.living_room_target_distance_closest", "sensor.printer_availability", "sensor.old_vacuum_battery", "sensor.removed_zigbee_plug_power", "binary_sensor.retired_window"]);
  const tree = devSpec.map(([name, platform, ents], i) => {
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/_+$/, "");
    const short = { "living_room_presence_sensor": "living_room", "kitchen_spots": "kitchen", "heat_pump": "heat_pump", "doorbell_g4": "doorbell", "roller_shutter_back": "shutter_back", "printer_canon_ts3700": "printer", "hallway_motion": "hallway" }[slug] || slug;
    return {
      device_id: `dev${i}`, name,
      entities: ents.map(([domain, key]) => {
        const id = key.startsWith(short) || ["power_consumption","power_production","gas_total","voltage_l1","cpu_utilization","memory_utilization","volume_used"].includes(key) ? `${domain}.${key}` : `${domain}.${short}_${key}`;
        const fixed = id.replace(`${domain}.${short}_${short}`, `${domain}.${short}`);
        const noisy = /uptime|linkquality|power|temp|distance|illuminance|voltage|cpu|memory|wifi|compressor/.test(key);
        return { entity_id: fixed, name: key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()), domain, platform, recorded: !excludedInit.has(fixed), records: Math.round((noisy ? 40000 : 3000) * (0.2 + rnd())) };
      }),
    };
  });
  const orphanIds = ["sensor.old_vacuum_battery", "sensor.removed_zigbee_plug_power", "binary_sensor.retired_window"];
  let tick = 0;
  const S = {
    sqlite: true, version: "0.1.0", yaml_file: "recorder_studio.yaml", pending_restart: false,
    options: { purge_keep_days: 14, auto_purge: true, auto_repack: true, commit_interval: 5 },
    rules_text: "exclude:\n  entity_globs:\n    - sensor.*_uptime\n",
    analysed: false, tree, orphans: orphanIds, configState: "inline", importedFrom: null,
  };
  const all = () => S.tree.flatMap((d) => d.entities);
  const excludedAll = () => [...all().filter((e) => !e.recorded).map((e) => e.entity_id), ...S.orphans];
  const summary = () => {
    if (!S.analysed) return null;
    const ents = all(); const total = ents.reduce((a, e) => a + e.records, 0);
    const obsolete = ents.filter((e) => !e.recorded).reduce((a, e) => a + e.records, 0);
    return { total_records: total, current_records: total - obsolete, obsolete_records: obsolete, excluded_with_records: ents.filter((e) => !e.recorded && e.records).length,
      orphan_exclusions: S.orphans, entity_count: ents.length, db_size_bytes: total * 118 + 12e6, db_path: "/config/home-assistant_v2.db", generated_at: new Date().toISOString(), error: null,
      top_entities: ents.map((e) => [e.entity_id, e.records]).sort((a, b) => b[1] - a[1]).slice(0, 12) };
  };
  const view = () => ({
    version: S.version, sqlite: S.sqlite, options: S.options, rules_text: S.rules_text, yaml_file: S.yaml_file, pending_restart: S.pending_restart, summary: summary(),
    tree: S.tree.map((d) => ({ ...d, entities: d.entities.map((e) => ({ ...e, records: S.analysed ? e.records : 0 })), records: 0, excluded_count: 0 })),
    config: { state: S.configState, include_target: "gui_recorder.yaml", legacy_file_present: true, imported: S.configState === "inline" ? { excluded_entities: [] } : null },
  });
  const impact = (ids) => { const m = new Set(ids); const r = all().filter((e) => m.has(e.entity_id)).reduce((a, e) => a + e.records, 0); return { entities: ids.length, records: r, approx_bytes: r * 118 }; };
  const diff = `--- configuration.yaml (now)\n+++ configuration.yaml (after)\n@@ -28,6 +28,7 @@\n-recorder: !include gui_recorder.yaml\n+# [recorder_studio] previous recorder config, replaced by the include below:\n+# recorder: !include gui_recorder.yaml\n+recorder: !include recorder_studio.yaml\n`;
  const handlers = {
    get_state: () => view(),
    set_recorded: ({ entity_ids, recorded }) => { const m = new Set(entity_ids); all().forEach((e) => m.has(e.entity_id) && (e.recorded = recorded)); S.pending_restart = true; return { excluded: excludedAll().length }; },
    save_settings: (m) => { Object.assign(S.options, { purge_keep_days: m.purge_keep_days, auto_purge: m.auto_purge, auto_repack: m.auto_repack, commit_interval: m.commit_interval }); S.rules_text = m.rules_text; S.pending_restart = true; return { ok: true }; },
    analyze: () => { S.analysed = true; return {}; },
    preview_purge: ({ kind, entity_ids }) => (kind === "excluded" ? impact(all().filter((e) => !e.recorded).map((e) => e.entity_id)) : impact(entity_ids || [])),
    purge: ({ kind, entity_ids }) => { const ids = new Set(kind === "excluded" ? all().filter((e) => !e.recorded).map((e) => e.entity_id) : entity_ids || []); all().forEach((e) => ids.has(e.entity_id) && (e.records = 0)); if (kind === "retention") all().forEach((e) => (e.records = Math.round(e.records * 0.4))); return { queued: true }; },
    repack: () => ({ queued: true }), restart: () => { S.pending_restart = false; return { ok: true }; },
    remove_orphans: () => { const n = S.orphans.length; S.orphans = []; S.pending_restart = true; return { removed: n }; },
    migration_preview: ({ source }) => ({ import: { excluded_count: source === "legacy" ? 46 : 23, excluded_entities: [], warnings: source === "legacy" ? [] : ["Option 'db_max_retries' is not supported and was left out.", "'db_url' uses a YAML tag (!secret db); set it manually, it was not imported."] }, config_state: S.configState, diff: S.configState === "active" ? "" : diff }),
    migration_import: () => { S.pending_restart = true; return { warnings: [], excluded: 46 }; },
    migration_activate: () => { S.configState = "active"; S.pending_restart = true; return { backup: "configuration.yaml.recorder_studio_backup_20261114_153012" }; },
  };
  return {
    themes: { darkMode: false },
    connection: {
      sendMessagePromise: (msg) => new Promise((res, rej) => setTimeout(() => {
        const fn = handlers[msg.type.replace("recorder_studio/", "")];
        if (!fn) return rej(new Error(`Unknown command ${msg.type}`));
        if (["purge", "repack", "restart", "migration_import", "migration_activate"].includes(msg.type.split("/")[1]) && msg.confirm !== true) return rej(new Error("confirm required"));
        try { res(JSON.parse(JSON.stringify(fn(msg)))); } catch (e) { rej(e); }
      }, 180)),
    },
  };
}
