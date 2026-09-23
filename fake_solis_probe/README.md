# Fake Solis Probe — Home Assistant OS App

Fake Solis Probe serves Home Assistant telemetry as a Solis hybrid Modbus TCP
profile for Tibber Bridge. Its optional smart-management surface is a fake
in-memory register model only. It does not communicate with a physical
inverter, and Modbus writes never leave the fake holding bank.

## Data flow

```text
Home Assistant sensor states
  -> startup validation and five-second polling
  -> canonical input-register profile
  -> Modbus TCP port 502
  -> Tibber Bridge
```

App options are loaded once from `/data/options.json`; restart after changing
them. Static experimental register baselines can be hot-reloaded separately
from `/share/fake_solis_probe/registers.json`.

## Required sensors

| Option | Required semantics | Scale target |
|---|---|---|
| `ha_sensor_pv_power` | Nonnegative total DC/PV power | W |
| `ha_sensor_grid_power` | Signed meter total active power | W |
| `ha_sensor_total_pv_generation` | Nonnegative cumulative PV generation | kWh |
| `ha_sensor_daily_pv_generation` | Nonnegative generation for the current HA local day | kWh |

All configured entities must be `sensor.*`. A state may be a finite number or
the exact transient sentinel `unknown` or `unavailable` at startup. Other
nonnumeric states fail validation. Declared device classes must match `power`
or `energy`; generation unit metadata must describe energy.

Grid/net import, export, cost, or signed balance sensors are invalid generation
sources. Negative generation is rejected rather than clamped or encoded as an
unsigned value.

## Native helper setup

When Home Assistant exposes PV power but no cumulative generation sensor:

1. Go to **Settings > Devices & services > Helpers**.
2. Create an **Integral** helper from the PV power sensor.
3. Configure the result as kWh. For a watt source, choose the kilo unit prefix
   and hours as the time unit. The `left` method generally suits sparse
   step-like samples.
4. Select the helper for `ha_sensor_total_pv_generation`.

When no daily sensor exists, create a **Utility Meter** helper with the
cumulative generation entity as its source and a daily cycle, then select it
for `ha_sensor_daily_pv_generation`.

Use these native helpers instead of a YAML template. The App deliberately does
not integrate instantaneous power.

## Scales and unavailable policies

Scales are independent, positive, finite source-to-physical-unit multipliers.

| Metric | Scale option | Default | Wire encoding |
|---|---|---:|---|
| PV power | `pv_power_scale` | `1.0` | U32 W at `33057–33058` |
| Grid power | `grid_power_scale` | `1.0` | S32 W at `33263–33264` |
| Total generation | `total_pv_generation_scale` | `1.0` | floor(kWh) as U32 at `33029–33030` |
| Daily generation | `daily_pv_generation_scale` | `1.0` | floor(kWh × 10) as U16 at `33035` |
| Household load | `household_load_power_scale` | `1.0` | U16 W at `33147` |
| Backup load | `backup_load_power_scale` | `1.0` | U16 W at `33148` |
| AC grid-port power | `ac_grid_port_power_scale` | `1.0` | S32 W at `33151–33152` |
| Inverter AC voltage A/B/C | `inverter_ac_voltage_scale` | `1.0` | U16, 0.1 V/raw at `33073–33075` |
| Inverter AC current A/B/C | `inverter_ac_current_scale` | `1.0` | U16, 0.1 A/raw at `33076–33078` |
| Inverter AC active power | `inverter_ac_power_scale` | `1.0` | S32 W at `33079–33080` |

For energy sources, use `1.0` for kWh, `0.001` for Wh, or `1000.0` for
MWh. For power, use `1.0` for W or `1000.0` for kW.

| Policy option | Default |
|---|---|
| `pv_power_unavailable_behavior` | `zero` |
| `grid_power_unavailable_behavior` | `zero` |
| `total_pv_generation_unavailable_behavior` | `last_known` |
| `daily_pv_generation_unavailable_behavior` | `zero` |
| `household_load_power_unavailable_behavior` | `zero` |
| `backup_load_power_unavailable_behavior` | `zero` |
| `ac_grid_port_power_unavailable_behavior` | `zero` |
| `inverter_ac_voltage_unavailable_behavior` | `zero` |
| `inverter_ac_current_unavailable_behavior` | `zero` |
| `inverter_ac_power_unavailable_behavior` | `zero` |

Every unavailable policy in this App accepts `zero` or `last_known`.

