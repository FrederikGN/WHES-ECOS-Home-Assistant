"""Select platform: apply a VPP control mode."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EcosHubConfigEntry
from .const import MODE_SLUGS, MODE_TO_SLUG
from .coordinator import EcosHubCoordinator
from .entity import EcosHubControlEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcosHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the control mode selector."""
    async_add_entities([EcosHubModeSelect(entry.runtime_data)])


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
