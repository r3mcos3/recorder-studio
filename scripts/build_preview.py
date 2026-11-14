#!/usr/bin/env python3
"""Build preview/preview.html: ONE self-contained file (panel + lit + fake backend) for browser review.

No Node needed. The panel/lit/mock sources are embedded as blob modules so the file also works from file://.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
fe = root / "custom_components" / "recorder_studio" / "frontend"
lit = (fe / "vendor" / "lit.js").read_text()
panel = (fe / "recorder-studio-panel.js").read_text().replace('"./vendor/lit.js"', "__LIT__")
mock = (root / "mock" / "mock-hass.js").read_text()

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Recorder Studio preview</title>
<style>
:root {{ --primary-color:#03a9f4; --text-primary-color:#fff; --primary-background-color:#fafafa; --card-background-color:#fff; --primary-text-color:#212121; --secondary-text-color:#727272; --divider-color:#e0e0e0; --error-color:#db4437; --warning-color:#f9a825; --success-color:#43a047; --ha-card-border-radius:12px; --ha-card-box-shadow:0 1px 2px rgba(0,0,0,.08); }}
:root[data-theme=dark] {{ --primary-background-color:#111111; --card-background-color:#1c1c1c; --primary-text-color:#e1e1e1; --secondary-text-color:#9b9b9b; --divider-color:rgba(225,225,225,.14); --ha-card-box-shadow:none; }}
html,body {{ margin:0; height:100%; background:var(--primary-background-color); font-family:Roboto,system-ui,sans-serif; }}
#bar {{ display:flex; gap:8px; align-items:center; padding:8px 12px; background:#263238; color:#fff; font-size:13px; }}
#bar b {{ flex:1; }} #bar button {{ background:#37474f; color:#fff; border:0; border-radius:6px; padding:6px 10px; cursor:pointer; }}
#frame {{ height:calc(100% - 41px); overflow:auto; margin:0 auto; transition:width .2s; }} #frame.phone {{ width:390px; border-inline:1px solid #888; }}
</style></head><body>
<div id="bar"><b>Recorder Studio — UI preview (fake data, nothing is written anywhere)</b>
<button id="t">Light / dark</button><button id="w">Phone / desktop</button></div>
<div id="frame"></div>
<script type="module">
const LIT = {json.dumps(lit)};
const PANEL = {json.dumps(panel)};
const MOCK = {json.dumps(mock)};
const url = (src) => URL.createObjectURL(new Blob([src], {{type: "text/javascript"}}));
const litUrl = url(LIT);
await import(url(PANEL.replace("__LIT__", JSON.stringify(litUrl))));
const {{ createMockHass }} = await import(url(MOCK));
const el = document.createElement("recorder-studio-panel");
el.hass = createMockHass();
document.getElementById("frame").append(el);
// Deep links for review, e.g. preview.html#analyze&tab=entities&theme=dark&phone&open=all&dialog=purge-excluded
const q = new URLSearchParams(location.hash.slice(1));
if (q.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
if (q.has("phone")) document.getElementById("frame").classList.add("phone");
await el.updateComplete;
if (q.has("analyze")) await el._analyze();
await el.updateComplete; await new Promise((r) => setTimeout(r, 400));
if (q.get("tab")) el._tab = q.get("tab");
if (q.get("open") === "all") el._open = new Set(el._data.tree.map((d) => d.device_id));
if (q.get("search")) el._search = q.get("search");
if (q.has("pending")) el._toggle(el._entities.slice(0, 4).map((e) => e.entity_id), false);
if (q.get("dialog") === "purge-excluded") await el._askPurge("excluded");
if (q.get("dialog") === "restart") el._askRestart();
if (q.get("dialog") === "migrate") {{ await el._previewMigration("configuration"); }}
document.getElementById("t").onclick = () => {{ const r = document.documentElement; r.dataset.theme = r.dataset.theme === "dark" ? "light" : "dark"; }};
document.getElementById("w").onclick = () => document.getElementById("frame").classList.toggle("phone");
</script></body></html>
"""
out = root / "preview" / "preview.html"
out.parent.mkdir(exist_ok=True)
out.write_text(page)
print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