`last_known` leaves the previous valid register value unchanged. Total
generation cannot decrease. Daily generation can reset only after the date
changes in the timezone returned by the Home Assistant `/api/config`
endpoint. At the first local-date transition it is cleared to zero until a
valid current-day sample arrives. If the timezone cannot be resolved, a
configured daily `last_known` policy is downgraded to `zero`; all numeric daily
samples are also suppressed and `33035` remains zero until the App restarts
with a resolvable timezone.

After a date transition, the App also compares the daily entity's Home
Assistant `last_updated`/`last_changed` date with the current local date. A
stale previous-day state cannot repopulate `33035`.

Fresh startup values are zero until validation supplies a valid numeric state.

## Grid power sign

`33263–33264` uses positive export and negative import.

| `grid_power_sign_convention` | HA source convention |
|---|---|
| `negate` (default) | positive import, negative export |
| `direct` | positive export, negative import |

## Optional household load

| Option | Default |
|---|---:|
| `ha_sensor_household_load_power` | blank |
| `household_load_power_scale` | `1.0` |
| `household_load_power_unavailable_behavior` | `zero` |

A configured value is validated and polled independently of battery mode, then
encoded as U16 W at `33147`. Blank configuration keeps the profile-owned word
at zero.

## Optional backup and AC grid-port power

Both metrics are optional, independent of battery mode, and profile-owned at
zero when unconfigured.

| Option | Default |
|---|---:|
| `ha_sensor_backup_load_power` | blank |
| `backup_load_power_scale` | `1.0` |
| `backup_load_power_unavailable_behavior` | `zero` |
| `ha_sensor_ac_grid_port_power` | blank |
| `ac_grid_port_power_scale` | `1.0` |
| `ac_grid_port_power_sign_convention` | `direct` |
| `ac_grid_port_power_unavailable_behavior` | `zero` |

Backup load must be nonnegative and fit U16 W at `33148`. AC grid-port power
is S32 W at `33151–33152`, high word first, with positive export/to-grid and
negative import/from-grid.

| Sign convention | Positive source | Negative source |
|---|---|---|
| `direct` | export | import |
| `negate` | import | export |

The AC grid-port source must represent the inverter port itself. It is not a
second copy of the meter/net-grid sensor at `33263–33264`.

## Optional inverter AC voltage, current, and active power

These independent sources populate the AC words within Tibber's observed FC4
`33070/26` read. They are optional and do not depend on battery mode.

| Option | Default | Meaning |
|---|---:|---|
| `ha_sensor_inverter_ac_voltage_a` | blank | AC voltage channel A |
| `ha_sensor_inverter_ac_voltage_b` | blank | AC voltage channel B |
| `ha_sensor_inverter_ac_voltage_c` | blank | AC voltage channel C |
| `ha_sensor_inverter_ac_current_a` | blank | Nonnegative AC current channel A |
| `ha_sensor_inverter_ac_current_b` | blank | Nonnegative AC current channel B |
| `ha_sensor_inverter_ac_current_c` | blank | Nonnegative AC current channel C |
| `ha_sensor_inverter_ac_power` | blank | Signed inverter AC active power |
| `inverter_ac_voltage_scale` | `1.0` | Shared source-to-V multiplier |
| `inverter_ac_current_scale` | `1.0` | Shared source-to-A multiplier |
| `inverter_ac_power_scale` | `1.0` | Source-to-W multiplier |
| `inverter_ac_power_sign_convention` | `direct` | Preserve source sign; `negate` reverses it |
| `inverter_ac_voltage_unavailable_behavior` | `zero` | Shared `zero` or `last_known` policy |
| `inverter_ac_current_unavailable_behavior` | `zero` | Shared `zero` or `last_known` policy |
| `inverter_ac_power_unavailable_behavior` | `zero` | `zero` or `last_known` policy |

Voltages and currents encode as nonnegative U16 at 0.1 V/raw and 0.1 A/raw;
230.0 V becomes raw `2300`. Active power encodes as high-word-first S32 at
1 W/raw. Use scale `1.0` for V, A, or W and `1000.0` for kV, kA, or kW.
The Solis hybrid table does not resolve the positive/negative direction of
inverter AC active power, so `direct` and `negate` describe only how the HA
source sign is mapped.

