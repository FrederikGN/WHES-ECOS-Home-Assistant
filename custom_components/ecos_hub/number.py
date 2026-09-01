"""Number platform: staged parameters for VPP control."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
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
    DEFAULT_PROTECT_SOC,
    DEFAULT_PV_POWER_LIMIT,
    DEFAULT_RELEASE_SOC,
    MAX_BATTERY_POWER,
    MAX_CONTROL_TIMEOUT,
    MIN_BATTERY_POWER,
    MIN_CONTROL_TIMEOUT,
)
from .coordinator import EcosHubCoordinator
from .entity import EcosHubConfigEntity, EcosHubControlEntity


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


@dataclass(frozen=True, kw_only=True)
class EcosHubConfigNumberDescription(NumberEntityDescription):
    """Describes a battery setting written straight to the inverter."""

    api_field: str


CONFIG_NUMBERS: tuple[EcosHubConfigNumberDescription, ...] = (
    EcosHubConfigNumberDescription(
        key="battery_min_soc",
        translation_key="battery_min_soc",
        api_field="minBatteryCapacity",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
    EcosHubConfigNumberDescription(
        key="battery_eps_min_soc",
        translation_key="battery_eps_min_soc",
        api_field="epsMinBatteryCapacity",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
    EcosHubConfigNumberDescription(
        key="battery_max_feedin",
        translation_key="battery_max_feedin",
        api_field="maxFeedIn",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)

# Local-only values used by the protect/release buttons.
STAGED_SOC_NUMBERS: tuple[EcosHubNumberDescription, ...] = (
    EcosHubNumberDescription(
        key="protect_soc",
        translation_key="protect_soc",
        param="protect_soc",
        default=DEFAULT_PROTECT_SOC,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
    EcosHubNumberDescription(
        key="release_soc",
        translation_key="release_soc",
        param="release_soc",
        default=DEFAULT_RELEASE_SOC,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcosHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the staged control parameters and the battery settings."""
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = [
        EcosHubNumber(coordinator, description)
        for description in NUMBERS + STAGED_SOC_NUMBERS
    ]
    entities.extend(
        EcosHubConfigNumber(coordinator, description)
        for description in CONFIG_NUMBERS
    )
    async_add_entities(entities)


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

        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value

        self.coordinator.staged[self.entity_description.param] = float(
            self._attr_native_value
        )

    async def async_set_native_value(self, value: float) -> None:
        """Stage a new value."""
        self._attr_native_value = value
        self.coordinator.staged[self.entity_description.param] = value
        self.async_write_ha_state()


class EcosHubConfigNumber(EcosHubConfigEntity, NumberEntity):
    """A battery setting read from and written to the inverter.

    Changing one of these writes immediately, unlike the staged VPP numbers.
    The value shown is what the inverter reports, so a change made in the ECOS
    app or by WHES AI appears here on the next configuration refresh.
    """

    entity_description: EcosHubConfigNumberDescription

    def __init__(
        self,
        coordinator: EcosHubCoordinator,
        description: EcosHubConfigNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_sn}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """The value the inverter reports."""
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.config.get(self.entity_description.api_field)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Write the new value to the inverter."""
        await self.coordinator.async_write_battery_config(
            **{self.entity_description.api_field: int(value)}
        )
