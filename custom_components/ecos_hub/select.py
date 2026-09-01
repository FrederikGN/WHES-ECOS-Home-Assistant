"""Select platform: apply a VPP control mode."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EcosHubConfigEntry
from .const import (
    BATTERY_MODE_TO_SLUG,
    BATTERY_MODES,
    MODE_SLUGS,
    MODE_TO_SLUG,
)
from .coordinator import EcosHubCoordinator
from .entity import EcosHubConfigEntity, EcosHubControlEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcosHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the selectors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EcosHubModeSelect(coordinator),
            EcosHubBatteryModeSelect(coordinator),
        ]
    )


class EcosHubModeSelect(EcosHubControlEntity, SelectEntity):
    """Choose the VPP control mode.

    Selecting a mode sends it immediately, using whatever the staged number
    entities currently hold for power, limits and timeout.

    The API has no endpoint to read the active mode back, so this reflects the
    last mode *this integration* applied. It shows unknown after a restart, and
    it will not notice changes made from the ECOS app.

    Options are lowercase slugs because Home Assistant requires that of state
    translation keys; they map to the API's CamelCase mode names.
    """

    _attr_translation_key = "control_mode"
    _attr_options: ClassVar[list[str]] = list(MODE_SLUGS)

    def __init__(self, coordinator: EcosHubCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_sn}_control_mode"

    @property
    def current_option(self) -> str | None:
        """The last mode we applied, as a slug."""
        mode = self.coordinator.last_control_mode
        return MODE_TO_SLUG.get(mode) if mode else None

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen mode."""
        await self.coordinator.async_set_control_mode(MODE_SLUGS[option])


class EcosHubBatteryModeSelect(EcosHubConfigEntity, SelectEntity):
    """The inverter's battery operating mode.

    Unlike the VPP selector this reads the device's actual state back, so it
    reflects changes made in the ECOS app too. The setting is persistent -- the
    inverter will not revert on its own.
    """

    _attr_translation_key = "battery_mode"
    _attr_options: ClassVar[list[str]] = list(BATTERY_MODES)

    def __init__(self, coordinator: EcosHubCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_sn}_battery_mode"

    @property
    def current_option(self) -> str | None:
        """The mode the inverter reports."""
        if not self.coordinator.data:
            return None
        code = self.coordinator.data.config.get("chargeModeCode")
        return BATTERY_MODE_TO_SLUG.get(str(code)) if code is not None else None

    async def async_select_option(self, option: str) -> None:
        """Write the chosen mode to the inverter."""
        await self.coordinator.async_write_battery_config(
            chargeModeCode=BATTERY_MODES[option]
        )