When a voltage source is blank, the app emits fixed synthetic 230.0 V
(`2300` raw) at A (`33073`) for every `fake_inverter_type_code`. Types `2050`
and `2060` also receive synthetic B/C (`33074–33075`); types `2030` and
`2040`, and every other type, receive A only. An explicit HA voltage source
takes precedence on any channel, including B/C on a single-phase fake type.
An unavailable configured source uses the selected `zero` or `last_known`
policy, never the synthetic value. Synthetic voltage **does not indicate that
an inverter is online** and is not a physical measurement. A 3P3W inverter
may report line-to-line voltage, which can differ from 230 V. Unconfigured
current and AC-power sources stay at zero. Inverter AC power is not copied
from PV/DC power at `33057–33058` or meter power at `33263–33264`. The
observed Tibber read does not prove these additions will restore historical
graphs.

## Optional battery telemetry

| Option | Default |
|---|---:|
| `battery_attached` | `false` |
| `ha_sensor_battery_soc` | blank |
| `ha_sensor_battery_power` | blank |
| `battery_soc_scale` | `1.0` |
| `battery_power_scale` | `1.0` |
| `battery_power_sign_convention` | `discharge_positive` |
| `battery_soc_unavailable_behavior` | `last_known` |
| `battery_power_unavailable_behavior` | `zero` |

When `battery_attached` is true, both entities are required. State of charge
must resolve to `0..100%`. The signed power source is scaled to watts, split
into direction at `33135` and a nonnegative S32 magnitude at
`33149–33150`, and committed atomically with state of charge at `33139`.

| Sign convention | Positive | Negative |
|---|---|---|
| `discharge_positive` | direction `1`, discharge | direction `0`, charge |
| `charge_positive` | direction `0`, charge | direction `1`, discharge |

Zero or unavailable battery power produces direction `0` and zero magnitude.
This is a deterministic emulator representation; the protocol does not define
a separate idle direction code.

When `battery_attached` is false, battery options are neither validated nor
polled and `33135`, `33139`, and `33149–33150` stay zero. Operating status at
`33121` remains `0x0001` regardless of battery state.

## Canonical input-register profile

All addresses below are documented addresses with no one-register offset.
Multiword values are high-word first and bytes are big-endian.

| Register | Type | Base-profile behavior |
|---|---|---|
| `33000–33003` | 4 × U16 | Profile-owned identity/version words, currently zero |
| `33004–33019` | 16 words | ASCII `fake_serial`, zero-padded to 32 bytes |
| `33029–33030` | U32 | Total PV generation, 1 kWh/raw |
| `33035` | U16 | Daily PV generation, 0.1 kWh/raw |
| `33057–33058` | U32 | Total DC/PV power, 1 W/raw |
| `33069` | U16 | Validated `fake_hmi_sub_version` discovery value |
| `33073–33075` | 3 × U16 | Optional AC voltage A/B/C, 0.1 V/raw; unconfigured channels get synthetic 230.0 V at A for every fake type and at B/C for `2050`/`2060` |
| `33076–33078` | 3 × U16 | Optional AC current A/B/C, 0.1 A/raw; otherwise zero |
| `33079–33080` | S32 | Optional independent inverter AC active power W; otherwise zero |
| `33121` | U16 | Operating status `0x0001` |
| `33135` | U16 | Battery direction when enabled; otherwise zero |
| `33139` | U16 | Battery SoC percent when enabled; otherwise zero |
| `33147` | U16 | Household load W when configured; otherwise zero |
| `33148` | U16 | Backup load W when configured; otherwise zero |
| `33149–33150` | S32 | Nonnegative battery-power magnitude W when enabled |
| `33151–33152` | S32 | Optional inverter AC grid-port power W; otherwise zero |
| `33245` | U16 | Blocked zero; parallel-inverter scale unresolved |
| `33263–33264` | S32 | Meter total active power W |
| `34351` | U16 | Blocked zero; meaning unverified |
| `34391–34393` | 3 words | Blocked zero; Smart Port profile is not enabled |
| `34502–34504` | 3 × U16 | Remote-dispatch capability, version, and fake runtime status when smart management is enabled; otherwise zero |
| `34621–34622` | 2 words | Blocked zero; meaning unverified |
| `35000` | U16 | Validated `fake_inverter_type_code` |

The historically observed FC4 request `33004/15` naturally returns the first
15 words of the canonical serial. The 2026-07-26 capture instead contains
`33000/20`, which returns four identity/version words followed by all 16 serial
words. A `33004/16` request also returns all 16. The separate `33067/3`
discovery read includes `fake_hmi_sub_version` at `33069`; `33067–33068`
remain zero. The `fake_inverter_model` option is used only by FC17/FC43 and is
never inserted into the serial field.

