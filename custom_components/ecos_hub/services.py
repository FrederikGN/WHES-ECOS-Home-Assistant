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

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CONTROL_MODE,
        _async_set_control_mode,
        schema=SET_CONTROL_MODE_SCHEMA,
    )
