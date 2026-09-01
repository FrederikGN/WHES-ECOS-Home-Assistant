"""Button platform for the WHES ECOS Hub integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EcosHubConfigEntry
from .coordinator import EcosHubCoordinator
from .entity import EcosHubConfigEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcosHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the battery protection buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EcosHubProtectBatteryButton(coordinator),
            EcosHubReleaseBatteryButton(coordinator),
        ]
    )


class EcosHubProtectBatteryButton(EcosHubConfigEntity, ButtonEntity):
    """Raise the discharge floor so the battery cannot supply the house.

    Intended for car charging: with the floor above the current level the
    inverter will not discharge, so the charger draws from the grid instead of
    emptying the house battery.

    The floor is taken from the "Battery protection level" number, so it can be
    tuned without editing anything here.
    """

    _attr_translation_key = "protect_battery"

    def __init__(self, coordinator: EcosHubCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_sn}_protect_battery"

    async def async_press(self) -> None:
        """Apply the protection level."""
        await self.coordinator.async_write_battery_config(
            minBatteryCapacity=int(self.coordinator.staged["protect_soc"])
        )


class EcosHubReleaseBatteryButton(EcosHubConfigEntity, ButtonEntity):
    """Lower the discharge floor again so the battery can supply the house."""

    _attr_translation_key = "release_battery"

    def __init__(self, coordinator: EcosHubCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_sn}_release_battery"

    async def async_press(self) -> None:
        """Restore the normal floor."""
        await self.coordinator.async_write_battery_config(
            minBatteryCapacity=int(self.coordinator.staged["release_soc"])
        )
