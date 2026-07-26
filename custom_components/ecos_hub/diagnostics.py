"""Diagnostics support for the ECOS Hub integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EcosHubConfigEntry
from .const import CONF_ACCESS_KEY, CONF_ACCESS_SECRET

TO_REDACT = {
    CONF_ACCESS_KEY,
    CONF_ACCESS_SECRET,
    "latitude",
    "longitude",
    "address",
    "device_sn",
    "wifi_sn",
    "bms_sn",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EcosHubConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "device": async_redact_data(dict(data.device) if data else {}, TO_REDACT),
        "metrics": async_redact_data(dict(data.metrics) if data else {}, TO_REDACT),
    }
