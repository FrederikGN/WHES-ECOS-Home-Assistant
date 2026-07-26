"""Constants for the WHES ECOS Hub integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ecos_hub"

CONF_ACCESS_KEY: Final = "access_key"
CONF_ACCESS_SECRET: Final = "access_secret"
CONF_HOST: Final = "host"
CONF_DEVICE_SN: Final = "device_sn"

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

# The hardware samples roughly every 5 minutes regardless of the sample_by
# parameter, so polling faster only burns API quota.
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=1)

# How far back to ask for metrics. Generous enough to always catch at least one
# sample even if the device missed a few uploads.
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

# Columns requested from the metrics endpoint. Restricted to what this hardware
# actually reports, verified against a live TIA103.
METRIC_COLUMNS: Final = [
    "time",
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
