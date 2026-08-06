# WHES ECOS Hub for Home Assistant

Home Assistant integration for solar and battery systems sold under the
**eCactus / Agave** brand and built by **WEIHENG (WHES)**, using the ECOS Hub
Open API. Developed and verified against an **Agave TH TIA103** with a 10 kWh
battery.

Sensors work out of the box. Control is implemented but requires WHES to enable
VPP on your account — see [Control](#control) below.

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

**Solar needs one extra step.** The Energy Dashboard only accepts cumulative
kWh sensors, and the API exposes no running total for PV production — it has
totals for grid and battery, but not solar. *Solar power* is instantaneous
watts, so the dropdown will not offer it.

Create a [Riemann sum integral
helper](https://www.home-assistant.io/integrations/integration/) to turn power
into energy:

**Settings → Devices & Services → Helpers → Create helper → Integral sensor**

| Field | Value |
| --- | --- |
| Name | `Solar energy produced` |
| Input sensor | *Solar power* |
| Integration method | Trapezoidal rule |
| Precision | 3 |
| Metric prefix | k (for kWh) |
| Time unit | Hours |

The new sensor then appears under **Solar production**. It starts at zero and
accumulates from there, so give it a day before the figures mean anything.

## Control

> **Requires WHES to enable VPP control on your account.** Until they do, every
> write returns an upstream 403 and the control entities show as unavailable.
> The sensors are unaffected.
>
> Ask them at service@whes.com:
>
> *"Please enable VPP control mode for our ECOS Hub Open API AccessKey `<key>`
> and device `<sn>`. `PUT /open-api/ecos-hub/v1/devices/{sn}/vpp/control-mode`
> currently returns 403 and the device reports `vpp_mode` 0."*
>
> The `POST /vpp/bind-device` endpoint does not work around this — it answers
> `4000 Invalid data` when the account has no VPP user to bind to.

### ⚠️ The battery power sign is inverted

In the control API, **negative charges** the battery and **positive discharges**
it. In the sensor feed, `bat_p` is **positive while charging**. They are
opposite. Getting this wrong sends the battery the other way.

### Entities

A **Control mode** dropdown applies a mode immediately, using the staged values
from these number entities:

| Entity | Sent as |
| --- | --- |
| Battery power setpoint | `bat_power` (negative = charge) |
| Minimum battery level | `bat_cap_min` |
| Maximum feed-in limit | `max_feedin_limit` |
| PV power limit | `ppv_limit` |
| Control timeout | `timeout` |

Changing a number does not talk to the inverter on its own — it is stored and
used the next time a mode is applied, so dragging a slider does not fire a dozen
commands at the hardware.

The API cannot read the active mode back, so the dropdown reflects the last mode
*this integration* applied. It shows unknown after a restart and will not notice
changes made from the ECOS app.

### Service

```yaml
action: ecos_hub.set_control_mode
data:
  device_id: <your inverter>
  mode: DirectCharge
  bat_power: -3000      # negative = charge at 3 kW
  bat_cap_min: 20
  timeout: 3600
```

Anything omitted falls back to the corresponding number entity. Each mode
requires a different set of parameters and incomplete calls are rejected locally
before anything is sent:

| Mode | Required |
| --- | --- |
| `SelfConsumption` | `max_feedin_limit`, `bat_cap_min` |
| `DirectCharge` | `bat_power`, `timeout`, `bat_cap_min` |
| `DirectDischarge` | `bat_power`, `ppv_limit`, `timeout`, `bat_cap_min` |
| `ChargeOnly` | `max_feedin_limit`, `timeout`, `bat_cap_min` |
| `DischargeToLoadOnly` | `max_feedin_limit`, `timeout`, `bat_cap_min` |
| `InverterOutputs` | `bat_power`, `bat_power_inv_limit`, `timeout`, `bat_cap_min` |
| `InverterOperates` | `bat_power`, `timeout`, `bat_cap_min` |

### The timeout is a safety feature

Every mode except `SelfConsumption` takes a `timeout`, after which the inverter
returns to normal operation on its own. If an automation dies mid-charge or Home
Assistant goes down, the system does not stay stuck in a forced mode. Keep it
short enough that a mistake corrects itself and have your automation renew the
command; the default is 15 minutes.

## Control

> **Requires WHES to enable VPP control on your account.** Until they do, every
> write returns an upstream 403 and the control entities show as unavailable.
> The sensors are unaffected.
>
> Ask them at service@whes.com:
>
> *"Please enable VPP control mode for our ECOS Hub Open API AccessKey `<key>`
> and device `<sn>`. `PUT /open-api/ecos-hub/v1/devices/{sn}/vpp/control-mode`
> currently returns 403 and the device reports `vpp_mode` 0."*
>
> The `POST /vpp/bind-device` endpoint does not work around this — it answers
> `4000 Invalid data` when the account has no VPP user to bind to.

### ⚠️ The battery power sign is inverted

In the control API, **negative charges** the battery and **positive discharges**
it. In the sensor feed, `bat_p` is **positive while charging**. They are
opposite. Getting this wrong sends the battery the other way.

### Entities

A **Control mode** dropdown applies a mode immediately, using the staged values
from these number entities:

| Entity | Sent as |
| --- | --- |
| Battery power setpoint | `bat_power` (negative = charge) |
| Minimum battery level | `bat_cap_min` |
| Maximum feed-in limit | `max_feedin_limit` |
| PV power limit | `ppv_limit` |
| Control timeout | `timeout` |

Changing a number does not talk to the inverter on its own — it is stored and
used the next time a mode is applied, so dragging a slider does not fire a dozen
commands at the hardware.

The API cannot read the active mode back, so the dropdown reflects the last mode
*this integration* applied. It shows unknown after a restart and will not notice
changes made from the ECOS app.

### Service

```yaml
action: ecos_hub.set_control_mode
data:
  device_id: <your inverter>
  mode: DirectCharge
  bat_power: -3000      # negative = charge at 3 kW
  bat_cap_min: 20
  timeout: 3600
```

Anything omitted falls back to the corresponding number entity. Each mode
requires a different set of parameters and incomplete calls are rejected locally
before anything is sent:

| Mode | Required |
| --- | --- |
| `SelfConsumption` | `max_feedin_limit`, `bat_cap_min` |
| `DirectCharge` | `bat_power`, `timeout`, `bat_cap_min` |
| `DirectDischarge` | `bat_power`, `ppv_limit`, `timeout`, `bat_cap_min` |
| `ChargeOnly` | `max_feedin_limit`, `timeout`, `bat_cap_min` |
| `DischargeToLoadOnly` | `max_feedin_limit`, `timeout`, `bat_cap_min` |
| `InverterOutputs` | `bat_power`, `bat_power_inv_limit`, `timeout`, `bat_cap_min` |
| `InverterOperates` | `bat_power`, `timeout`, `bat_cap_min` |

### The timeout is a safety feature

Every mode except `SelfConsumption` takes a `timeout`, after which the inverter
returns to normal operation on its own. If an automation dies mid-charge or Home
Assistant goes down, the system does not stay stuck in a forced mode. Keep it
short enough that a mistake corrects itself and have your automation renew the
command; the default is 15 minutes.

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

`POST /open-api/ecos-hub/v1/devices/{sn}/metrics` is polled every 30 seconds by
default for the last 30 minutes of samples.

**Rows are sparse.** This is a time-series store and not every field is written
in every sample, so the newest row on its own often has nulls scattered through
it. Reading only `rows[-1]` makes entities flip to "unknown" at random. The
client instead walks backwards from the newest row and keeps the first non-null
value per column, building a complete snapshot of the latest known state. A
*Last sample* diagnostic sensor exposes the newest row's timestamp so you can
see how fresh the data actually is.

The device uploads a fresh sample roughly **every 10 seconds**, so that is the
useful floor for polling — anything faster just re-fetches the same row. Adjust
the interval under **Configure** on the integration (10–600 seconds).

Do not add `sample_by` to the request. It downsamples rather than refines:
asking for `1m` was observed to return one row per *five* minutes, while
omitting it returns the raw 10-second data.

If the device misses an upload the previous readings are kept rather than
blanking every entity.

The API also answers `5000 Internal error` from time to time, notably around
its nightly maintenance window. Up to ten consecutive failures are ridden out
on the last known readings before the entities are marked unavailable — about
five minutes at the default interval. Authentication failures are never
tolerated, since bad credentials will not fix themselves.

Polling also backs off while the API is failing: the interval doubles per
failure up to ten minutes, then resets on the first success. A five-hour
outage costs about 36 requests instead of 660.

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
