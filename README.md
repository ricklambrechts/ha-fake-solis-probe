# Fake Solis Probe

**Connects Tibber Bridge to Home Assistant PV telemetry by emulating a
supported Solis hybrid inverter, with an optional fake smart-management
register surface.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[[![Version](https://img.shields.io/badge/app%20version-0.9.0-blue)](fake_solis_probe/CHANGELOG.md)]([![Version](https://img.shields.io/badge/addon%20version-0.6.0-blue)](fake_solis_probe/CHANGELOG.md))
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-HAOS%20Addon-41BDF5?logo=home-assistant)](https://www.home-assistant.io/)
![Status: Experimental](https://img.shields.io/badge/status-experimental-orange)

> [!WARNING]
> This independent community project is not affiliated with Tibber AS or
> Ginlong Solis. Firmware or cloud changes can alter Tibber behavior.

## What it does

The App reads semantic Home Assistant sensors and serves a canonical Solis
hybrid Modbus TCP profile on port 502. It never contacts the user's physical
inverter or forwards Modbus writes to Home Assistant or real hardware.

```text
PV system -> Home Assistant sensors -> Fake Solis Probe App
                                      -> Modbus TCP :502
                                      -> Tibber Bridge
```

The physical PV system can be any brand. The emulated wire profile remains the
base Solis hybrid profile; the App does not mix string-inverter or optional
Smart Port register maps into that profile. The experimental smart-management
profile is a separate, explicit opt-in and remains entirely inside the fake
process.

## Current protocol status

Version 0.9.0 retains the corrected 0.8.0 base profile and adds:

- PV power remains at `33057–33058`.
- Meter total active power remains at `33263–33264`.
- The canonical 16-word serial field is `33004–33019`.
- Total and daily PV generation are now encoded only at `33029–33030` and
  `33035`.
- `33121` is the operating-status bitfield and is held at `0x0001`.
- Optional battery direction, state of charge, and power use `33135`, `33139`,
  and `33149–33150`.
- Optional household load power uses `33147`.
- Optional backup load power uses `33148`.
- Optional, distinct inverter AC grid-port power uses `33151–33152`.
- `fake_hmi_sub_version` supplies the discovery word at `33069`.
- An experimental smart-management profile can advertise remote dispatch at
  `34502–34503` and mirror fake holding-register writes.
- Unresolved or profile-specific addresses requested by Tibber receive safe
  zeroes.

The observed Tibber steady-state requests do not include the canonical
generation registers. Tibber may therefore stop displaying lifetime or daily
generation after this correction even though every request still succeeds.
That is not permission to restore a disproven payload meaning.

The sanitized observations preserved in the
[pytest interoperability tables](fake_solis_probe/tests/test_register_mapping.py)
confirm a 2026-07-26 Tibber discovery burst, continued polling with response
bytes, and three acknowledged two-frame FC16 Remote Dispatch bursts. The last
contains a signed 2.61 kW battery discharge target. Post-write readback,
cancellation, failsafe expiry, pairing/UI acceptance, displayed values, and
schedule execution still require controlled verification.

## Requirements

- Home Assistant OS with support for local Apps.
- Tibber Bridge on the same LAN as Home Assistant.
- Four required `sensor.*` entities:
  - current total PV power;
  - signed meter or net-grid power;
  - cumulative total PV generation;
  - current-day PV generation.
- Optional `sensor.*` entities for household load, backup load, distinct
  inverter AC grid-port power, and—when enabled—battery state of charge and
  one signed battery power source.

## Installation

### Home Assistant App repository

1. Open **Settings > Apps > App store**.
2. Add `https://github.com/Chillout222/ha-fake-solis-probe` as a repository.
3. Install **Fake Solis Probe**.
4. Configure the required entities.
5. Enable start on boot and watchdog, then start the App.

### Manual installation

Copy `fake_solis_probe/` to the Home Assistant local Apps directory
(`/addons/fake_solis_probe/` when using the traditional Samba layout), reload
the App store, install, configure, and start it.

## Required configuration

Use neutral examples such as the following; replace them with entities from
your own Home Assistant instance.

| Option | Required meaning | Typical unit |
|---|---|---|
| `ha_sensor_pv_power` | Nonnegative total PV/DC power | W or kW |
| `ha_sensor_grid_power` | Signed meter total active power | W or kW |
| `ha_sensor_total_pv_generation` | Nonnegative cumulative PV generation | kWh, Wh, or MWh |
| `ha_sensor_daily_pv_generation` | Nonnegative PV generation for the current day | kWh, Wh, or MWh |

The App checks that each entity exists and currently has a finite numeric state
or exactly `unknown`/`unavailable`. When Home Assistant declares metadata,
power sensors must have the `power` device class and generation sensors must
have the `energy` device class and an energy-compatible unit. Grid import,
grid export, net-grid balance, cost, and other signed balance entities are not
valid generation sources.

### Scaling

Scales convert the source state to the physical unit named below. They must be
positive and finite.

| Option | Default | Output after scaling |
|---|---:|---|
| `pv_power_scale` | `1.0` | W |
| `grid_power_scale` | `1.0` | W |
| `total_pv_generation_scale` | `1.0` | kWh |
| `daily_pv_generation_scale` | `1.0` | kWh |

Examples:

| Source unit | Power scale | Generation scale |
|---|---:|---:|
| W / kWh | `1.0` | `1.0` |
| kW / Wh | `1000.0` | `0.001` |
| — / MWh | — | `1000.0` |

The App then applies the fixed wire encoding: total generation is whole kWh in
a U32 pair; daily generation is tenths of kWh in one U16.

### Native Home Assistant helpers

Do not create a YAML template sensor or ask this App to integrate power.

If only a PV power sensor is available:

1. Open **Settings > Devices & services > Helpers**.
2. Create an **Integral** helper using the PV power sensor.
3. Configure its output as cumulative kWh. For a source in watts, use the
   kilo unit prefix and hours as the time unit. The `left` method is generally
   appropriate for sparse step-like power updates.
4. Use that helper for `ha_sensor_total_pv_generation`.

If a daily generation sensor is missing, create a **Utility Meter** helper in
the same Helpers screen, select the cumulative generation entity as its source,
choose a daily cycle, and use the resulting sensor for
`ha_sensor_daily_pv_generation`.

### Grid sign

The canonical meter register is positive for export and negative for import.

| `grid_power_sign_convention` | Use when the HA sensor reports |
|---|---|
| `negate` (default) | positive import, negative export |
| `direct` | positive export, negative import |

### Unavailable behavior

| Option | Default |
|---|---|
| `pv_power_unavailable_behavior` | `zero` |
| `grid_power_unavailable_behavior` | `zero` |
| `total_pv_generation_unavailable_behavior` | `last_known` |
| `daily_pv_generation_unavailable_behavior` | `zero` |

Each policy accepts `zero` or `last_known`.

Fresh startup uses zero until the first valid sample. Total generation never
decreases. A daily `last_known` value is retained only within the Home
Assistant local calendar date. The App resolves that timezone through the Home
Assistant API. If it cannot, the effective daily fallback is forced to `zero`
and `33035` stays zero even when a numeric sample is present, because the App
cannot authenticate that sample as belonging to the current local day.

## Optional household load

| Option | Default | Meaning |
|---|---:|---|
| `ha_sensor_household_load_power` | blank | Nonnegative household load power sensor |
| `household_load_power_scale` | `1.0` | Source-to-W multiplier |
| `household_load_power_unavailable_behavior` | `zero` | Fallback policy |

Household load is independent of battery support. When left blank, reserved
register `33147` remains zero.

## Optional backup and AC grid-port power

These sources are independent of battery support and of each other:

| Option | Default | Meaning |
|---|---:|---|
| `ha_sensor_backup_load_power` | blank | Nonnegative backup/EPS load power |
| `backup_load_power_scale` | `1.0` | Source-to-W multiplier |
| `backup_load_power_unavailable_behavior` | `zero` | Fallback policy |
| `ha_sensor_ac_grid_port_power` | blank | Signed inverter AC grid-port power; distinct from meter power |
| `ac_grid_port_power_scale` | `1.0` | Source-to-W multiplier |
| `ac_grid_port_power_sign_convention` | `direct` | Interprets the source sign |
| `ac_grid_port_power_unavailable_behavior` | `zero` | Fallback policy |

Backup load is encoded as nonnegative U16 W at `33148`. AC grid-port power is
encoded as S32 W at `33151–33152`, high word first, with positive meaning
export/to-grid and negative meaning import/from-grid.

| AC grid-port sign setting | Use when the HA source reports |
|---|---|
| `direct` (default) | positive export, negative import |
| `negate` | positive import, negative export |

Do not point `ha_sensor_ac_grid_port_power` at the same meter/net-grid entity
used for `ha_sensor_grid_power`. Registers `33151–33152` describe the
inverter's AC grid port; `33263–33264` describe meter total active power.
When an option is blank, its profile-owned register remains zero.

## Optional inverter AC telemetry

Tibber has also been observed reading FC4 `33070/26`, which includes three AC
voltage channels at `33073–33075`, three current channels at `33076–33078`,
and inverter AC active power at `33079–33080`. Configure the corresponding
Home Assistant sources independently of PV/DC power, meter power, AC grid-port
power, and battery mode.

| Option | Default | Meaning |
|---|---:|---|
| `ha_sensor_inverter_ac_voltage_a` | blank | AC voltage channel A |
| `ha_sensor_inverter_ac_voltage_b` | blank | AC voltage channel B |
| `ha_sensor_inverter_ac_voltage_c` | blank | AC voltage channel C |
| `ha_sensor_inverter_ac_current_a` | blank | Nonnegative AC current channel A |
| `ha_sensor_inverter_ac_current_b` | blank | Nonnegative AC current channel B |
| `ha_sensor_inverter_ac_current_c` | blank | Nonnegative AC current channel C |
| `ha_sensor_inverter_ac_power` | blank | Signed inverter AC active power |
| `inverter_ac_voltage_scale` | `1.0` | Shared source-to-V multiplier for all three voltage channels |
| `inverter_ac_current_scale` | `1.0` | Shared source-to-A multiplier for all three current channels |
| `inverter_ac_power_scale` | `1.0` | Source-to-W multiplier |
| `inverter_ac_power_sign_convention` | `direct` | `direct` preserves the source sign; `negate` reverses it |
| `inverter_ac_voltage_unavailable_behavior` | `zero` | Shared `zero` or `last_known` policy for configured voltage sources |
| `inverter_ac_current_unavailable_behavior` | `zero` | Shared `zero` or `last_known` policy for configured current sources |
| `inverter_ac_power_unavailable_behavior` | `zero` | `zero` or `last_known` policy for configured AC power |

Voltage and current use unsigned U16 values with 0.1 V/raw and 0.1 A/raw;
for example, 230.0 V encodes as `2300`. Active power uses signed S32 watts,
high word first. Scales convert each HA state to V, A, or W before wire
encoding: use `1.0` for those units and `1000.0` for kV, kA, or kW.
The Solis hybrid table does not establish whether positive inverter AC power
means import or export; choose `direct` or `negate` to map your source sign,
without treating either setting as a verified direction convention.

An unconfigured voltage channel receives a fixed **synthetic 230.0 V**
(`2300` raw) according to `fake_inverter_type_code`: channel A at `33073` for
every type; channels B/C at `33074–33075` only for `2050` and `2060`.
Types `2030` and `2040`, and all other type codes, get A only. A configured
HA voltage source takes precedence on any channel, including B/C on a
single-phase fake type. If a configured source becomes unavailable, its
`zero` or `last_known` policy applies; synthetic voltage is never substituted
for an outage. This synthetic value is not an online-status indicator or a
physical measurement. A 3P3W inverter may report line-to-line voltage on
these channels, which can differ from 230 V. Unconfigured currents and AC
power remain zero. None of `33073–33080` can be overridden through
`registers.json`. Populating this Tibber-read block has not been shown to
restore historical Tibber graphs.

## Optional battery telemetry

Set `battery_attached: true` only when both required battery sensors are
available.

| Option | Default | Meaning |
|---|---:|---|
| `battery_attached` | `false` | Enables battery validation and polling |
| `ha_sensor_battery_soc` | blank | Battery state of charge |
| `ha_sensor_battery_power` | blank | One signed charge/discharge power source |
| `battery_soc_scale` | `1.0` | Source-to-percent multiplier |
| `battery_power_scale` | `1.0` | Source-to-W multiplier |
| `battery_power_sign_convention` | `discharge_positive` | Interprets the source sign |
| `battery_soc_unavailable_behavior` | `last_known` | Starts at zero until valid |
| `battery_power_unavailable_behavior` | `zero` | Deterministic idle fallback |

| Battery sign setting | Positive source | Negative source |
|---|---|---|
| `discharge_positive` | discharge | charge |
| `charge_positive` | charge | discharge |

The App writes a nonnegative power magnitude and a separate canonical
direction. Zero or unavailable power writes zero magnitude and direction
`0` deterministically; this is an emulator fallback, not a protocol-defined
idle code. State of charge must resolve to `0..100%`.

When `battery_attached` is false, battery entity fields are not validated or
polled and their reserved registers remain zero. During Tibber pairing, enter
zero capacity for a no-battery system; for a real battery, enter its actual
capacity in Tibber because capacity is not supplied by this App.

## Upgrade from 0.7.x

The old keys are rejected at startup and are never translated:

| Removed key | Replacement |
|---|---|
| `ha_sensor_total_energy` | `ha_sensor_total_pv_generation` |
| `ha_sensor_daily_energy` | `ha_sensor_daily_pv_generation` |
| `total_energy_scale` | `total_pv_generation_scale` |
| `daily_energy_scale` | `daily_pv_generation_scale` |
| `total_energy_unavailable_behavior` | `total_pv_generation_unavailable_behavior` |
| `daily_energy_unavailable_behavior` | `daily_pv_generation_unavailable_behavior` |

Review energy scales during migration. The new generation scales convert the
source to kWh and default to `1.0`; they are not raw-register multipliers.

## Advanced options

| Option | Default | Description |
|---|---:|---|
| `enable_http` | `false` | Enables the optional HTTP probe on port 80 |
| `log_raw_hex` | `false` | Logs Modbus PDU hex; enable only while debugging |
| `mirror_writes` | `false` | Mirrors FC6/FC16 into the fake holding-register overlay only |
| `fake_vendor` | `Ginlong` | FC17/FC43 vendor text |
| `fake_inverter_model` | `Solis S6-EH1P` | FC17/FC43 model text; not part of the serial register field |
| `fake_logger_model` | `S2-WL-ST` | FC43 logger text |
| `fake_serial` | `S2WLSTFAKE001` | ASCII serial, at most 32 encoded bytes |
| `fake_inverter_type_code` | `2030` | U16 value at profile-owned register `35000` |
| `fake_hmi_sub_version` | `0` | U16 discovery value at profile-owned register `33069` |
| `log_max_bytes` | `5242880` | Event-log rotation threshold; `0` disables rotation |
| `log_backup_count` | `3` | Rotated backups; integer at most `100`, nonpositive truncates |

See the [App-specific README](fake_solis_probe/README.md) for register-file and
runtime details.

## Experimental smart management

This profile is disabled by default. To test Tibber external/smart management,
set both:

```yaml
mirror_writes: true
smart_management_enabled: true
```

Startup fails if smart management is enabled without write mirroring. When
enabled, the App advertises remote-dispatch support with `34502 = 0xAA55` and
`34503 = 0x0001`, exposes validated fake defaults for the observed legacy
holding registers, and provides an in-memory readback surface for
`44100–44199`.

| Option | Default | Fake register behavior |
|---|---:|---|
| `smart_management_enabled` | `false` | Enables this experimental fake profile; requires `mirror_writes` |
| `smart_management_max_charge_soc` | `95` | Maximum SoC at `43010` and `44110` |
| `smart_management_min_soc` | `20` | Minimum SoC at `43011` and `44109` |
| `smart_management_active_power_limit_percent` | `100.0` | Active-power limit at `43052` |
| `smart_management_grid_feed_in_limit_enabled` | `false` | Feed-in-limit flags at `43073` and `44102` |
| `smart_management_backflow_limit_w` | `0` | Limit at `43074` and `44104`, in 100 W steps |
| `smart_management_allow_grid_charge` | `true` | Storage-control grid-charge bit at `43110` |
| `smart_management_meter_location` | `grid_side` | Meter-location byte at `43140` |
| `smart_management_meter_type` | `auto` | Meter-type byte at `43140`; `auto` follows the fake inverter family |
| `smart_management_peak_shaving_enabled` | `false` | Peak-shaving bits at `43110` and `43483` |
| `smart_management_peak_baseline_soc` | `20` | Peak baseline SoC at `43487` |
| `smart_management_peak_max_grid_power_w` | `0` | Peak grid-power limit at `43488`, in 100 W steps |
| `smart_management_failsafe_minutes` | `5` | `1..30` minute fake timeout shared by `43282` and `44101` |

This does **not** control energy equipment. FC6/FC16 writes update only the
fake in-memory holding overlay and are cleared on restart. The App never calls
Home Assistant services and never forwards commands to a physical inverter.
Defined time-of-use words in the `44100–44199` range are raw mirrored readback
only; protocol-reserved gaps remain protected zeroes. Invalid profile writes
retain the previous readback. The App does not interpret schedules or run a
charging controller.

## Pairing and verification

See [Tibber discovery](docs/tibber-discovery.md). The App continues to answer
all eight observed steady-state FC4 request ranges with the requested word
count, using canonical values or deterministic safe zeroes.

A 2026-07-26 trace confirms three acknowledged two-frame Tibber FC16 Remote
Dispatch bursts in a session associated with smart scheduling. They use
system-settings and real-time blocks, including a later signed 2.61 kW
discharge target; no TOU block was written. Before relying on 0.9.0, verify
post-write FC3 readback, cancellation, failsafe expiry, the Tibber UI outcome,
and the values Tibber displays. Test smart management only with the explicit
opt-in above. Loss of a display value should trigger a new sanitized capture
and evidence review, never restoration of an address meaning known to be
wrong.

## Technical documentation

- [Architecture](docs/architecture.md)
- [Register reconciliation ledger](docs/register-map.md)
- [Adapting Home Assistant sources](docs/adapting-for-other-inverters.md)
- [Tibber discovery](docs/tibber-discovery.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Changelog](fake_solis_probe/CHANGELOG.md)

## Security and privacy

The Supervisor token is never logged. Runtime logs use hashed references for
entity IDs, peers, and HTTP request targets. Raw PDU logging can still reveal
values or identity payloads; remove entity references, serials, measured
values, transaction details, and network information before sharing logs.

## License

MIT — see [LICENSE](LICENSE).
