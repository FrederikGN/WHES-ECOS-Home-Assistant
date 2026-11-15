"""Diagnostics support for the ECOS Hub integration."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import EcosHubConfigEntry
from .api import EcosHubError
from .const import (
    CONF_ACCESS_KEY,
    CONF_ACCESS_SECRET,
    INVERTER_SLAVE_ID,
    METRICS_LOOKBACK,
    PROBE_CONFIG_MODULES,
    PROBE_METRIC_COLUMNS,
    PROBE_REGISTER_COUNT,
    PROBE_REGISTER_START,
    PROBE_TIMEOUT_SECONDS,
)
from .coordinator import EcosHubCoordinator

TO_REDACT = {
    CONF_ACCESS_KEY,
    CONF_ACCESS_SECRET,
    "latitude",
    "longitude",
    "address",
    "alias",
    "device_sn",
    "wifi_sn",
    "bms_sn",
    # The configuration endpoints spell it in camelCase.
    "deviceSn",
    # Metric columns, present when the API made us fetch every column.
    "serial",
    "bms_serial",
    "bms_serial_c",
}


def _scrub_serial(value: Any, device_sn: str) -> Any:
    """Blank the serial number wherever it turns up as a value.

    Redacting by key misses it in error messages, which quote the request
    path, and in fields such as device_name that default to the serial.
    """
    if isinstance(value, str):
        return value.replace(device_sn, REDACTED)
    if isinstance(value, dict):
        return {key: _scrub_serial(item, device_sn) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_serial(item, device_sn) for item in value]
    return value


async def _async_attempt(call: Awaitable[Any]) -> Any:
    """Run one probe call, reporting a failure instead of raising.

    Any of these can be refused -- each needs its own permission -- and a
    refusal is itself worth seeing in the download.
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            return await call
    except (EcosHubError, TimeoutError, ValueError) as err:
        return {"error": str(err) or type(err).__name__}


async def _async_probe(coordinator: EcosHubCoordinator) -> dict[str, Any]:
    """Take a live, read-only snapshot of how the inverter is being driven.

    Nothing here writes. The calls run one at a time because they all end up
    on the inverter's single Modbus link.
    """
    client = coordinator.client
    device_sn = coordinator.device_sn
    probe: dict[str, Any] = {"taken_at": dt_util.utcnow().isoformat()}

    for module in PROBE_CONFIG_MODULES:
        probe[module] = await _async_attempt(
            client.async_query_config(device_sn, module)
        )

    registers = await _async_attempt(
        client.async_read_registers(
            device_sn, PROBE_REGISTER_START, PROBE_REGISTER_COUNT, INVERTER_SLAVE_ID
        )
    )
    if isinstance(registers, list):
        # Keyed by address so two downloads can be compared line by line.
        registers = {
            str(PROBE_REGISTER_START + offset): value
            for offset, value in enumerate(registers)
        }
    probe["registers"] = registers

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(METRICS_LOOKBACK.total_seconds() * 1000)
    probe["ems_metrics"] = await _async_attempt(
        client.async_get_latest_metrics(
            device_sn, start_ms, now_ms, PROBE_METRIC_COLUMNS
        )
    )

    return probe


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EcosHubConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    diagnostics = {
        "entry": dict(entry.data),
        "device": dict(data.device) if data else {},
        "metrics": dict(data.metrics) if data else {},
        "config": dict(data.config) if data else {},
        "probe": await _async_probe(coordinator),
    }

    return _scrub_serial(
        async_redact_data(diagnostics, TO_REDACT), coordinator.device_sn
    )