The App still answers the eight observed Tibber steady-state blocks with the
requested word count. The queried ranges at `34391` and `34621` contain safe
zeroes, not generation. Canonical generation registers have not been observed
in that steady-state request sequence, so the Tibber UI may no longer show
those energy values. The observed `33135/17` read contains backup load at
`33148` but ends at `33151`, only the high word of AC grid-port power. The App
still owns and updates the complete `33151–33152` pair atomically. Other
unowned words use the input file baseline and then default to zero.

## Separate input and holding banks

| Operation | Resolution or effect |
|---|---|
| FC4 input read | profile-owned input → input file baseline → zero |
| FC3 profile holding read with smart management enabled | fake write overlay → validated profile default |
| FC3 profile holding read with smart management disabled | profile-owned zero |
| FC3 unowned holding read | fake write overlay → holding file baseline → zero |
| FC6/FC16 with `mirror_writes: true` | update fake holding overlay only |
| FC6/FC16 with `mirror_writes: false` | acknowledge without changing readback |

FC3, FC6, and FC16 never access the input bank. Writes are never sent to Home
Assistant or a physical inverter. The holding overlay survives a
`registers.json` hot reload and is cleared on App restart.

## `registers.json`

This optional file is only for unowned static or experimental words. It is not
a second configuration surface for supported telemetry.

The only accepted shape is:

```json
{
  "input": {"33067": 0},
  "holding": {"45000": 0}
}
```

Rules:

- The top-level object may contain only `input` and `holding`.
- Each bank must be an object whose addresses are decimal JSON strings.
- Addresses must be `0..65535`.
- Values must be JSON integers in `0..65535`; they are never masked or wrapped.
- Any profile-owned address, including `33073–33080`, `35000`, the observed
  smart-management holdings, and `44100–44199`, is rejected in its bank.
- A legacy flat object is rejected.

An invalid file present at startup prevents the Modbus server from opening.
During hot reload, an invalid revision leaves the last valid input and holding
baselines plus the holding overlay unchanged and emits one clear error for
that file revision. Removing a previously loaded file clears both baselines
but not the holding overlay.

## Startup validation

Before port 502 opens, the App:

1. Rejects malformed options and every removed option key with its replacement.
2. Validates required and conditionally enabled `sensor.*` entities, metadata,
   finite state or allowed transient sentinel, scale, sign, and physical range.
3. Validates `fake_serial` as no more than 32 ASCII bytes, the inverter type
   and HMI sub-version as U16, and all enabled smart-management defaults.
4. Resolves the Home Assistant timezone and effective daily policy.
5. Initializes all profile-owned input and holding words, including disabled
   optional telemetry, smart-management defaults or zeroes, and status.
6. Strictly loads the optional register file.
7. Seeds canonical telemetry from startup validation before accepting clients.

## Removed 0.7.x options

The App intentionally has no aliases:

| Removed | Replacement |
|---|---|
| `ha_sensor_total_energy` | `ha_sensor_total_pv_generation` |
| `ha_sensor_daily_energy` | `ha_sensor_daily_pv_generation` |
| `total_energy_scale` | `total_pv_generation_scale` |
| `daily_energy_scale` | `daily_pv_generation_scale` |
| `total_energy_unavailable_behavior` | `total_pv_generation_unavailable_behavior` |
| `daily_energy_unavailable_behavior` | `daily_pv_generation_unavailable_behavior` |

## Other App options

| Option | Default | Purpose |
|---|---:|---|
| `enable_http` | `false` | Optional HTTP probe on port 80 |
| `log_raw_hex` | `false` | Raw Modbus PDU diagnostics |
| `mirror_writes` | `false` | Fake holding-overlay writes only |
| `fake_vendor` | `Ginlong` | FC17/FC43 vendor text |
| `fake_inverter_model` | `Solis S6-EH1P` | FC17/FC43 model text |
| `fake_logger_model` | `S2-WL-ST` | FC43 logger text |
| `fake_serial` | `S2WLSTFAKE001` | Canonical serial and FC43 serial text |
| `fake_inverter_type_code` | `2030` | Profile-owned U16 at `35000` |
| `fake_hmi_sub_version` | `0` | Profile-owned U16 at `33069` |
| `log_max_bytes` | `5242880` | Rotation threshold; zero disables rotation |
| `log_backup_count` | `3` | Rotated backups; integer at most `100`, nonpositive truncates |

