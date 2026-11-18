"""Tests against a REAL recorder (HA's recorder_mock). Separate from tests_ha because that suite sets up `hass` in an
autouse fixture, and recorder_mock must be created before `hass`.

Run with:  python -m pytest tests_ha_recorder
"""
import pytest


@pytest.fixture
def config_dir(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    return tmp_path
