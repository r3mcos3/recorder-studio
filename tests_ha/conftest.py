"""Tests for the Home Assistant glue (service, websocket API, config flow, alerts).

Run with:  .venv-ha/bin/python -m pytest tests_ha     (needs pytest-homeassistant-custom-component)
The pure-Python core is tested separately in tests/ and needs no Home Assistant.
"""
import sqlite3
import time

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recorder_studio import service
from custom_components.recorder_studio.const import DOMAIN


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture(autouse=True)
def _no_real_dependencies():
    """frontend/http/recorder are dependencies in the manifest; the glue is tested without starting them."""
    from unittest.mock import patch

    from homeassistant import setup

    original = setup._async_process_dependencies

    async def fake(hass, config, integration):
        return [] if integration.domain == DOMAIN else await original(hass, config, integration)

    with patch("homeassistant.setup._async_process_dependencies", fake):
        yield


@pytest.fixture
def config_dir(hass, tmp_path):
    """Point the config folder at a temp dir so generated files never touch anything real."""
    hass.config.config_dir = str(tmp_path)
    return tmp_path


@pytest.fixture
def db_file(config_dir, monkeypatch):
    """Synthetic recorder database, wired in as the one the integration analyses (never a real database)."""
    path = config_dir / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT);
        CREATE TABLE state_attributes (attributes_id INTEGER PRIMARY KEY, shared_attrs TEXT);
        CREATE TABLE states (state_id INTEGER PRIMARY KEY, metadata_id INTEGER, state TEXT, attributes_id INTEGER, last_updated_ts REAL);
        """
    )
    now = time.time()
    for i, (eid, n) in enumerate({"sensor.wifi_rssi": 80, "sensor.keep": 15, "light.kitchen": 5}.items(), start=1):
        conn.execute("INSERT INTO states_meta VALUES (?, ?)", (i, eid))
        conn.execute("INSERT INTO state_attributes VALUES (?, ?)", (i, "x" * 50))
        conn.executemany(
            "INSERT INTO states (metadata_id, state, attributes_id, last_updated_ts) VALUES (?, '1', ?, ?)", [(i, i, now - 60)] * n
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(service, "db_path", lambda hass: path)
    monkeypatch.setattr(service, "recorder_db_url", lambda hass: "sqlite:///test.db")
    return path


@pytest.fixture
async def entry(hass, config_dir, db_file):
    """A set-up Recorder Studio config entry (dependencies faked: no real recorder/frontend needed)."""
    from unittest.mock import AsyncMock, patch

    e = MockConfigEntry(domain=DOMAIN, data={})
    e.add_to_hass(hass)
    with patch("custom_components.recorder_studio.async_setup_panel", AsyncMock()):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    return e


@pytest.fixture
async def ws(hass, entry, hass_ws_client):
    return await hass_ws_client(hass)


async def call(client, type_, **payload):
    await client.send_json_auto_id({"type": f"{DOMAIN}/{type_}", **payload})
    return await client.receive_json()
