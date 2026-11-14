DOMAIN = "recorder_studio"
VERSION = "0.1.0"
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

# First live test: every write action (yaml, purge, repack, restart, migration, settings) is refused
# server-side. Statistics (read-only SQLite) and the entity list keep working. Set to False only after
# explicit approval to enable writes.
READ_ONLY_MODE = True
