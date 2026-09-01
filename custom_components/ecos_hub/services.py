"""Service registration for the ECOS Hub integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_BAT_CAP_MIN,
    ATTR_BAT_POWER,
    ATTR_BAT_POWER_INV_LIMIT,
    ATTR_MAX_FEEDIN_LIMIT,
    ATTR_MODE,
    ATTR_PPV_LIMIT,
    ATTR_TIMEOUT,
    CONTROL_MODES,
    DOMAIN,
    MAX_SEGMENTS,
    SERVICE_CLEAR_CHARGE_SCHEDULE,
    SERVICE_SET_CHARGE_SCHEDULE,
    SERVICE_SET_CONTROL_MODE,
)

SET_CONTROL_MODE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_MODE): vol.In(CONTROL_MODES),
        vol.Optional(ATTR_BAT_POWER): vol.Coerce(float),
        vol.Optional(ATTR_BAT_CAP_MIN): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
        vol.Optional(ATTR_MAX_FEEDIN_LIMIT): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
        vol.Optional(ATTR_PPV_LIMIT): vol.Coerce(float),
        vol.Optional(ATTR_BAT_POWER_INV_LIMIT): vol.Coerce(float),
        vol.Optional(ATTR_TIMEOUT): vol.All(
            vol.Coerce(float), vol.Range(min=60, max=86400)
        ),
    }
)


SET_CHARGE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("period"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_SEGMENTS)
        ),
        vol.Optional("charge_start"): cv.time,
        vol.Optional("charge_end"): cv.time,
        vol.Optional("charge_power"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("charge_soc_upper"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional("discharge_start"): cv.time,
        vol.Optional("discharge_end"): cv.time,
        vol.Optional("discharge_power"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("discharge_soc_lower"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional("curtail_pv_while_charging"): cv.boolean,
    }
)

CLEAR_CHARGE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("period"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_SEGMENTS)
        ),
    }
)


def _segment_from_call(data: dict) -> dict:
    """Translate service fields into the API's segment field names."""
    segment: dict[str, int] = {}

    if (start := data.get("charge_start")) is not None:
        segment["chargeBeginHour"] = start.hour
        segment["chargeBeginMinute"] = start.minute
    if (end := data.get("charge_end")) is not None:
        segment["chargeEndHour"] = end.hour
        segment["chargeEndMinute"] = end.minute
    if (power := data.get("charge_power")) is not None:
        segment["chargePower"] = power
    if (soc := data.get("charge_soc_upper")) is not None:
        segment["chargeSocUpper"] = soc

    if (start := data.get("discharge_start")) is not None:
        segment["disChargeBeginHour"] = start.hour
        segment["disChargeBeginMinute"] = start.minute
    if (end := data.get("discharge_end")) is not None:
        segment["disChargeEndHour"] = end.hour
        segment["disChargeEndMinute"] = end.minute
    if (power := data.get("discharge_power")) is not None:
        segment["disChargePower"] = power
    if (soc := data.get("discharge_soc_lower")) is not None:
        segment["disChargeSocLower"] = soc

    if (curtail := data.get("curtail_pv_while_charging")) is not None:
        segment["chargeAbandonPv"] = 1 if curtail else 0

    return segment


# A period is disabled by zeroing every field; there is no "off" flag.
EMPTY_SEGMENT = {
    "chargeBeginHour": 0,
    "chargeBeginMinute": 0,
    "chargeEndHour": 0,
    "chargeEndMinute": 0,
    "chargePower": 0,
    "chargeAbandonPv": 0,
    "disChargeBeginHour": 0,
    "disChargeBeginMinute": 0,
    "disChargeEndHour": 0,
    "disChargeEndMinute": 0,
    "disChargePower": 0,
    "disChargeAbandonPv": 0,
}


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_CONTROL_MODE):
        return

    async def _async_set_control_mode(call: ServiceCall) -> None:
        """Apply a control mode to every targeted ECOS Hub device."""
        registry = dr.async_get(hass)
        coordinators = []

        for device_id in call.data["device_id"]:
            device = registry.async_get(device_id)
            if device is None:
                raise HomeAssistantError(f"Unknown device {device_id}")

            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None or entry.domain != DOMAIN:
                    continue
                # runtime_data only exists while the entry is loaded.
                if (coordinator := getattr(entry, "runtime_data", None)) is not None:
                    coordinators.append(coordinator)

        if not coordinators:
            raise HomeAssistantError(
                "No loaded ECOS Hub device matched the service target"
            )

        overrides = {
            key: value
            for key, value in call.data.items()
            if key not in ("device_id", ATTR_MODE)
        }

        for coordinator in coordinators:
            await coordinator.async_set_control_mode(call.data[ATTR_MODE], **overrides)

    def _coordinators(call: ServiceCall) -> list:
        """Resolve the targeted devices to loaded coordinators."""
        registry = dr.async_get(hass)
        found = []
        for device_id in call.data["device_id"]:
            device = registry.async_get(device_id)
            if device is None:
                raise HomeAssistantError(f"Unknown device {device_id}")
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None or entry.domain != DOMAIN:
                    continue
                if (coordinator := getattr(entry, "runtime_data", None)) is not None:
                    found.append(coordinator)
        if not found:
            raise HomeAssistantError(
                "No loaded ECOS Hub device matched the service target"
            )
        return found

    async def _async_set_charge_schedule(call: ServiceCall) -> None:
        """Write one scheduled charge/discharge period."""
        segment = _segment_from_call(dict(call.data))
        if not segment:
            raise HomeAssistantError(
                "Supply at least one time or power to set on the period"
            )
        for coordinator in _coordinators(call):
            await coordinator.async_write_segment(call.data["period"], segment)

    async def _async_clear_charge_schedule(call: ServiceCall) -> None:
        """Zero one scheduled period, which disables it."""
        for coordinator in _coordinators(call):
            await coordinator.async_write_segment(
                call.data["period"], dict(EMPTY_SEGMENT)
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CONTROL_MODE,
        _async_set_control_mode,
        schema=SET_CONTROL_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CHARGE_SCHEDULE,
        _async_set_charge_schedule,
        schema=SET_CHARGE_SCHEDULE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_CHARGE_SCHEDULE,
        _async_clear_charge_schedule,
        schema=CLEAR_CHARGE_SCHEDULE_SCHEMA,
    )
