# CLAUDE.md

Guidance for AI agents working on this repository. Read `README.md` first for the user-facing description.

## What this is

**Recorder Studio** (`recorder_studio`) is a Home Assistant custom integration: a sidebar panel to control what the
`recorder` stores (per device / per entity), see what fills the SQLite database, and purge or repack it safely. It is an
independent re-implementation inspired by GUI Recorder (MIT); no code was copied. Public repo, MIT license, installed
through HACS (custom repository, and a pull request to the HACS default list is pending).

**SQLite only.** The config flow refuses other backends. MariaDB/PostgreSQL support is a known, parked idea (see
"Ideas parked" below); do not build it unless asked.

## Layout

```
custom_components/recorder_studio/
  core/                pure Python, NO Home Assistant imports, unit-tested
    rules.py           exclusion rules, manual YAML rules validation
    yaml_writer.py     renders recorder_studio.yaml, atomic write
    db_stats.py        read-only SQLite analysis (counts, dbstat table sizes, file sizes, free space)
    tree.py            device -> entity tree with record counts and percentages
    migration.py       inspect/import/activate of an existing recorder config (backup + diff)
  __init__.py, const.py, config_flow.py, storage.py, panel.py, service.py, websocket_api.py   HA glue
  frontend/recorder-studio-panel.js    single Lit module, no build step
  frontend/vendor/lit.js               Lit 3.2.1 bundled once with esbuild (do not rebuild at runtime)
  brand/                               icons (HA 2026.3+ local brand images)
  translations/en.json, manifest.json
tests/                 pytest on a synthetic SQLite database (conftest.py builds states + states_meta)
mock/mock-hass.js      fake hass object + websocket for the preview
scripts/build_preview.py   builds preview/preview.html (single file, fake data, writes nothing)
preview/preview.html   generated; rebuild after every panel or mock change
docs/images/           README screenshots (real screenshots, cropped to the panel)
.github/workflows/validate.yaml    hassfest + HACS action + pytest
```

## How it works (the important decisions)

- Choices are stored in `.storage/recorder_studio.data` and rendered to **`recorder_studio.yaml`** in the HA config
  folder (atomic write). `configuration.yaml` contains `recorder: !include recorder_studio.yaml`. The recorder reads it
  **at startup only**, so changes need an HA restart; the panel shows a banner for that.
- Statistics use a strictly **read-only** SQLite connection (`mode=ro`). Everything that changes data goes through the
  official services `recorder.purge` and `recorder.purge_entities`. Never write to the database directly.
- Purges are queued recorder tasks and can take a minute on a large database. The panel therefore polls `analyze`
  until the expected number of records is gone (`_followUp` in the panel) instead of trusting the first analysis.
- Websocket API is admin-only (`require_admin`); destructive commands also need `confirm: true`.
- `const.READ_ONLY_MODE` (False) refuses all write actions when set to True.
- Migration never imports `!secret`/YAML-tag values as plain text and only emits rescued entities when a domain/glob
  filter makes `include.entities` meaningful.
- Data is **live**: the panel's `_live()` loop runs a light `analyze` (record counts only, `light: true`) every 30 s (slower
  if an analysis takes long) and a full one (with `dbstat` table sizes, which read every page) every 10 minutes. It pauses
  while the tab is hidden, an action runs or a dialog is open. Background refreshes are `silent` so they never overwrite
  Settings the user is typing. There is no manual Refresh button; keep it that way.

## Gotchas learned the hard way

- **Device registry:** iterate `dev_reg.devices` (yields `DeviceEntry` on current HA, ids on older). Do NOT use
  `async_get_devices()` without filters: it does not return all devices and every device shows as "Unknown device".
- Python changes need an HA restart; panel JS, brand and README changes do not (hard refresh with Ctrl+Shift+R).
- Percentages are stored with 4 decimals; rounding to 1-2 decimals turned small entities into "0%".
- A typed `PURGE` confirmation is required for multi-entity purges; a single entity needs only a confirm click.
- Device purge always uses the unfiltered device (all its entities), even when a search filter is active.
- Re-enabling recording for an entity matched by a manual domain/glob rule is not supported (documented limitation).

## Working on it

```bash
uv venv .venv && uv pip install --python .venv/bin/python pytest pyyaml
.venv/bin/python -m pytest            # must stay green
python3 scripts/build_preview.py      # rebuild preview/preview.html
```

- Keep `core/` free of Home Assistant imports and cover new logic with tests on the synthetic database.
- The preview (`preview/preview.html#analyze&tab=entities&open=all&theme=dark&phone`, also `dialog=purge-excluded|
  purge-device|purge-entity|restart|migrate`) is the way to check UI changes without Home Assistant. Rebuild it after
  panel or mock changes.
- **Never run purge or migration tests against a real database.** There is no HA test instance; verify with pytest and
  the mock preview, then deploy to the user's HA only when they ask.
- `manifest.json` keys must stay in hassfest order (domain, name, then alphabetical). Bump `version` for a release.
- **Release policy (keep releases frequent, do not let a gap build up):** HACS users get the latest *release*, not
  `main`, so unreleased fixes do not reach anyone. After every user-facing fix or feature (changes under
  `custom_components/`), bump `version` in `manifest.json` (patch for fixes, minor for features) and push. The
  `Release` workflow then creates the GitHub release by itself once `Validate` is green, with generated notes. Docs-only
  or CI-only commits need no release. Before finishing a work session, check `git log vX.Y.Z..main` and release if
  user-facing changes are waiting.
- README: keep the troubleshooting table, limitations and tab descriptions in sync with the code. Screenshots in
  `docs/images/` are cropped real screenshots; they show real entity names, so check them before publishing new ones.

## Conventions

- Commit subjects: an emoji prefix plus an English description (for example `✨ Add per-device purge`,
  `🐛 Fix device names showing as Unknown device`). No `Co-Authored-By` trailers.
- Commit and push straight to `main`; no feature branches.
- Chat with the maintainer is in Dutch; code, comments, commits and docs are in English.
- Do not push, deploy to a live Home Assistant, restart it, or open pull requests on other repositories without being
  asked. Announce a restart beforehand.

## Open items and ideas parked

- HACS default list: pull request `hacs/default#14173` is waiting for review. Do not request a review (they close it).
- Parked, not to be built unprompted: MariaDB/PostgreSQL support. Plan: use the recorder's own SQLAlchemy session
  (no `db_url` parsing), generic `states JOIN states_meta GROUP BY` counts, sizes via `information_schema.TABLES`
  (MariaDB) or `pg_database_size`/`pg_total_relation_size` (PostgreSQL), label as experimental, test the SQL in GitHub
  Actions with service containers, leave the SQLite path untouched.
- The per-table size card needs SQLite's `dbstat` module; it is hidden when unavailable.
