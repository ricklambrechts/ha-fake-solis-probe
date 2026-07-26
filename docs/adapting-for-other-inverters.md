# Adapting Home Assistant Sources

Fake Solis Probe can consume semantic sensors from any PV brand or Home
Assistant integration. “Adapting” means selecting and scaling those Home
Assistant sources. It does not mean copying another inverter family's raw
register map into the Solis hybrid profile.

Version 0.9.0 implements the base Solis hybrid telemetry profile plus an
experimental, fake-only smart-management surface. A future string-inverter or
other feature profile would need its own official protocol, explicit selector,
identity map, register ownership, and parameterized regression cases.

## 1. Select the four required entities

Open **Developer Tools > States** and identify:

| Role | Required semantics | Valid examples of units |
|---|---|---|
| PV power | Current nonnegative total PV/DC power | W, kW |
| Grid power | Signed meter or net-grid power | W, kW |
| Total PV generation | Nonnegative cumulative generated energy | Wh, kWh, MWh |
| Daily PV generation | Nonnegative generated energy for the current day | Wh, kWh, MWh |

Configure them as:

```text
ha_sensor_pv_power
ha_sensor_grid_power
ha_sensor_total_pv_generation
ha_sensor_daily_pv_generation
```

Only `sensor.*` entities are accepted. If an entity declares a device class,
power sources must be `power` and generation sources must be `energy`.

Do not select grid import/export energy, a net-grid balance, cost, revenue, or
another signed balance as either generation source. The App rejects obvious
semantic mismatches and every negative generation state.

## 2. Create native helpers when needed

Use Home Assistant's built-in helpers rather than YAML templates.

### Power to cumulative PV generation

If the integration provides PV power but no cumulative generation:

1. Go to **Settings > Devices & services > Helpers**.
2. Create an **Integral** helper.
3. Choose the PV power entity as the source.
4. Configure the result in kWh. For watts, select the kilo unit prefix and
   hours as the time unit.
5. Prefer the `left` method for sparse step-like samples unless the source
   behavior justifies a different integration method.
6. Use the helper for `ha_sensor_total_pv_generation`.

The App does not perform this integration itself.

### Cumulative to daily PV generation

If a daily entity is missing:

1. Create a **Utility Meter** helper from the same Helpers screen.
2. Use the cumulative PV-generation entity as its source.
3. Select a daily cycle.
4. Use the resulting entity for `ha_sensor_daily_pv_generation`.

The Utility Meter helper follows Home Assistant's local cycle handling and
avoids a hand-written reset automation or template sensor.

## 3. Configure source scales

Each scale converts the Home Assistant state to the named physical unit before
the App applies its fixed register encoding.

### Power

| Source unit | `pv_power_scale` or `grid_power_scale` |
|---|---:|
| W | `1.0` |
| kW | `1000.0` |

### Generation

| Source unit | `total_pv_generation_scale` or `daily_pv_generation_scale` |
|---|---:|
| Wh | `0.001` |
| kWh | `1.0` |
| MWh | `1000.0` |

The total and daily scales are independent. After conversion:

```text
total raw U32 = floor(total kWh)
daily raw U16 = floor(daily kWh * 10)
```

Scales must be positive and finite. Do not use a negative scale to encode a
sign convention.

## 4. Choose the grid sign convention

The canonical meter value is positive export and negative import.

| Home Assistant source behavior | Setting |
|---|---|
| positive import, negative export | `grid_power_sign_convention: negate` |
| positive export, negative import | `grid_power_sign_convention: direct` |

Verify this while the installation's flow direction is known. After
normalization, importing must produce a negative S32 value at
`33263–33264`.

## 5. Configure unavailable behavior

The defaults are:

| Metric | Default |
|---|---|
| PV power | `zero` |
| Grid power | `zero` |
| Total PV generation | `last_known` |
| Daily PV generation | `zero` |

Power generally uses zero as a safe neutral fallback. Total generation retains
the last valid cumulative value and cannot decrease.

