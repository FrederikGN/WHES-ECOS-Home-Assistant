"""Config flow for the WHES ECOS Hub integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import EcosHubAuthError, EcosHubClient, EcosHubError
from .const import (
    CONF_ACCESS_KEY,
    CONF_ACCESS_SECRET,
    CONF_DEVICE_SN,
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    REGIONS,
)

_LOGGER = logging.getLogger(__name__)

CONF_REGION = "region"

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCESS_KEY): str,
        vol.Required(CONF_ACCESS_SECRET): str,
        vol.Required(CONF_REGION, default="EU"): SelectSelector(
            SelectSelectorConfig(
                options=list(REGIONS),
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


class EcosHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EcosHubOptionsFlow:
        """Return the options flow."""
        return EcosHubOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials and verify them against the API."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = REGIONS[user_input[CONF_REGION]]
            client = EcosHubClient(
                session=async_get_clientsession(self.hass),
                host=host,
                access_key=user_input[CONF_ACCESS_KEY],
                access_secret=user_input[CONF_ACCESS_SECRET],
            )

            try:
                devices = await client.async_get_devices()
            except EcosHubAuthError:
                errors["base"] = "invalid_auth"
            except EcosHubError as err:
                _LOGGER.debug("Connection test failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    self._credentials = {
                        CONF_ACCESS_KEY: user_input[CONF_ACCESS_KEY],
                        CONF_ACCESS_SECRET: user_input[CONF_ACCESS_SECRET],
                        CONF_HOST: host,
                    }
                    self._devices = devices
                    if len(devices) == 1:
                        return await self._async_create(devices[0])
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick which device to add."""
        if user_input is not None:
            selected = next(
                device
                for device in self._devices
                if device.get("device_sn") == user_input[CONF_DEVICE_SN]
            )
            return await self._async_create(selected)

        options = [
            {
                "value": device["device_sn"],
                "label": f"{device.get('device_model') or 'Device'} ({device['device_sn']})",
            }
            for device in self._devices
            if device.get("device_sn")
        ]

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_SN): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def _async_create(self, device: dict[str, Any]) -> ConfigFlowResult:
        """Create the entry for a chosen device."""
        device_sn = device["device_sn"]
        await self.async_set_unique_id(device_sn)
        self._abort_if_unique_id_configured()

        model = (device.get("device_model") or "ECOS Hub").strip()
        return self.async_create_entry(
            title=f"{model} ({device_sn})",
            data={**self._credentials, CONF_DEVICE_SN: device_sn},
        )


class EcosHubOptionsFlow(OptionsFlow):
    """Let the user tune how often we poll."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_SECONDS,
                            max=MAX_SCAN_INTERVAL_SECONDS,
                            step=5,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
