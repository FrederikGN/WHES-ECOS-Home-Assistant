"""Tests for the diagnostics download and its read-only probe.

Nothing here talks to the real cloud or the real battery.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ecos_hub.api import (
    EcosHubApiError,
    EcosHubClient,
    EcosHubConnectionError,
)
from custom_components.ecos_hub.const import (
    API_PREFIX,
    DOMAIN,
    INVERTER_SLAVE_ID,
    PROBE_CONFIG_MODULES,
    PROBE_REGISTER_COUNT,
    PROBE_REGISTER_START,
)
from custom_components.ecos_hub.coordinator import EcosHubCoordinator, EcosHubData
from custom_components.ecos_hub.diagnostics import async_get_config_entry_diagnostics

SN = "TESTSN0001"
ACCESS_KEY = "test-access-key"
ACCESS_SECRET = "test-access-secret"


def _client() -> AsyncMock:
    client = AsyncMock()
    client.async_query_config.return_value = {
        "deviceSn": SN,
        "chargeModeCode": "1",
        "segments": [{"chargePower": "3000"}],
    }
    client.async_read_registers.return_value = list(range(PROBE_REGISTER_COUNT))
    client.async_get_latest_metrics.return_value = {"sys_power_config": 3}
    return client


def _entry(hass: HomeAssistant, client: AsyncMock) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SN,
        data={
            "access_key": ACCESS_KEY,
            "access_secret": ACCESS_SECRET,
            "host": "https://example.invalid",
            "device_sn": SN,
        },
    )
    entry.add_to_hass(hass)
    coordinator = EcosHubCoordinator(hass, entry, client, SN)
    coordinator.data = EcosHubData(
        metrics={"bat_soc": 55, "serial": SN},
        device={
            "device_sn": SN,
            # The API defaults the name to the serial.
            "device_name": SN,
            "alias": "Home battery",
            "latitude": 55.676,
            "longitude": 12.568,
            "state": 1,
        },
        config={"deviceSn": SN, "chargeModeCode": "1"},
    )
    entry.runtime_data = coordinator
    return entry


async def test_probe_reads_everything_in_order(hass: HomeAssistant) -> None:
    """The snapshot covers each module, the register block and the metrics."""
    client = _client()
    result = await async_get_config_entry_diagnostics(hass, _entry(hass, client))
    probe = result["probe"]

    for module in PROBE_CONFIG_MODULES:
        assert probe[module]["chargeModeCode"] == "1"
    assert [call.args for call in client.async_query_config.await_args_list] == [
        (SN, module) for module in PROBE_CONFIG_MODULES
    ]

    client.async_read_registers.assert_awaited_once_with(
        SN, PROBE_REGISTER_START, PROBE_REGISTER_COUNT, INVERTER_SLAVE_ID
    )
    # Keyed by address, so the operating mode sits under its register number.
    assert len(probe["registers"]) == PROBE_REGISTER_COUNT
    assert probe["registers"]["41003"] == 2

    assert probe["ems_metrics"] == {"sys_power_config": 3}
    assert result["config"]["chargeModeCode"] == "1"


async def test_probe_never_writes(hass: HomeAssistant) -> None:
    """Downloading diagnostics must not change anything on the inverter."""
    client = _client()
    await async_get_config_entry_diagnostics(hass, _entry(hass, client))

    client.async_set_battery_config.assert_not_called()
    client.async_set_control_mode.assert_not_called()
    client.async_bind_vpp_devices.assert_not_called()


async def test_nothing_identifying_is_left_in_the_download(
    hass: HomeAssistant,
) -> None:
    """Serial, credentials, alias and coordinates are all gone."""
    client = _client()
    # An error that quotes the request path, serial included.
    client.async_get_latest_metrics.side_effect = EcosHubConnectionError(
        f"HTTP 502 from {API_PREFIX}/devices/{SN}/metrics"
    )

    result = await async_get_config_entry_diagnostics(hass, _entry(hass, client))
    text = json.dumps(result)

    assert SN not in text
    assert ACCESS_KEY not in text
    assert ACCESS_SECRET not in text
    assert "Home battery" not in text
    assert "55.676" not in text
    assert "12.568" not in text
    # The error itself survives, minus the serial.
    assert "HTTP 502" in result["probe"]["ems_metrics"]["error"]


async def test_refused_and_hung_calls_do_not_fail_the_download(
    hass: HomeAssistant,
) -> None:
    """Each read needs its own permission; a refusal is reported in place."""
    client = _client()

    async def query_config(device_sn: str, module: str) -> dict:
        if module == "EMS_RUNTIME_DATA":
            raise EcosHubApiError(4000, "permission denied")
        if module == "WORK_MODE_PARALLEL":
            await asyncio.Event().wait()  # never answers
        return {"chargeModeCode": "1"}

    client.async_query_config.side_effect = query_config

    with patch("custom_components.ecos_hub.diagnostics.PROBE_TIMEOUT_SECONDS", 0.05):
        result = await async_get_config_entry_diagnostics(hass, _entry(hass, client))
    probe = result["probe"]

    assert probe["BATTERY_SETTING"] == {"chargeModeCode": "1"}
    assert "permission denied" in probe["EMS_RUNTIME_DATA"]["error"]
    assert probe["WORK_MODE_PARALLEL"] == {"error": "TimeoutError"}
    # The calls after the failures still ran.
    assert len(probe["registers"]) == PROBE_REGISTER_COUNT
    assert probe["ems_metrics"] == {"sys_power_config": 3}


async def test_read_registers_only_ever_reads() -> None:
    """The passthrough call is a holding-register read, function code 3."""
    client = EcosHubClient(
        session=None, host="https://example.invalid", access_key="k", access_secret="s"
    )

    with patch.object(
        client, "_request", AsyncMock(return_value={"code": 200, "data": [7, 8, 9]})
    ) as request:
        assert await client.async_read_registers(SN, 41001, 3, 1) == [7, 8, 9]

    request.assert_awaited_once_with(
        "POST",
        f"{API_PREFIX}/devices/{SN}/read",
        json_body={
            "deviceSn": SN,
            "slaveId": 1,
            "startAddress": 41001,
            "len": 3,
            "funcCode": 3,
        },
    )

    # A device that answers with no data yields an empty list, not a crash.
    with patch.object(
        client, "_request", AsyncMock(return_value={"code": 200, "data": None})
    ):
        assert await client.async_read_registers(SN, 41001, 3, 1) == []
