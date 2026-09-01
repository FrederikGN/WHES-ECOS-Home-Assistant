"""Data update coordinator for the ECOS Hub integration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    EcosHubApiError,
    EcosHubAuthError,
    EcosHubClient,
    EcosHubControlForbidden,
    EcosHubError,
)
from .const import (
    BACKOFF_MAX_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONFIG_MODULE_BATTERY,
    CONFIG_REFRESH_SECONDS,
    DEFAULT_BATTERY_POWER,
    DEFAULT_CONTROL_TIMEOUT,
    DEFAULT_MAX_FEEDIN_LIMIT,
    DEFAULT_MIN_BATTERY_CAPACITY,
    DEFAULT_PROTECT_SOC,
    DEFAULT_PV_POWER_LIMIT,
    DEFAULT_RELEASE_SOC,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SEGMENTS,
    MAX_TOLERATED_FAILURES,
    METRIC_COLUMNS,
    METRICS_LOOKBACK,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class EcosHubData:
    """Everything the entities read from."""

    metrics: dict[str, Any] = field(default_factory=dict)
    device: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


class EcosHubCoordinator(DataUpdateCoordinator[EcosHubData]):
    """Poll the ECOS Hub API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: EcosHubClient,
        device_sn: str,
    ) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {device_sn}",
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.client = client
        self.device_sn = device_sn
        # Device metadata changes rarely. Refresh it roughly every 10 minutes
        # regardless of how fast metrics are polled.
        self._device_refresh_every = max(1, int(600 / max(interval, 1)))
        self._device_info_countdown = 0

        # Battery configuration only changes when something writes it, so it is
        # read far less often than the metrics.
        self._config_refresh_every = max(
            1, int(CONFIG_REFRESH_SECONDS / max(interval, 1))
        )
        self._config_countdown = 0
        # Set when the account lacks device-level permissions, so the
        # configuration entities can mark themselves unavailable.
        self.config_available = True

        # Transient upstream failures are tolerated for a while before the
        # entities are marked unavailable.
        self._consecutive_failures = 0
        self._base_interval = timedelta(seconds=interval)

        # Set once the API tells us VPP control is not provisioned, so the
        # control entities can stop pretending they work.
        self.control_forbidden = False
        self.last_control_mode: str | None = None

        # Staged parameters. The select entity and the service read these, so a
        # user can dial in power and limits before choosing a mode.
        self.staged: dict[str, float] = {
            "protect_soc": DEFAULT_PROTECT_SOC,
            "release_soc": DEFAULT_RELEASE_SOC,
            "bat_power": DEFAULT_BATTERY_POWER,
            "bat_cap_min": DEFAULT_MIN_BATTERY_CAPACITY,
            "max_feedin_limit": DEFAULT_MAX_FEEDIN_LIMIT,
            "ppv_limit": DEFAULT_PV_POWER_LIMIT,
            "bat_power_inv_limit": DEFAULT_PV_POWER_LIMIT,
            "timeout": DEFAULT_CONTROL_TIMEOUT,
        }

    async def async_set_control_mode(self, mode: str, **overrides: float) -> None:
        """Apply a VPP control mode using staged values for anything omitted."""
        params = {**self.staged, **{k: v for k, v in overrides.items() if v is not None}}

        try:
            await self.client.async_set_control_mode(self.device_sn, mode, **params)
        except EcosHubControlForbidden as err:
            self.control_forbidden = True
            self.async_update_listeners()
            raise HomeAssistantError(str(err)) from err
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        except EcosHubError as err:
            raise HomeAssistantError(f"Could not set control mode: {err}") from err

        self.last_control_mode = mode
        self.async_update_listeners()

    def _apply_backoff(self) -> None:
        """Slow polling down while the API is failing.

        Doubles the interval per consecutive failure up to the ceiling. A
        multi-hour outage at the normal interval would otherwise mean hundreds
        of pointless requests.
        """
        backed_off = self._base_interval * (2**self._consecutive_failures)
        new_interval = min(backed_off, BACKOFF_MAX_INTERVAL)

        if new_interval != self.update_interval:
            _LOGGER.debug(
                "Backing off to %s after %d consecutive failures",
                new_interval,
                self._consecutive_failures,
            )
            self.update_interval = new_interval

    async def _async_update_data(self) -> EcosHubData:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - int(METRICS_LOOKBACK.total_seconds() * 1000)

        previous = self.data or EcosHubData()

        try:
            metrics = await self.client.async_get_latest_metrics(
                self.device_sn, start_ms, now_ms, METRIC_COLUMNS
            )
        except EcosHubAuthError as err:
            # Bad credentials will not fix themselves, so fail immediately.
            self._consecutive_failures = 0
            raise UpdateFailed(f"Authentication rejected: {err}") from err
        except EcosHubError as err:
            # The upstream API returns transient 5000 "Internal error"
            # responses, notably around its nightly maintenance window. Riding
            # those out keeps every entity from going unavailable over a blip.
            self._consecutive_failures += 1
            self._apply_backoff()

            if self._consecutive_failures <= MAX_TOLERATED_FAILURES and previous.metrics:
                _LOGGER.warning(
                    "Could not fetch metrics (attempt %d of %d before giving up): %s",
                    self._consecutive_failures,
                    MAX_TOLERATED_FAILURES,
                    err,
                )
                return previous

            raise UpdateFailed(
                f"Could not fetch metrics after {self._consecutive_failures} "
                f"attempts: {err}"
            ) from err

        if self._consecutive_failures:
            _LOGGER.info(
                "Metrics recovered after %d failed attempt(s)",
                self._consecutive_failures,
            )
            self._consecutive_failures = 0
            self.update_interval = self._base_interval

        # A device that is briefly offline returns no rows. Keep the previous
        # readings rather than blanking every entity.
        if not metrics:
            metrics = previous.metrics

        # Device metadata (firmware, model, state) changes rarely.
        device = previous.device
        if self._device_info_countdown <= 0 or not device:
            try:
                device = await self.client.async_get_device(self.device_sn)
                self._device_info_countdown = self._device_refresh_every
            except EcosHubApiError as err:
                # Non-fatal: metrics are what matter.
                _LOGGER.debug("Could not refresh device details: %s", err)
            except EcosHubError as err:
                _LOGGER.debug("Could not refresh device details: %s", err)
        else:
            self._device_info_countdown -= 1

        config = previous.config
        if self._config_countdown <= 0 or not config:
            try:
                config = await self.client.async_query_config(
                    self.device_sn, CONFIG_MODULE_BATTERY
                )
                self.config_available = True
                self._config_countdown = self._config_refresh_every
            except EcosHubError as err:
                # Device-level permissions are a separate grant from the
                # metrics feed, so this can fail while everything else works.
                if self.config_available:
                    _LOGGER.info("Battery configuration unavailable: %s", err)
                self.config_available = False
                self._config_countdown = self._config_refresh_every
        else:
            self._config_countdown -= 1

        return EcosHubData(metrics=metrics, device=device, config=config)

    async def async_write_battery_config(self, **fields: Any) -> None:
        """Write battery settings and refresh so entities show the truth."""
        try:
            await self.client.async_set_battery_config(self.device_sn, **fields)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        except EcosHubError as err:
            raise HomeAssistantError(f"Could not write battery config: {err}") from err

        # Force a re-read on the next cycle rather than trusting our own write:
        # WHES AI and the ECOS app write the same settings and may override us.
        self._config_countdown = 0
        await self.async_request_refresh()

    async def async_write_segment(
        self, index: int, changes: dict[str, Any]
    ) -> None:
        """Update one scheduled period, leaving the other eleven untouched.

        Periods are positional, so the whole list has to be sent every time.
        The current list is re-read first so a concurrent change by the app or
        by WHES AI is not silently reverted.
        """
        config = await self.client.async_query_config(
            self.device_sn, CONFIG_MODULE_BATTERY
        )
        segments = list(config.get("segments") or [])

        while len(segments) < MAX_SEGMENTS:
            segments.append({})
        segments = segments[:MAX_SEGMENTS]

        if not 1 <= index <= MAX_SEGMENTS:
            raise HomeAssistantError(
                f"Period must be between 1 and {MAX_SEGMENTS}, got {index}"
            )

        target = dict(segments[index - 1])
        target.update({k: v for k, v in changes.items() if v is not None})
        segments[index - 1] = target

        await self.async_write_battery_config(segments=segments)
