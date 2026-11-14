import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "recorder_studio"))


@pytest.fixture
def synthetic_db(tmp_path):
    """Small SQLite file with the modern HA schema (states + states_meta). Never the real DB."""
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT);
        CREATE TABLE states (state_id INTEGER PRIMARY KEY, metadata_id INTEGER, state TEXT);
        """
    )
    rows = {"sensor.a": 50, "sensor.b_uptime": 30, "light.kitchen": 15, "sensor.gone": 5}
    for i, (eid, n) in enumerate(rows.items(), start=1):
        conn.execute("INSERT INTO states_meta VALUES (?, ?)", (i, eid))
        conn.executemany("INSERT INTO states (metadata_id, state) VALUES (?, 'x')", [(i,)] * n)
    conn.commit()
    conn.close()
    return path
