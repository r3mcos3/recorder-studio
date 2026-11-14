# Recorder Studio

A Home Assistant custom integration (HACS, **SQLite only**) with a modern sidebar panel to manage the
`recorder`: choose per device/entity what is recorded, see database statistics, run maintenance
(purge, purge excluded, repack, restart), detect orphaned exclusions and migrate an existing recorder config.

This is an independent re-implementation inspired by the *functionality* of
[GUI Recorder](https://github.com/martinandersen84/gui-recorder) (MIT). No code was copied.

> **Purges are permanent.** Make a full HA backup first. Never try purge/migration on a database you care about without one.

## Installation (HACS)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=r3mcos3&repository=recorder-studio&category=integration)

1. Click the button above (or HACS > three dots > *Custom repositories*, add `https://github.com/r3mcos3/recorder-studio`, category *Integration*).
2. Download **Recorder Studio** in HACS and restart Home Assistant.
3. Settings > Devices & services > *Add integration* > **Recorder Studio**.

> HACS can only download a repository that is **public** (or reachable with a GitHub token). The button works
> once the repository is made public.

Manual: copy `custom_components/recorder_studio/` to `<config>/custom_components/` and restart.

## How it works

The panel writes `recorder_studio.yaml` in your config folder. `configuration.yaml` includes it with
`recorder: !include recorder_studio.yaml` (the Migration tab sets this up, with a diff preview and a backup).
Recorder changes apply after a Home Assistant restart. Statistics come from a strictly read-only SQLite connection;
purges go through the official `recorder.purge` / `recorder.purge_entities` services.

## Safety

- Every destructive action shows its impact and needs confirmation (typing `PURGE` for bulk purges).
- All websocket commands are admin-only; destructive ones also require an explicit `confirm: true`.
- `configuration.yaml` is backed up before it is touched; files are written atomically.
- Values using YAML tags (e.g. `!secret`) are never imported as plain text.
- `gui_recorder.yaml` is only ever read, never modified.

## Preview the UI without Home Assistant

Open `preview/preview.html` in a browser (single file, fake data, writes nothing). Deep links:
`preview.html#analyze&tab=entities&open=all&theme=dark&phone`. Rebuild it with `python3 scripts/build_preview.py`.

## Development

```
uv venv .venv && uv pip install --python .venv/bin/python pytest pyyaml
.venv/bin/python -m pytest
```

The logic lives in `custom_components/recorder_studio/core/` (pure Python, no HA imports, unit-tested on a
synthetic SQLite database). The panel is [Lit](https://lit.dev) (BSD-3, vendored in `frontend/vendor/`, no build step).

## Status

v0.1.0. Tested read-only on a live Home Assistant; write actions are enabled from this version on.
Set `READ_ONLY_MODE = True` in `const.py` to refuse all write actions.
