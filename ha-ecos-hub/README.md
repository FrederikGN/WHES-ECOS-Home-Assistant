# WHES ECOS Hub for Home Assistant

Home Assistant integration for solar and battery systems sold under the
**eCactus / Agave** brand and built by **WEIHENG (WHES)**, using the ECOS Hub
Open API. Developed and verified against an **Agave TH TIA103** with a 10 kWh
battery.

Read-only. Charge scheduling is not implemented — use the ECOS app for that.

## What you get

Grouped under one device, ready for the Home Assistant Energy Dashboard.

**Power (live)**

| Entity | Source field |
| --- | --- |
| Solar power | `pv1_p + pv2_p` |
| PV string 1 / 2 power | `pv1_p`, `pv2_p` |
| Inverter power | `ac_p` |
| Grid power | `meter_p` |
| Battery power | `bat_p` (positive = charging) |
| Battery charge / discharge power | derived from `bat_p`, split into two always-positive sensors |
| Backup (EPS) power | `eps_p` |

**Battery**

Battery level (`bat_soc`), health (`bat_soh`), energy available
(`bat_available_energy`), voltage and current.

**Energy totals** — cumulative kWh, `total_increasing`, suitable for the Energy
Dashboard:

`electricity_e_total_from_grid`, `electricity_e_total_to_grid`,
`electricity_e_total_charge`, `electricity_e_total_discharge`,
`electricity_e_total_eps`.

**Diagnostics** — grid voltage / current / frequency, inverter temperature, run
mode, device state.

### Energy Dashboard setup

- **Grid consumption** → *Energy imported from grid*
- **Return to grid** → *Energy exported to grid*
- **Battery in / out** → *Battery energy charged* / *discharged*

There is no cumulative PV total in the API, so solar production has to be
derived. Add a [Riemann sum integration
helper](https://www.home-assistant.io/integrations/integration/) over the
*Solar power* sensor and use that as your solar source.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories**
2. Add this repository's URL, category **Integration**
3. Install **WHES ECOS Hub**, restart Home Assistant
4. **Settings → Devices & Services → Add Integration → WHES ECOS Hub**

### Manual

Copy `custom_components/ecos_hub` into your `config/custom_components/`
directory and restart Home Assistant.

## Configuration

You need an **AccessKey** and **AccessKeySecret** for the WHES Open API. These
are not your ECOS app login — request them from WHES / your installer
(service@whes.com). The setup dialog asks for both plus a region, then lets you
pick which device to add.

Only the **EU** region has been verified against a live account. The AU and CN
hosts follow WHES' naming convention but are untested; open an issue if one
does not resolve.

## How it works

`POST /open-api/ecos-hub/v1/devices/{sn}/metrics` is polled once a minute for
the last 30 minutes of samples, and the newest row is used.

The device uploads a sample roughly **every 5 minutes**, regardless of the
`sample_by` parameter, so values change at that rate no matter how often Home
Assistant polls. If the device misses an upload the previous readings are kept
rather than blanking every entity.

### Notes on the API

Things that cost time to work out, recorded here so the next person doesn't
repeat them:

- **The documented paths are incomplete.** The docs write `ecos-hub/v1/devices`,
  but the gateway requires `/open-api/ecos-hub/v1/devices`. The published
  Signature guide page returns an empty document; the signing scheme here was
  derived from WHES' official sign-demo (Java/Go/Python).
- **The path must not be percent-encoded in the signature.** WHES' helper is
  called `percentEncode` but only rewrites `+` → `%20`, `*` → `%2A` and `%7E` →
  `~`. Encoding the slashes yields `invalid signature`.
- **Everything returns HTTP 200.** Errors are signalled by the `code` field in
  the JSON body, so status codes tell you nothing.
- **`/inverter`, `/battery`, `/ammeter`, `/rated-power` and `/iot/is-online`
  are documented but did not work** on the test account — they return
  `operation failed`, `Internal error` or `not found`. All live data comes from
  `/metrics` instead.
- **`ecos-hub.whes.com` is the web app, not the API.** It serves its SPA shell
  with HTTP 200 for every path, which looks like success. The API gateway is
  `open-api-eu.weiheng-tech.com`.

## Disclaimer

Not affiliated with, endorsed by or associated with WEIHENG Group, WHES,
eCactus or Agave. Trademarks belong to their respective owners.

## License

MIT