Daily `last_known` is optional and date-scoped. The App gets the configured
timezone explicitly from Home Assistant. At a local-date transition it clears
the old daily value to zero until a finite state whose Home Assistant update
timestamp belongs to the current local date arrives. If the timezone cannot be
resolved, the effective daily fallback is forced to zero and numeric daily
states are suppressed; `33035` remains zero until the App restarts with a
resolvable timezone.

## 6. Optional household load

Household load is independent of battery support:

```text
ha_sensor_household_load_power
household_load_power_scale
household_load_power_unavailable_behavior
```

Use a nonnegative power sensor and a source-to-W scale. The normalized value
must fit `0..65535 W`. Blank configuration reserves `33147` at zero; it cannot
be filled through `registers.json`.

Do not derive load from an undocumented power-balance formula. If the
integration does not expose a trustworthy load value, leave the option blank.

## 7. Optional backup and AC grid-port power

Backup load is independent of battery support:

```text
ha_sensor_backup_load_power
backup_load_power_scale
backup_load_power_unavailable_behavior
```

Use a nonnegative source and convert it to watts. The result must fit
`0..65535 W` and is encoded at `33148`. Leave the option blank to keep the
profile-owned register at zero.

AC grid-port power is a distinct inverter measurement:

```text
ha_sensor_ac_grid_port_power
ac_grid_port_power_scale
ac_grid_port_power_sign_convention
ac_grid_port_power_unavailable_behavior
```

It is encoded as signed S32 W at `33151–33152`, high word first, with positive
export/to-grid and negative import/from-grid.

| Home Assistant source behavior | Setting |
|---|---|
| positive export, negative import | `ac_grid_port_power_sign_convention: direct` |
| positive import, negative export | `ac_grid_port_power_sign_convention: negate` |

Do not reuse the meter/net-grid source configured for
`ha_sensor_grid_power`. Meter power at `33263–33264` and inverter AC grid-port
power at `33151–33152` are different protocol metrics. If the integration
does not expose a trustworthy, distinct grid-port value, leave this option
blank.

## 8. Optional battery telemetry

Set `battery_attached: true` only when the installation has:

- a battery SoC sensor;
- one signed charge/discharge power sensor.

Then configure:

```text
ha_sensor_battery_soc
ha_sensor_battery_power
battery_soc_scale
battery_power_scale
battery_power_sign_convention
battery_soc_unavailable_behavior
battery_power_unavailable_behavior
```

State of charge must normalize to `0..100%`. Battery power must normalize to a
magnitude that fits `0..2147483647 W`.

| Power source convention | Setting |
|---|---|
| positive discharge, negative charge | `discharge_positive` |
| positive charge, negative discharge | `charge_positive` |

One signed source drives direction and magnitude together. Do not configure
separate charge and discharge entities. Zero/unavailable power is represented
as zero magnitude and direction zero.

When `battery_attached` is false, battery entity fields are ignored, not
validated, and not polled.

## 9. Identity, HMI sub-version, and inverter type

`fake_inverter_type_code` owns input register `35000`. The supported fake
identity codes are:

| Code | Hybrid family | Tibber observation |
|---:|---|---|
| `2030` | S6-EH1P low-voltage hybrid | verified default in earlier testing |
| `2040` | high-voltage one-phase hybrid | not verified here |
| `2050` | S6-EH3P low-voltage hybrid | earlier connection verified in one installation |
| `2060` | high-voltage three-phase hybrid | not verified here |

These type choices do not enable other register profiles.

`fake_serial` is encoded as ASCII across the canonical 16-word field
`33004–33019`; values longer than 32 bytes or containing non-ASCII characters
fail startup. `fake_inverter_model` is separate and is used only for FC17/FC43
device identification.

`fake_hmi_sub_version` is a U16 value at `33069`. Tibber's observed
`33067/3` discovery read includes it; `33067–33068` remain zero in the base
profile. Leave the default `0` unless a controlled pairing test establishes a
more appropriate fake identity value.

