"""The WHES ECOS Hub integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EcosHubAuthError, EcosHubClient, EcosHubError
from .const import CONF_ACCESS_KEY, CONF_ACCESS_SECRET, CONF_DEVICE_SN, CONF_HOST
from .coordinator import EcosHubCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

EcosHubConfigEntry = ConfigEntry[EcosHubCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EcosHubConfigEntry) -> bool:
    """Set up ECOS Hub from a config entry."""
    client = EcosHubClient(
        session=async_get_clientsession(hass),
        host=entry.data[CONF_HOST],
        access_key=entry.data[CONF_ACCESS_KEY],
        access_secret=entry.data[CONF_ACCESS_SECRET],
    )

    coordinator = EcosHubCoordinator(hass, entry, client, entry.data[CONF_DEVICE_SN])

    try:
        await coordinator.async_config_entry_first_refresh()
    except EcosHubAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except EcosHubError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EcosHubConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: EcosHubConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
