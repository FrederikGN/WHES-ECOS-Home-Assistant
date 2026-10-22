"""Shared fixtures for the ECOS Hub tests.

The tests run inside a real Home Assistant core supplied by
pytest-homeassistant-custom-component. The WHES API is always mocked, so
nothing here reaches the cloud or the battery.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/ecos_hub."""
    yield
