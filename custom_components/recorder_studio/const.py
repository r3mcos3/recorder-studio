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
}

# When True every write action (yaml, purge, repack, restart, migration, settings) is refused
# server-side; statistics and the entity list keep working. Useful for a cautious first run.
READ_ONLY_MODE = False
