"""Switch platform for the WHES ECOS Hub integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
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
    """Set up the battery switches."""
    async_add_entities([EcosHubDischargeToGridSwitch(entry.runtime_data)])


class EcosHubDischargeToGridSwitch(EcosHubConfigEntity, SwitchEntity):
    """Whether the battery may discharge into the grid.

    With this on, the inverter will sell from the battery rather than only
    covering the house. That is what WHES AI uses to trade on price, so
    turning it off will stop the AI selling stored energy.
    """

    _attr_translation_key = "discharge_to_grid"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EcosHubCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_sn}_discharge_to_grid"

    @property
    def is_on(self) -> bool | None:
        """Whether the inverter reports the flag as set."""
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.config.get("dischargeToGridFlag")
        return str(raw) == "1" if raw is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow discharging to the grid."""
        await self.coordinator.async_write_battery_config(dischargeToGridFlag=1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop discharging to the grid."""
        await self.coordinator.async_write_battery_config(dischargeToGridFlag=0)
