"""Tests for the security-hardening branch, run against a mocked WHES API.

Nothing here talks to the real cloud or the real battery.
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ecos_hub.api import EcosHubConnectionError
from custom_components.ecos_hub.const import DOMAIN, MAX_STALE_DATA
from custom_components.ecos_hub.coordinator import EcosHubCoordinator, EcosHubData
from custom_components.ecos_hub.services import (
    SET_CHARGE_SCHEDULE_SCHEMA,
    SET_CONTROL_MODE_SCHEMA,
)

SN = "TESTSN0001"




def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=SN,
        data={
            "access_key": "k",
            "access_secret": "s",
            "host": "https://example.invalid",
            "device_sn": SN,
        },
    )


def _metrics(age: timedelta) -> dict:
    sample_ms = int((time.time() - age.total_seconds()) * 1000)
    return {"bat_soc": 55, "_sample_time": sample_ms}


def _coordinator(hass: HomeAssistant, client) -> EcosHubCoordinator:
    entry = _entry()
    entry.add_to_hass(hass)
    coord = EcosHubCoordinator(hass, entry, client, SN)
    return coord


def _client() -> AsyncMock:
    client = AsyncMock()
    client.async_get_device.return_value = {"device_model": "TIA103"}
    client.async_query_config.return_value = {"chargeModeCode": "1"}
    return client


# --- Fund 1: stale data -----------------------------------------------------


async def test_api_failure_keeps_fresh_readings(hass: HomeAssistant) -> None:
    """A blip keeps readings that are still younger than the limit."""
    client = _client()
    coord = _coordinator(hass, client)
    coord.data = EcosHubData(metrics=_metrics(timedelta(minutes=3)))

    client.async_get_latest_metrics.side_effect = EcosHubConnectionError("5000")
    result = await coord._async_update_data()
    assert result is coord.data


async def test_api_failure_drops_stale_readings(hass: HomeAssistant) -> None:
    """Once the newest sample is too old, the entities go unavailable."""
    client = _client()
    coord = _coordinator(hass, client)
    coord.data = EcosHubData(metrics=_metrics(MAX_STALE_DATA + timedelta(seconds=5)))

    client.async_get_latest_metrics.side_effect = EcosHubConnectionError("5000")
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_old_bug_scenario_is_now_bounded(hass: HomeAssistant) -> None:
    """Simulate a long outage: data never survives past MAX_STALE_DATA.

    Under the old count-based rule ten failures with backoff took 60-75 min.
    """
    client = _client()
    coord = _coordinator(hass, client)
    start = time.time()
    coord.data = EcosHubData(metrics=_metrics(timedelta(0)))
    client.async_get_latest_metrics.side_effect = EcosHubConnectionError("5000")

    elapsed = 0.0
    served_stale_until = 0.0
    for _ in range(30):
        with patch(
            "custom_components.ecos_hub.coordinator.time.time",
            return_value=start + elapsed,
        ):
            try:
                coord.data = await coord._async_update_data()
                served_stale_until = elapsed
            except UpdateFailed:
                break
        elapsed += coord.update_interval.total_seconds()
    else:
        pytest.fail("never went unavailable")

    assert served_stale_until < MAX_STALE_DATA.total_seconds()
    # Detection happens no later than one base interval after the limit.
    assert elapsed <= MAX_STALE_DATA.total_seconds() + coord._base_interval.total_seconds()


async def test_device_stopped_uploading(hass: HomeAssistant) -> None:
    """The API answers fine, but the newest sample is old: unavailable."""
    client = _client()
    coord = _coordinator(hass, client)
    client.async_get_latest_metrics.return_value = _metrics(timedelta(minutes=12))
    with pytest.raises(UpdateFailed, match="has not reported"):
        await coord._async_update_data()


async def test_device_reporting_normally(hass: HomeAssistant) -> None:
    client = _client()
    coord = _coordinator(hass, client)
    client.async_get_latest_metrics.return_value = _metrics(timedelta(seconds=20))
    data = await coord._async_update_data()
    assert data.metrics["bat_soc"] == 55


async def test_empty_rows_reuse_previous_only_while_fresh(hass: HomeAssistant) -> None:
    client = _client()
    coord = _coordinator(hass, client)
    client.async_get_latest_metrics.return_value = {}

    coord.data = EcosHubData(metrics=_metrics(timedelta(minutes=2)))
    data = await coord._async_update_data()
    assert data.metrics["bat_soc"] == 55

    coord.data = EcosHubData(metrics=_metrics(timedelta(minutes=11)))
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_missing_sample_time_falls_back_to_last_success(
    hass: HomeAssistant,
) -> None:
    client = _client()
    coord = _coordinator(hass, client)
    client.async_get_latest_metrics.return_value = {"bat_soc": 40}
    await coord._async_update_data()
    coord.data = EcosHubData(metrics={"bat_soc": 40})

    client.async_get_latest_metrics.side_effect = EcosHubConnectionError("down")
    later = time.monotonic() + MAX_STALE_DATA.total_seconds() + 1
    with (
        patch(
            "custom_components.ecos_hub.coordinator.time.monotonic",
            return_value=later,
        ),
        pytest.raises(UpdateFailed),
    ):
        await coord._async_update_data()


async def test_backoff_never_outlives_stale_limit(hass: HomeAssistant) -> None:
    client = _client()
    coord = _coordinator(hass, client)
    coord._consecutive_failures = 6  # would normally back off to the 10 min cap
    coord.data = EcosHubData(metrics=_metrics(MAX_STALE_DATA - timedelta(minutes=2)))
    client.async_get_latest_metrics.side_effect = EcosHubConnectionError("5000")

    await coord._async_update_data()
    assert coord.update_interval <= timedelta(minutes=2, seconds=1)


# --- Fund 3: service limits ---------------------------------------------------


@pytest.mark.parametrize("bat_power", [-6000, 0, 6000])
def test_control_mode_accepts_valid_power(bat_power: float) -> None:
    SET_CONTROL_MODE_SCHEMA(
        {"device_id": "x", "mode": "DirectCharge", "bat_power": bat_power}
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("bat_power", 60000),
        ("bat_power", -60000),
        ("ppv_limit", 99999),
        ("ppv_limit", -1),
        ("bat_power_inv_limit", 7000),
        ("timeout", 30),
        ("timeout", 100000),
    ],
)
def test_control_mode_rejects_out_of_range(field: str, value: float) -> None:
    with pytest.raises(vol.Invalid):
        SET_CONTROL_MODE_SCHEMA(
            {"device_id": "x", "mode": "DirectCharge", field: value}
        )


@pytest.mark.parametrize("field", ["charge_power", "discharge_power"])
def test_schedule_power_limits(field: str) -> None:
    SET_CHARGE_SCHEDULE_SCHEMA({"device_id": "x", "period": 1, field: 10000})
    with pytest.raises(vol.Invalid):
        SET_CHARGE_SCHEDULE_SCHEMA({"device_id": "x", "period": 1, field: 10001})


# --- End to end: load the integration in a real HA core ---------------------


async def test_integration_loads_and_rejects_bad_service_call(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.ecos_hub.api.EcosHubClient.async_get_latest_metrics",
            return_value=_metrics(timedelta(seconds=10)),
        ),
        patch(
            "custom_components.ecos_hub.api.EcosHubClient.async_get_device",
            return_value={"device_model": "TIA103"},
        ),
        patch(
            "custom_components.ecos_hub.api.EcosHubClient.async_query_config",
            return_value={"chargeModeCode": "1"},
        ),
        patch(
            "custom_components.ecos_hub.api.EcosHubClient.async_set_control_mode",
        ) as set_mode,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        states = [s for s in hass.states.async_all() if "battery" in s.entity_id]
        assert states, "no battery entities were created"

        from homeassistant.helpers import device_registry as dr

        device = dr.async_get(hass).async_get_device({(DOMAIN, SN)})
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN,
                "set_control_mode",
                {"device_id": device.id, "mode": "DirectDischarge", "bat_power": 50000},
                blocking=True,
            )
        set_mode.assert_not_called()

        await hass.services.async_call(
            DOMAIN,
            "set_control_mode",
            {
                "device_id": device.id,
                "mode": "DirectCharge",
                "bat_power": -3000,
                "timeout": 900,
            },
            blocking=True,
        )
        set_mode.assert_called_once()
