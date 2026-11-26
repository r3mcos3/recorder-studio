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
    sqlite: true, version: "0.4.0", yaml_file: "recorder_studio.yaml", pending_restart: false,
    options: { purge_keep_days: 14, auto_purge: true, auto_repack: true, commit_interval: 5 },
    rules_text: "exclude:\n  entity_globs:\n    - sensor.*_uptime\n",
    analysed: false, tree, orphans: orphanIds, configState: "inline", importedFrom: null, dismissed: new Set(), alerts: { enabled: true, free_percent: 10, growth_percent: 25 }, alertActive: [], backup: { known: true, count: 3, hoursAgo: 5 },
  };
  const all = () => S.tree.flatMap((d) => d.entities);
  const excludedAll = () => [...all().filter((e) => !e.recorded).map((e) => e.entity_id), ...S.orphans];
  const summary = () => {
    if (!S.analysed) return null;
    const ents = all(); const total = ents.reduce((a, e) => a + e.records, 0);
    const obsolete = ents.filter((e) => !e.recorded).reduce((a, e) => a + e.records, 0);
    return { total_records: total, current_records: total - obsolete, obsolete_records: obsolete, excluded_with_records: ents.filter((e) => !e.recorded && e.records).length,
      orphan_exclusions: S.orphans, entity_count: ents.length, db_size_bytes: total * 118 + 12e6, db_path: "/config/home-assistant_v2.db", generated_at: new Date().toISOString(), error: null,
      tables: [["states", 0.46], ["state_attributes", 0.22], ["statistics_short_term", 0.12], ["events", 0.09], ["statistics", 0.05], ["event_data", 0.03]].map(([name, f]) => ({ name, bytes: Math.round((total * 118 + 12e6) * f) })), free_bytes: 18.4e6,
      top_entities: ents.map((e) => [e.entity_id, e.records, +(e.records * 100 / total).toFixed(2)]).sort((a, b) => b[1] - a[1]).slice(0, 12),
      top_sizes: (() => { const sz = ents.map((e) => [e.entity_id, bytesOf(e)]); const tb = sz.reduce((a, x) => a + x[1], 0) || 1; return sz.sort((a, b) => b[1] - a[1]).slice(0, 12).map(([id, b]) => [id, b, +(b * 100 / tb).toFixed(2)]); })(),
      recent_total: Math.round(total / 9), has_attr_sizes: true,
      top_recent: ents.map((e) => [e.entity_id, Math.round(e.records / 9)]).sort((a, b) => b[1] - a[1]).slice(0, 8) };
  };
  const bytesOf = (e) => Math.round(e.records * 118 + (e.records ? 1200 : 0));
  const suggestions = () => {
    if (!S.analysed) return { items: [], total_found: 0, save_bytes: 0, save_percent: 0, dismissed: S.dismissed.size };
    const cand = all().filter((e) => e.recorded && !S.dismissed.has(e.entity_id) && /uptime|linkquality|wifi|voltage|distance|compressor/.test(e.entity_id));
    const total = all().reduce((a, e) => a + bytesOf(e), 0) || 1;
    const items = cand.sort((a, b) => b.records - a.records).slice(0, 6).map((e) => {
      const warn = /voltage|compressor/.test(e.entity_id) ? "Has long-term statistics: excluding it stops those too (and any Energy dashboard use)." : "";
      const diag = /uptime|linkquality|wifi/.test(e.entity_id);
      return { entity_id: e.entity_id, name: e.name, device: "", records: e.records, bytes: bytesOf(e), percent: +(e.records * 100 / all().reduce((a, x) => a + x.records, 0)).toFixed(2), per_day: Math.round(e.records / 9),
        reasons: [diag ? "Diagnostic entity" : "Name suggests a rapidly changing value", diag ? "Name suggests technical noise (signal, uptime, …)" : "Large share of the database", `${fmtN(Math.round(e.records / 9))} records in the last 24 h`], warn, confidence: warn ? "check" : "high" };
    });
    const saved = items.filter((i) => !i.warn).reduce((a, i) => a + i.bytes, 0);
    return { items, total_found: items.length, save_bytes: saved, save_percent: +(saved * 100 / total).toFixed(1), dismissed: S.dismissed.size };
  };
  const fmtN = (n) => n.toLocaleString("en-US");
  const growth = () => {
    const size = all().reduce((a, e) => a + e.records, 0) * 118 + 12e6;
    const points = Array.from({ length: 21 }, (_, i) => ({ d: new Date(Date.now() - (20 - i) * 864e5).toISOString().slice(0, 10), size: Math.round(size * (0.72 + 0.28 * (i / 20) + (i % 3) * 0.004)) }));
    return { points, growth_per_day: Math.round(size * 0.0135), days_to_full: 142, days_covered: 14, recent_total: Math.round(all().reduce((a, e) => a + e.records, 0) / 9), bytes_per_day: Math.round(size * 0.012), disk_total: 64e9, disk_free: 38.5e9, snapshots: 21 };
  };
  const view = () => ({
    suggestions: suggestions(), growth: growth(), alerts: { ...S.alerts, active: S.alertActive },
    version: S.version, sqlite: S.sqlite, db_files: (() => { const t = all().reduce((a, e) => a + e.records, 0) * 118 + 12e6; return { db: Math.round(t * 0.93), wal: Math.round(t * 0.07), shm: 32768, total: Math.round(t * 0.93) + Math.round(t * 0.07) + 32768 }; })(), options: S.options, rules_text: S.rules_text, yaml_file: S.yaml_file, pending_restart: S.pending_restart, summary: summary(),
    tree: (() => { const tot = all().reduce((a, e) => a + e.records, 0); const p = (n) => (S.analysed && tot ? +(n * 100 / tot).toFixed(2) : 0); return S.tree.map((d) => ({ ...d, entities: d.entities.map((e) => ({ ...e, records: S.analysed ? e.records : 0, percent: p(e.records), bytes: S.analysed ? bytesOf(e) : 0 })), records: S.analysed ? d.entities.reduce((a, e) => a + e.records, 0) : 0, percent: p(d.entities.reduce((a, e) => a + e.records, 0)), bytes: S.analysed ? d.entities.reduce((a, e) => a + bytesOf(e), 0) : 0, excluded_count: 0 })); })(),
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
    save_alerts: (m) => { S.alerts = { enabled: m.enabled, free_percent: m.free_percent, growth_percent: m.growth_percent }; return { active: S.alertActive }; },
    dismiss_suggestions: (m) => { if (m.reset) S.dismissed.clear(); (m.entity_ids || []).forEach((i) => S.dismissed.add(i)); return { suggestions: suggestions() }; },
    backup_status: () => (S.backup.known ? { known: true, count: S.backup.count, age_hours: S.backup.hoursAgo, last: new Date(Date.now() - S.backup.hoursAgo * 36e5).toISOString() } : { known: false }),
    repack: () => ({ queued: true }), restart: () => { S.pending_restart = false; return { ok: true }; },
    remove_orphans: () => { const n = S.orphans.length; S.orphans = []; S.pending_restart = true; return { removed: n }; },
    migration_sources: () => ({ sources: [{ id: "configuration", label: "configuration.yaml (inline recorder: block)", path: "configuration.yaml", kind: "inline", excluded: 23, note: "" }, { id: "legacy", label: "gui_recorder.yaml", path: "gui_recorder.yaml", kind: "legacy", excluded: 46, note: "GUI Recorder's file; it stays untouched and becomes inert after activation." }, { id: "file:packages/recorder.yaml", label: "packages/recorder.yaml", path: "packages/recorder.yaml", kind: "other", excluded: 8, note: "This file is not changed. After activation, remove its recorder: section yourself, otherwise Home Assistant reports a duplicate recorder configuration." }] }),
    migration_preview: ({ source }) => ({ label: source === "legacy" ? "gui_recorder.yaml" : source === "paste" ? "pasted YAML" : source.startsWith("file:") ? source.slice(5) : "configuration.yaml", note: source.startsWith("file:") ? source.slice(5) + " is not changed by Recorder Studio. After activation, remove its recorder: section yourself, otherwise Home Assistant reports a duplicate recorder configuration." : "", current_excluded: 12, import: { excluded_count: source === "legacy" ? 46 : 23, excluded_entities: [], warnings: source === "legacy" ? [] : ["Option 'db_max_retries' is not supported and was left out.", "'db_url' uses a YAML tag (!secret db); set it manually, it was not imported."] }, config_state: S.configState, diff: S.configState === "active" ? "" : diff }),
    migration_import: () => { S.pending_restart = true; return { warnings: [], excluded: 46 }; },
  };
  return {
    __S: S,
    themes: { darkMode: false },
    connection: {
      sendMessagePromise: (msg) => new Promise((res, rej) => setTimeout(() => {
        const fn = handlers[msg.type.replace("recorder_studio/", "")];
        if (!fn) return rej(new Error(`Unknown command ${msg.type}`));
        if (["purge", "repack", "restart", "migration_import"].includes(msg.type.split("/")[1]) && msg.confirm !== true) return rej(new Error("confirm required"));
        try { res(JSON.parse(JSON.stringify(fn(msg)))); } catch (e) { rej(e); }
      }, 180)),
    },
  };
}
