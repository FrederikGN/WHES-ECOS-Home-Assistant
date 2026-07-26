"""Data update coordinator for the ECOS Hub integration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EcosHubApiError, EcosHubAuthError, EcosHubClient, EcosHubError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    METRIC_COLUMNS,
    METRICS_LOOKBACK,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class EcosHubData:
    """Everything the entities read from."""

    metrics: dict[str, Any] = field(default_factory=dict)
    device: dict[str, Any] = field(default_factory=dict)


class EcosHubCoordinator(DataUpdateCoordinator[EcosHubData]):
    """Poll the ECOS Hub API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: EcosHubClient,
        device_sn: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {device_sn}",
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.device_sn = device_sn
        self._device_info_countdown = 0

    async def _async_update_data(self) -> EcosHubData:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - int(METRICS_LOOKBACK.total_seconds() * 1000)

        previous = self.data or EcosHubData()

        try:
            metrics = await self.client.async_get_latest_metrics(
                self.device_sn, start_ms, now_ms, METRIC_COLUMNS
            )
        except EcosHubAuthError as err:
            raise UpdateFailed(f"Authentication rejected: {err}") from err
        except EcosHubError as err:
            raise UpdateFailed(f"Could not fetch metrics: {err}") from err

        # A device that is briefly offline returns no rows. Keep the previous
        # readings rather than blanking every entity.
        if not metrics:
            metrics = previous.metrics

        # Device metadata (firmware, model, state) changes rarely; refresh it
        # about every 10 minutes.
        device = previous.device
        if self._device_info_countdown <= 0 or not device:
            try:
                device = await self.client.async_get_device(self.device_sn)
                self._device_info_countdown = 10
            except EcosHubApiError as err:
                # Non-fatal: metrics are what matter.
                _LOGGER.debug("Could not refresh device details: %s", err)
            except EcosHubError as err:
                _LOGGER.debug("Could not refresh device details: %s", err)
        else:
            self._device_info_countdown -= 1

        return EcosHubData(metrics=metrics, device=device)
