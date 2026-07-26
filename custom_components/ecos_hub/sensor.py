"""Sensor platform for the WHES ECOS Hub integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EcosHubConfigEntry
from .const import DEVICE_STATE, RUN_MODE
from .coordinator import EcosHubCoordinator, EcosHubData
from .entity import EcosHubEntity


def _number(value: Any) -> float | None:
    """Coerce an API value to a float, treating junk as unavailable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric(key: str) -> Callable[[EcosHubData], float | None]:
    return lambda data: _number(data.metrics.get(key))


def _solar_power(data: EcosHubData) -> float | None:
    """Combined PV power across both strings."""
    values = [_number(data.metrics.get(key)) for key in ("pv1_p", "pv2_p")]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _battery_charge_power(data: EcosHubData) -> float | None:
    """Charging power only (0 while discharging)."""
    value = _number(data.metrics.get("bat_p"))
    return max(value, 0.0) if value is not None else None


def _battery_discharge_power(data: EcosHubData) -> float | None:
    """Discharging power as a positive number (0 while charging)."""
    value = _number(data.metrics.get("bat_p"))
    return max(-value, 0.0) if value is not None else None


def _run_mode(data: EcosHubData) -> str | None:
    value = _number(data.metrics.get("sys_run_mode"))
    return RUN_MODE.get(int(value)) if value is not None else None


def _device_state(data: EcosHubData) -> str | None:
    value = data.device.get("state")
    if value is None:
        return None
    try:
        return DEVICE_STATE.get(int(value))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class EcosHubSensorDescription(SensorEntityDescription):
    """Describes an ECOS Hub sensor."""

    value_fn: Callable[[EcosHubData], float | str | None]


POWER_SENSORS: tuple[EcosHubSensorDescription, ...] = (
    EcosHubSensorDescription(
        key="solar_power",
        translation_key="solar_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_solar_power,
    ),
    EcosHubSensorDescription(
        key="pv1_power",
        translation_key="pv1_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_metric("pv1_p"),
    ),
    EcosHubSensorDescription(
        key="pv2_power",
        translation_key="pv2_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_metric("pv2_p"),
    ),
    EcosHubSensorDescription(
        key="inverter_power",
        translation_key="inverter_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_metric("ac_p"),
    ),
    EcosHubSensorDescription(
        key="grid_power",
        translation_key="grid_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_metric("meter_p"),
    ),
    EcosHubSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_metric("bat_p"),
    ),
    EcosHubSensorDescription(
        key="battery_charge_power",
        translation_key="battery_charge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_battery_charge_power,
    ),
    EcosHubSensorDescription(
        key="battery_discharge_power",
        translation_key="battery_discharge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_battery_discharge_power,
    ),
    EcosHubSensorDescription(
        key="backup_power",
        translation_key="backup_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_metric("eps_p"),
    ),
)

BATTERY_SENSORS: tuple[EcosHubSensorDescription, ...] = (
    EcosHubSensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_metric("bat_soc"),
    ),
    EcosHubSensorDescription(
        key="battery_soh",
        translation_key="battery_soh",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_metric("bat_soh"),
    ),
    EcosHubSensorDescription(
        key="battery_available_energy",
        translation_key="battery_available_energy",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=_metric("bat_available_energy"),
    ),
    EcosHubSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_metric("bat_v"),
    ),
    EcosHubSensorDescription(
        key="battery_current",
        translation_key="battery_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_metric("bat_i"),
    ),
)

ENERGY_SENSORS: tuple[EcosHubSensorDescription, ...] = (
    EcosHubSensorDescription(
        key="energy_from_grid",
        translation_key="energy_from_grid",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_metric("electricity_e_total_from_grid"),
    ),
    EcosHubSensorDescription(
        key="energy_to_grid",
        translation_key="energy_to_grid",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_metric("electricity_e_total_to_grid"),
    ),
    EcosHubSensorDescription(
        key="energy_battery_charged",
        translation_key="energy_battery_charged",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_metric("electricity_e_total_charge"),
    ),
    EcosHubSensorDescription(
        key="energy_battery_discharged",
        translation_key="energy_battery_discharged",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_metric("electricity_e_total_discharge"),
    ),
    EcosHubSensorDescription(
        key="energy_backup",
        translation_key="energy_backup",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_metric("electricity_e_total_eps"),
    ),
)

GRID_SENSORS: tuple[EcosHubSensorDescription, ...] = (
    EcosHubSensorDescription(
        key="grid_voltage",
        translation_key="grid_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_metric("ac_v"),
    ),
    EcosHubSensorDescription(
        key="grid_current",
        translation_key="grid_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_metric("ac_i"),
    ),
    EcosHubSensorDescription(
        key="grid_frequency",
        translation_key="grid_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_metric("ac_f"),
    ),
)

STATUS_SENSORS: tuple[EcosHubSensorDescription, ...] = (
    EcosHubSensorDescription(
        key="inverter_temperature",
        translation_key="inverter_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_metric("sys_inv_sink_t"),
    ),
    EcosHubSensorDescription(
        key="run_mode",
        translation_key="run_mode",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(RUN_MODE.values())),
        value_fn=_run_mode,
    ),
    EcosHubSensorDescription(
        key="device_state",
        translation_key="device_state",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(DEVICE_STATE.values())),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_device_state,
    ),
)

SENSORS: tuple[EcosHubSensorDescription, ...] = (
    POWER_SENSORS + BATTERY_SENSORS + ENERGY_SENSORS + GRID_SENSORS + STATUS_SENSORS
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcosHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        EcosHubSensor(coordinator, description) for description in SENSORS
    )


class EcosHubSensor(EcosHubEntity, SensorEntity):
    """A single ECOS Hub measurement."""

    entity_description: EcosHubSensorDescription

    def __init__(
        self,
        coordinator: EcosHubCoordinator,
        description: EcosHubSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_sn}_{description.key}"

    @property
    def native_value(self) -> float | str | None:
        """Return the current reading."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Report unavailable when we have no data at all."""
        if not super().available or self.coordinator.data is None:
            return False
        return bool(self.coordinator.data.metrics or self.coordinator.data.device)
