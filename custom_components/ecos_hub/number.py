"""Number platform: staged parameters for VPP control."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EcosHubConfigEntry
from .const import (
    DEFAULT_BATTERY_POWER,
    DEFAULT_CONTROL_TIMEOUT,
    DEFAULT_MAX_FEEDIN_LIMIT,
    DEFAULT_MIN_BATTERY_CAPACITY,
    DEFAULT_PV_POWER_LIMIT,
    MAX_BATTERY_POWER,
    MAX_CONTROL_TIMEOUT,
    MIN_BATTERY_POWER,
    MIN_CONTROL_TIMEOUT,
)
from .coordinator import EcosHubCoordinator
from .entity import EcosHubControlEntity


@dataclass(frozen=True, kw_only=True)
class EcosHubNumberDescription(NumberEntityDescription):
    """Describes a staged control parameter."""

    param: str
    default: float


NUMBERS: tuple[EcosHubNumberDescription, ...] = (
    EcosHubNumberDescription(
        key="battery_power",
        translation_key="battery_power_setpoint",
        param="bat_power",
        default=DEFAULT_BATTERY_POWER,
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=MIN_BATTERY_POWER,
        native_max_value=MAX_BATTERY_POWER,
        native_step=100,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    EcosHubNumberDescription(
        key="min_battery_capacity",
        translation_key="min_battery_capacity",
        param="bat_cap_min",
        default=DEFAULT_MIN_BATTERY_CAPACITY,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
    EcosHubNumberDescription(
        key="max_feedin_limit",
        translation_key="max_feedin_limit",
        param="max_feedin_limit",
        default=DEFAULT_MAX_FEEDIN_LIMIT,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
    EcosHubNumberDescription(
        key="pv_power_limit",
        translation_key="pv_power_limit",
        param="ppv_limit",
        default=DEFAULT_PV_POWER_LIMIT,
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=MAX_BATTERY_POWER,
        native_step=100,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    EcosHubNumberDescription(
        key="control_timeout",
        translation_key="control_timeout",
        param="timeout",
        default=DEFAULT_CONTROL_TIMEOUT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=MIN_CONTROL_TIMEOUT,
        native_max_value=MAX_CONTROL_TIMEOUT,
        native_step=60,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcosHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the staged control parameters."""
    coordinator = entry.runtime_data
    async_add_entities(
        EcosHubNumber(coordinator, description) for description in NUMBERS
    )


class EcosHubNumber(EcosHubControlEntity, RestoreNumber):
    """A parameter that is staged locally and sent when a mode is applied.

    Changing one of these does not talk to the inverter on its own; the value
    is used the next time a control mode is applied. That keeps a slider drag
    from firing a dozen commands at the hardware.
    """

    entity_description: EcosHubNumberDescription

    def __init__(
        self,
        coordinator: EcosHubCoordinator,
        description: EcosHubNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_sn}_{description.key}"
        self._attr_native_value = description.default

    async def async_added_to_hass(self) -> None:
        """Restore the previous value and push it into the staged parameters."""
        await super().async_added_to_hass()

        if (last := await self.async_get_last_number_data()) is not None:
            if last.native_value is not None:
                self._attr_native_value = last.native_value

        self.coordinator.staged[self.entity_description.param] = float(
            self._attr_native_value
        )

    async def async_set_native_value(self, value: float) -> None:
        """Stage a new value."""
        self._attr_native_value = value
        self.coordinator.staged[self.entity_description.param] = value
        self.async_write_ha_state()
