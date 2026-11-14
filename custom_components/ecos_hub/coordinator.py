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
    MAX_STALE_DATA,
    METRIC_COLUMNS,
    METRICS_LOOKBACK,
    PRESERVED_BATTERY_FIELDS,
)

_LOGGER = logging.getLogger(__name__)


def _whole_seconds(delta: timedelta) -> timedelta:
    """Drop the microseconds so log lines stay readable."""
    return timedelta(seconds=int(delta.total_seconds()))


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

        # Transient upstream failures are tolerated until the newest reading is
        # MAX_STALE_DATA old, then the entities are marked unavailable.
        self._consecutive_failures = 0
        self._base_interval = timedelta(seconds=interval)
        # Monotonic time of the last successful metrics fetch. Only used to age
        # the data when the API does not say when the newest sample was taken.
        self._last_success: float | None = None

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

    def _data_age(self, metrics: dict[str, Any]) -> timedelta | None:
        """How old the newest reading in ``metrics`` is.

        Taken from the sample timestamp the API returns, so a device that has
        stopped uploading ages even while the API itself answers fine. Falls
        back to the time of the last successful fetch when the timestamp is
        missing, and to None when there has never been one.
        """
        try:
            sample_ms = float(metrics.get("_sample_time"))
        except (TypeError, ValueError):
            sample_ms = None

        if sample_ms is not None:
            return timedelta(seconds=max(0.0, time.time() - sample_ms / 1000))
        if self._last_success is not None:
            return timedelta(seconds=time.monotonic() - self._last_success)
        return None

    def _apply_backoff(self, deadline: timedelta | None = None) -> None:
        """Slow polling down while the API is failing.

        Doubles the interval per consecutive failure up to the ceiling. A
        multi-hour outage at the normal interval would otherwise mean hundreds
        of pointless requests.

        ``deadline`` is how long the readings currently shown may still be
        trusted. The next poll is never scheduled later than that, so stale
        data cannot outlive MAX_STALE_DATA just because polling slowed down.
        """
        backed_off = self._base_interval * (2**self._consecutive_failures)
        new_interval = min(backed_off, BACKOFF_MAX_INTERVAL)
        if deadline is not None:
            new_interval = min(new_interval, max(self._base_interval, deadline))

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
            # those out keeps every entity from going unavailable over a blip,
            # but only until the readings are MAX_STALE_DATA old.
            self._consecutive_failures += 1
            age = self._data_age(previous.metrics)

            if previous.metrics and age is not None and age < MAX_STALE_DATA:
                self._apply_backoff(deadline=MAX_STALE_DATA - age)
                _LOGGER.warning(
                    "Could not fetch metrics (attempt %d); keeping readings "
                    "that are %s old, for at most %s: %s",
                    self._consecutive_failures,
                    _whole_seconds(age),
                    MAX_STALE_DATA,
                    err,
                )
                return previous

            self._apply_backoff()
            raise UpdateFailed(
                f"Could not fetch metrics after {self._consecutive_failures} "
                f"attempt(s): {err}"
            ) from err

        if self._consecutive_failures:
            _LOGGER.info(
                "Metrics recovered after %d failed attempt(s)",
                self._consecutive_failures,
            )
            self._consecutive_failures = 0
            self.update_interval = self._base_interval
        self._last_success = time.monotonic()

        # A device that is briefly offline returns no rows. Keep the previous
        # readings rather than blanking every entity -- until they are too old.
        if not metrics:
            metrics = previous.metrics

        age = self._data_age(metrics)
        if age is not None and age >= MAX_STALE_DATA:
            raise UpdateFailed(
                f"The device has not reported for {_whole_seconds(age)}; "
                f"readings older than {MAX_STALE_DATA} are not shown"
            )

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
        """Change specific battery settings, leaving everything else alone.

        The documentation says omitted fields are optional, but in practice a
        partial write resets the fields that were left out -- changing only the
        discharge floor was observed to also change the operating mode. So the
        current settings are read immediately beforehand and sent back
        unchanged, with the requested change layered on top.

        That costs one extra request per write and closes a small window where
        a concurrent change by the ECOS app could be reverted, but it is far
        better than silently altering settings the user did not touch.
        """
        try:
            current = await self.client.async_query_config(
                self.device_sn, CONFIG_MODULE_BATTERY
            )
        except EcosHubError as err:
            raise HomeAssistantError(
                f"Could not read current battery config before writing: {err}"
            ) from err

        payload: dict[str, Any] = {}
        for key in PRESERVED_BATTERY_FIELDS:
            if current.get(key) is not None:
                payload[key] = current[key]

        segments = current.get("segments")
        if segments:
            payload["segments"] = segments

        payload.update(fields)

        try:
            await self.client.async_set_battery_config(self.device_sn, **payload)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        except EcosHubError as err:
            raise HomeAssistantError(f"Could not write battery config: {err}") from err

        # Re-read rather than trusting our own write: WHES AI and the ECOS app
        # write the same settings and may override us.
        self._config_countdown = 0
        await self.async_request_refresh()

    async def async_write_segment(
        self, index: int, changes: dict[str, Any]
    ) -> None:
        """Update one scheduled period, leaving the other eleven untouched.

        Periods are positional, so the whole list is sent every time. The write
        path re-reads the current configuration anyway, so the list is taken
        from there.
        """
        if not 1 <= index <= MAX_SEGMENTS:
            raise HomeAssistantError(
                f"Period must be between 1 and {MAX_SEGMENTS}, got {index}"
            )

        try:
            current = await self.client.async_query_config(
                self.device_sn, CONFIG_MODULE_BATTERY
            )
        except EcosHubError as err:
            raise HomeAssistantError(
                f"Could not read current schedule before writing: {err}"
            ) from err

        segments = [dict(s) for s in (current.get("segments") or [])]
        while len(segments) < MAX_SEGMENTS:
            segments.append({})
        segments = segments[:MAX_SEGMENTS]

        segments[index - 1].update(
            {k: v for k, v in changes.items() if v is not None}
        )

        await self.async_write_battery_config(segments=segments)
