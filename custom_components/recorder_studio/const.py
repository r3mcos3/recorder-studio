import json
from pathlib import Path

DOMAIN = "recorder_studio"


def _manifest_version() -> str:
    """Single source of truth for the version: manifest.json (bumped on every release)."""
    try:
        return json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return "unknown"


VERSION = _manifest_version()
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.data"

CONFIG_FILE = "configuration.yaml"
GENERATED_FILE = "recorder_studio.yaml"
LEGACY_FILE = "gui_recorder.yaml"  # only ever read, never modified

PANEL_PATH = "recorder-studio"
PANEL_TITLE = "Recorder Studio"
PANEL_ICON = "mdi:database-cog"
STATIC_URL = f"/api/{DOMAIN}/static"

DEFAULT_DATA = {
    "options": {"purge_keep_days": 10, "auto_purge": True, "auto_repack": True, "commit_interval": 5},
    "excluded_entities": [],
    "rescued_entities": [],
    "rules_text": "",
    "stats": None,
    "history": [],  # daily {d, size, records, recent} snapshots, see core/history.py
    "dismissed": [],  # suggestions the user hid
    "alerts": {"enabled": True, "free_percent": 10, "growth_percent": 25},
}

ALERT_INTERVAL_HOURS = 6  # background check (read-only light analysis + repairs issues)
ATTR_REFRESH_SECONDS = 3600  # the slow per-entity attribute size measurement is repeated at most hourly

# When True every write action (yaml, purge, repack, restart, migration, settings) is refused
# server-side; statistics and the entity list keep working. Useful for a cautious first run.
READ_ONLY_MODE = False
