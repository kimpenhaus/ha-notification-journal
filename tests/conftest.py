"""Shared fixtures."""

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from custom_components in every test."""
    return


@pytest.fixture(autouse=True)
def config_dir(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Keep the database of every test in its own directory."""
    hass.config.config_dir = str(tmp_path)
    return tmp_path
