"""Shared entity base for the ECOS Hub integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import EcosHubCoordinator


class EcosHubEntity(CoordinatorEntity[EcosHubCoordinator]):
    """Common device grouping for every ECOS Hub entity."""

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Group every entity under one device."""
        device = self.coordinator.data.device if self.coordinator.data else {}
        model = (device.get("device_model") or "ECOS Hub").strip()
        brand = (device.get("brand") or "").strip()

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_sn)},
            name=f"{brand} {model}".strip() or model,
            manufacturer=MANUFACTURER,
            model=model,
            serial_number=self.coordinator.device_sn,
            sw_version=device.get("ems_software_version"),
            hw_version=device.get("ems_hardware_version"),
        )


class EcosHubControlEntity(EcosHubEntity):
    """Base for entities that write to the inverter.

    VPP control has to be provisioned by WHES. Until it is, the API answers
    every write with an upstream 403, so these entities mark themselves
    unavailable once we have seen that rather than offering controls that
    silently fail.
    """

    @property
    def available(self) -> bool:
        """Unavailable when VPP control is not provisioned."""
        return super().available and not self.coordinator.control_forbidden


class EcosHubConfigEntity(EcosHubEntity):
    """Base for entities backed by the device configuration endpoints.

    Device-level configuration access is a separate permission from the
    metrics feed, so these can be unavailable while the sensors work fine.
    """

    @property
    def available(self) -> bool:
        """Unavailable when the configuration cannot be read."""
        if not super().available or not self.coordinator.config_available:
            return False
        return bool(self.coordinator.data and self.coordinator.data.config)
