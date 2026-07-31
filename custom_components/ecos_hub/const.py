"""Constants for the WHES ECOS Hub integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ecos_hub"

CONF_ACCESS_KEY: Final = "access_key"
CONF_ACCESS_SECRET: Final = "access_secret"
CONF_HOST: Final = "host"
CONF_DEVICE_SN: Final = "device_sn"
CONF_SCAN_INTERVAL: Final = "scan_interval"

# Regional API gateways. The docs never state these; EU was verified against a
# live account, the others follow the same naming convention as the ECOS app
# hosts (api-ecos-eu / -au / -hu .weiheng-tech.com) and are unverified.
HOST_EU: Final = "https://open-api-eu.weiheng-tech.com"
HOST_AU: Final = "https://open-api-au.weiheng-tech.com"
HOST_CN: Final = "https://open-api-hu.weiheng-tech.com"

REGIONS: Final = {
    "EU": HOST_EU,
    "AU": HOST_AU,
    "CN": HOST_CN,
}

DEFAULT_HOST: Final = HOST_EU

# The docs write paths as "ecos-hub/v1/...", omitting this prefix. The real
# gateway requires it.
API_PREFIX: Final = "/open-api/ecos-hub/v1"

# The device uploads a fresh sample roughly every 10 seconds, so that is the
# useful floor -- polling faster just re-fetches the same row.
#
# Do NOT send "sample_by" with metrics requests: it downsamples rather than
# refines, and asking for "1m" was observed to return one row per 5 minutes.
DEFAULT_SCAN_INTERVAL_SECONDS: Final = 30
MIN_SCAN_INTERVAL_SECONDS: Final = 10
MAX_SCAN_INTERVAL_SECONDS: Final = 600
DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS)

# How far back to ask for metrics. Rows are sparse -- a given field may only be
# written every few minutes -- and we merge backwards to fill the gaps, so this
# window needs to be comfortably longer than the slowest-updating field.
METRICS_LOOKBACK: Final = timedelta(minutes=30)

MANUFACTURER: Final = "WEIHENG"

# Device state codes from the device-list endpoint.
DEVICE_STATE: Final = {
    -5: "unknown",
    -4: "disabled",
    -3: "not_activated",
    -1: "offline",
    0: "standby",
    1: "on_grid",
    2: "eps",
    3: "fault",
    4: "reserved",
    5: "self_check",
}

# sys_run_mode from the metrics endpoint.
RUN_MODE: Final = {
    0: "waiting_for_grid",
    1: "on_grid",
    2: "off_grid",
    3: "fault",
    4: "reserved",
    5: "self_check",
}

# --- VPP control -----------------------------------------------------------
#
# PUT /open-api/ecos-hub/v1/devices/{sn}/vpp/control-mode
#
# CAUTION: bat_power uses the OPPOSITE sign convention to the bat_p metric.
# Here a negative value charges the battery and a positive value discharges it;
# in the metrics feed bat_p is positive while charging. Mixing these up sends
# the battery in the wrong direction.
MODE_SELF_CONSUMPTION: Final = "SelfConsumption"
MODE_DIRECT_CHARGE: Final = "DirectCharge"
MODE_DIRECT_DISCHARGE: Final = "DirectDischarge"
MODE_CHARGE_ONLY: Final = "ChargeOnly"
MODE_DISCHARGE_TO_LOAD_ONLY: Final = "DischargeToLoadOnly"
MODE_INVERTER_OUTPUTS: Final = "InverterOutputs"
MODE_INVERTER_OPERATES: Final = "InverterOperates"

# Parameters the API requires for each mode, per the ECOS Hub documentation.
MODE_REQUIRED_PARAMS: Final[dict[str, tuple[str, ...]]] = {
    MODE_SELF_CONSUMPTION: ("max_feedin_limit", "bat_cap_min"),
    MODE_DIRECT_CHARGE: ("bat_power", "timeout", "bat_cap_min"),
    MODE_DIRECT_DISCHARGE: ("bat_power", "ppv_limit", "timeout", "bat_cap_min"),
    MODE_CHARGE_ONLY: ("max_feedin_limit", "timeout", "bat_cap_min"),
    MODE_DISCHARGE_TO_LOAD_ONLY: ("max_feedin_limit", "timeout", "bat_cap_min"),
    MODE_INVERTER_OUTPUTS: (
        "bat_power",
        "bat_power_inv_limit",
        "timeout",
        "bat_cap_min",
    ),
    MODE_INVERTER_OPERATES: ("bat_power", "timeout", "bat_cap_min"),
}

CONTROL_MODES: Final = tuple(MODE_REQUIRED_PARAMS)

# Home Assistant requires entity state translation keys to be lowercase slugs,
# so the select entity exposes slugs and maps them to the API's CamelCase mode
# names. The service keeps the API names, since those are what the WHES docs
# use.
MODE_SLUGS: Final[dict[str, str]] = {
    "self_consumption": MODE_SELF_CONSUMPTION,
    "direct_charge": MODE_DIRECT_CHARGE,
    "direct_discharge": MODE_DIRECT_DISCHARGE,
    "charge_only": MODE_CHARGE_ONLY,
    "discharge_to_load_only": MODE_DISCHARGE_TO_LOAD_ONLY,
    "inverter_outputs": MODE_INVERTER_OUTPUTS,
    "inverter_operates": MODE_INVERTER_OPERATES,
}

MODE_TO_SLUG: Final[dict[str, str]] = {v: k for k, v in MODE_SLUGS.items()}

# The device reverts to normal operation once the timeout expires, which makes
# it a dead-man's switch: a crashed automation cannot leave the system stuck in
# a forced mode.
DEFAULT_CONTROL_TIMEOUT: Final = 900  # 15 minutes
MIN_CONTROL_TIMEOUT: Final = 60
MAX_CONTROL_TIMEOUT: Final = 86400

DEFAULT_MIN_BATTERY_CAPACITY: Final = 10
DEFAULT_MAX_FEEDIN_LIMIT: Final = 100

# Battery power limits. The documentation quotes different ranges per mode
# (-5000~0 for DirectCharge, 0~6000 for InverterOutputs), so we allow the
# widest documented span and let the device clamp what it cannot do.
MIN_BATTERY_POWER: Final = -6000
MAX_BATTERY_POWER: Final = 6000
DEFAULT_BATTERY_POWER: Final = 0
DEFAULT_PV_POWER_LIMIT: Final = 6000

SERVICE_SET_CONTROL_MODE: Final = "set_control_mode"

ATTR_MODE: Final = "mode"
ATTR_BAT_POWER: Final = "bat_power"
ATTR_MAX_FEEDIN_LIMIT: Final = "max_feedin_limit"
ATTR_PPV_LIMIT: Final = "ppv_limit"
ATTR_BAT_POWER_INV_LIMIT: Final = "bat_power_inv_limit"
ATTR_TIMEOUT: Final = "timeout"
ATTR_BAT_CAP_MIN: Final = "bat_cap_min"

# Columns requested from the metrics endpoint. Restricted to what this hardware
# actually reports, verified against a live TIA103.
#
# "time" must NOT be listed here: the API returns the timestamp automatically
# and rejects the request with "column time not valid" if you ask for it.
METRIC_COLUMNS: Final = [
    "ac_f",
    "ac_i",
    "ac_p",
    "ac_v",
    "bat_available_energy",
    "bat_i",
    "bat_p",
    "bat_soc",
    "bat_soh",
    "bat_v",
    "electricity_e_total_charge",
    "electricity_e_total_discharge",
    "electricity_e_total_eps",
    "electricity_e_total_from_grid",
    "electricity_e_total_to_grid",
    "eps_p",
    "meter_p",
    "pv1_p",
    "pv1_v",
    "pv2_p",
    "pv2_v",
    "sys_inv_sink_t",
    "sys_run_mode",
]