## Experimental smart-management profile

The fake smart-management surface is disabled by default. Enabling it requires
write mirroring:

```yaml
mirror_writes: true
smart_management_enabled: true
```

The App rejects this profile at startup if `mirror_writes` is false. When
enabled, `34502 = 0xAA55` advertises remote-dispatch support and
`34503 = 0x0001` reports protocol version V01. `34504` is a fake runtime
status: `0` not running, `1` default settings, `2` real-time control, or `3`
after a nonzero raw time-of-use write. An all-zero TOU write reports 1. This
classifies fake traffic rather than claiming that a schedule runs. It returns
to zero when the generic in-memory failsafe expires.

The profile initializes the observed legacy settings and the remote-dispatch
surface from semantic options:

| Option | Default | Validation / fake register use |
|---|---:|---|
| `smart_management_enabled` | `false` | Enables this fake profile; requires `mirror_writes` |
| `smart_management_max_charge_soc` | `95` | `70..100%`; `43010`, `44110` |
| `smart_management_min_soc` | `20` | `5..40%` and below maximum; `43011`, `44109` |
| `smart_management_active_power_limit_percent` | `100.0` | `0..110%`; `43052` at 0.01%/raw |
| `smart_management_grid_feed_in_limit_enabled` | `false` | `43073` bit 4 and `44102` bit 1 |
| `smart_management_backflow_limit_w` | `0` | Nonnegative 100 W steps; `43074`, `44104` |
| `smart_management_allow_grid_charge` | `true` | `43110` bit 5 |
| `smart_management_meter_location` | `grid_side` | `grid_side`, `load_side`, or `grid_and_pv`; high byte of `43140` |
| `smart_management_meter_type` | `auto` | Semantic meter type; low byte of `43140` |
| `smart_management_peak_shaving_enabled` | `false` | `43110` bit 11 and `43483` bit 7 |
| `smart_management_peak_baseline_soc` | `20` | `7..100%`; `43487` |
| `smart_management_peak_max_grid_power_w` | `0` | Nonnegative 100 W steps; `43488` |
| `smart_management_failsafe_minutes` | `5` | `1..30` minutes; shared by legacy `43282` and remote-dispatch `44101` |

`smart_management_meter_type: auto` selects Eastron one-phase for fake type
codes `2030`/`2040`, Eastron three-phase for `2050`/`2060`, and no meter for
other codes. Explicit choices are `general_1_phase`, `acrel_3_phase`,
`general_3_phase`, `eastron_1_phase`, `eastron_3_phase`, and `no_meter`.

FC6/FC16 writes to supported profile holdings are mirrored only in memory and
read back through FC3. The `44100–44199` remote-dispatch range is
profile-owned, but protocol-reserved gaps remain protected zeroes. Only
`44100–44110` have semantic defaults; defined time-of-use words are raw
mirrored readback only. The App does not parse, schedule, or execute them.
Invalid values are acknowledged without changing readback, while `0xFFFF`
written to `44103` or `44104` restores that word's configured default.

This feature never calls a Home Assistant service, never writes to a Home
Assistant entity, and never contacts or controls a physical inverter. Restart
the App to clear the fake write overlay.

## Logs and privacy

Structured events are stored at
`/share/fake_solis_probe/events.jsonl`, with rotation controlled by
`log_max_bytes` and `log_backup_count`. Repeated sensor, fallback, and invalid
sample events use backoff.

Entity IDs, client addresses, and HTTP request targets are represented by
stable one-way diagnostic references in logs. `SUPERVISOR_TOKEN` is never
logged. Raw PDU logging can still disclose register payloads; sanitize
identity, measurements, transactions, and network context before sharing.

## Physical verification status

The checked-in
[pytest interoperability tables](tests/test_register_mapping.py) preserve
sanitized request shapes and artificial before/after response expectations. A
2026-07-26 trace confirms three acknowledged two-frame Tibber FC16 Remote
Dispatch bursts in a session associated with smart scheduling. The last
real-time block carries a signed 2.61 kW discharge target; no TOU block was
written. The trace does not include post-write FC3 readback, cancellation,
failsafe expiry, or independent proof of UI acceptance or schedule execution.
Those outcomes, plus what Tibber actually displays, still require physical
verification before relying on 0.9.0.