Do not try to set identity through `registers.json`. All identity words and
`33069` and `35000` are profile-owned, and a file containing them is rejected.

## 10. Experimental smart-management profile

Smart management is opt-in and requires fake write mirroring:

```text
mirror_writes: true
smart_management_enabled: true
```

Startup fails if `smart_management_enabled` is true while `mirror_writes` is
false. When enabled, the App advertises V01 remote dispatch using
`34502 = 0xAA55` and `34503 = 0x0001`, then mirrors supported FC6/FC16 writes
into its in-memory holding overlay for FC3 readback.

Choose semantic defaults that describe the fake inverter profile:

| Option | Default | Allowed values / purpose |
|---|---:|---|
| `smart_management_enabled` | `false` | Enables the fake profile; requires `mirror_writes` |
| `smart_management_max_charge_soc` | `95` | `70..100%` |
| `smart_management_min_soc` | `20` | `5..40%`, below maximum |
| `smart_management_active_power_limit_percent` | `100.0` | `0..110%` |
| `smart_management_grid_feed_in_limit_enabled` | `false` | Fake feed-in-limit flags |
| `smart_management_backflow_limit_w` | `0` | Nonnegative multiple of `100 W` |
| `smart_management_allow_grid_charge` | `true` | Fake storage-control grid-charge bit |
| `smart_management_meter_location` | `grid_side` | `grid_side`, `load_side`, or `grid_and_pv` |
| `smart_management_meter_type` | `auto` | Automatic or explicit semantic meter type |
| `smart_management_peak_shaving_enabled` | `false` | Fake peak-shaving bits |
| `smart_management_peak_baseline_soc` | `20` | `7..100%` |
| `smart_management_peak_max_grid_power_w` | `0` | Nonnegative multiple of `100 W` |
| `smart_management_failsafe_minutes` | `5` | `1..30` minutes |

The options initialize the observed legacy settings and `44100–44110`. The
`44100–44199` range is profile-owned, but protocol-reserved gaps remain
protected zeroes. Defined time-of-use words without semantic options are
opaque readback only. Invalid profile values retain their prior readback, and
`0xFFFF` at `44103` or `44104` restores that word's configured default. The
App does not interpret a schedule, call a Home Assistant service, write an
entity, or contact a physical inverter. Restarting clears the fake write
overlay.

Use `smart_management_meter_type: auto` unless a controlled capture proves a
different fake identity is required. It chooses Eastron one-phase for type
codes `2030`/`2040`, Eastron three-phase for `2050`/`2060`, and no meter for
other codes. Explicit choices are:

```text
general_1_phase
acrel_3_phase
general_3_phase
eastron_1_phase
eastron_3_phase
no_meter
```

## 11. Optional experimental register baseline

The only accepted runtime file shape is:

```json
{
  "input": {"33067": 0},
  "holding": {"45000": 0}
}
```

Use it only for unowned static or experimental values. It cannot configure
supported telemetry, disabled optional metrics, blocked addresses, identity,
smart-management holdings, or `44100–44199`.

An invalid startup file is fatal. An invalid hot reload keeps the last valid
baseline. FC6/FC16 mirroring, when enabled, overlays only the fake holding bank
and survives file reload until the App restarts.

## 12. Verify the result

Enable `log_raw_hex` only for a short diagnostic session. Confirm:

- the App passes startup validation;
- normalized source values and sign conventions are physically plausible;
- Tibber receives all requested word counts;
- no private entity, network, serial, or measured data is included in any
  shared excerpt.

The corrected profile has synthetic regression coverage but still requires a
fresh physical Tibber discovery/pairing and display-value check. The current
steady-state request parameters do not show Tibber reading `33029–33030` or
`33035`, so energy display loss is a known verification item. The
experimental smart-management workflow also needs a controlled opt-in test;
fake register readback alone does not prove Tibber accepts or uses the
feature.
