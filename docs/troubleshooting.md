# Troubleshooting

## App does not appear

For manual installation:

1. Confirm the directory is named `fake_solis_probe`.
2. Confirm `config.yaml` is directly inside it.
3. Use LF line endings.
4. Open **Settings > Apps > App store** and reload/check for updates.
5. Check the Supervisor log if the local App still does not load.

## App cannot bind port 502

An `Address already in use` error means another service already owns the
Modbus TCP port on the Home Assistant host.

From a trusted local terminal, inspect listeners:

```sh
ss -ltnp | grep ':502'
```

Stop or reconfigure the conflicting service. Tibber Bridge expects port 502,
so changing this App to a different external port generally does not solve
discovery.

## Configuration validation fails

The four core entity options are required:

```text
ha_sensor_pv_power
ha_sensor_grid_power
ha_sensor_total_pv_generation
ha_sensor_daily_pv_generation
```

Each must be an existing `sensor.*` entity. Its current state must be a finite
number or exactly `unknown`/`unavailable`. When declared, device class and unit
metadata must agree with power or energy semantics.

The App validates all configuration before opening port 502. The fatal message
names the option and expected value.

### Removed option error after upgrading

Version 0.8.0 rejects old keys rather than translating them:

| Removed | Replacement |
|---|---|
| `ha_sensor_total_energy` | `ha_sensor_total_pv_generation` |
| `ha_sensor_daily_energy` | `ha_sensor_daily_pv_generation` |
| `total_energy_scale` | `total_pv_generation_scale` |
| `daily_energy_scale` | `daily_pv_generation_scale` |
| `total_energy_unavailable_behavior` | `total_pv_generation_unavailable_behavior` |
| `daily_energy_unavailable_behavior` | `daily_pv_generation_unavailable_behavior` |

Open the App configuration, remove every old key, add its replacement, and
restart. Review scales: the new generation scales convert the source to kWh
and normally use `1.0` for a kWh entity.

### Generation entity is rejected

Use a nonnegative sensor that semantically represents PV generation. Grid
import/export, net-grid balance, cost, revenue, and signed balance entities are
not generation sensors.

When Home Assistant declares a device class it must be `energy`; its unit must
be energy-compatible. Negative, NaN, infinity, decreasing total generation,
and out-of-range states are rejected.

If the needed energy entities do not exist, use Home Assistant's native
helpers:

1. Create an **Integral** helper from PV power through
   **Settings > Devices & services > Helpers** and configure cumulative kWh.
2. Create a daily **Utility Meter** helper from that cumulative entity.
3. Do not use a YAML template sensor.

### Battery validation is unexpected

When `battery_attached` is false, battery entities are ignored. When true,
both `ha_sensor_battery_soc` and `ha_sensor_battery_power` are required.

SoC must normalize to `0..100%`. Use a positive scale and select:

- `discharge_positive` when positive means discharge;
- `charge_positive` when positive means charge.

Do not use a negative scale or separate charge/discharge sensors.

### Household load is rejected

The optional entity must be a `sensor.*` power source whose scaled value is
nonnegative and at most `65535 W`. Leave the option blank if no trustworthy
load entity exists; `33147` then stays zero.

### Backup load is rejected

`ha_sensor_backup_load_power` is optional, but a configured entity must be a
`sensor.*` power source. After applying `backup_load_power_scale`, it must be
nonnegative and no greater than `65535 W`. Leave it blank to keep `33148` at
zero.

### AC grid-port power is rejected or reversed

`ha_sensor_ac_grid_port_power` must be a distinct signed inverter grid-port
power sensor, not the meter/net-grid source used for `ha_sensor_grid_power`.
After scaling and sign conversion it must fit signed 32-bit watts.

- Use `ac_grid_port_power_sign_convention: direct` when positive means export.
- Use `ac_grid_port_power_sign_convention: negate` when positive means import.

The canonical result at `33151–33152` is positive export/to-grid and negative
import/from-grid.

### Smart-management validation fails

The experimental profile requires both:

```yaml
mirror_writes: true
smart_management_enabled: true
```

The fatal startup message names any semantic default outside its accepted
range. In particular, minimum SoC must be below maximum SoC, power-limit
values expressed in watts must use 100 W steps, and
`smart_management_failsafe_minutes` must be `1..30`. The official remote
dispatch word at `44101` can represent a longer timeout, but this shared fake
option is limited by the legacy `43282` field.

## Home Assistant timezone warning

The App reads `time_zone` from the Home Assistant `/api/config` endpoint. It
uses that local date to prevent daily `last_known` state crossing midnight.

If the timezone cannot be resolved, the App logs
`ha_timezone_unresolved` and forces the effective daily unavailable behavior
to `zero`. It also suppresses numeric daily states and holds `33035` at zero
because their local-day membership cannot be verified. Correct the Home
Assistant timezone; do not rely on the container timezone.

## `registers.json` prevents startup

Only this bank-qualified structure is accepted:

```json
{
  "input": {"33067": 0},
  "holding": {"45000": 0}
}
```

Common errors:

- legacy flat JSON;
- an unknown top-level bank;
- a non-decimal or out-of-range address;
- a Boolean, string, float, negative, or value above `65535`;
- any profile-owned address, including identity, telemetry, blocked ranges,
  smart-management holdings, `44100–44199`, and `35000`.

An invalid startup file is fatal. Move it aside or correct it, then restart.
An invalid hot reload keeps the last valid baselines and holding overlay and
logs one error for that rejected revision.

Removing a previously valid file clears its input and holding baselines.
Mirrored holding writes remain until the App restarts.

## Tibber cannot discover the App

Check:

1. The App is running without a startup-validation error.
2. Tibber Bridge and Home Assistant can reach each other on the LAN.
3. Port 502 is not blocked by a firewall or VLAN rule.
4. No other service owns port 502.
5. Register `35000` uses an appropriate hybrid type code; `2030` is the
   default with earlier successful observations.
6. If a controlled comparison identified an HMI sub-version requirement,
   configure its U16 value through `fake_hmi_sub_version`; it is served at
   `33069`.

The corrected serial occupies `33004–33019`. The historical `33004/15`
request receives the first 15 serial words. The 2026-07-26 `33000/20` request
receives four identity/version words followed by all 16 serial words. No model
text is inserted into either response.

The 2026-07-26 evidence confirms an observed Tibber discovery request burst,
continued polling with response bytes, and three acknowledged two-frame FC16
Remote Dispatch bursts. The last real-time frame includes a signed 2.61 kW
discharge target. The trace does not contain post-write FC3 readback,
cancellation, failsafe expiry, or an independent Tibber UI outcome. Pairing
acceptance and displayed values still require explicit verification before
release.

### Tibber does not offer external/smart management

Confirm that both `smart_management_enabled` and `mirror_writes` are true and
that the App restarted successfully. With the profile enabled, an FC4 read
must return `34502 = 0xAA55` and `34503 = 0x0001`.

This remains experimental. Those capability words and successful FC3/FC6/FC16
traffic prove only fake protocol readback; they do not prove that Tibber will
accept the emulated inverter or expose a particular UI.

The observed real-time FC16 frames write `44108 = 0x0820` and later
`0x0410`. Smart Control V1.0 reserves their high bytes, so the App acknowledges
each frame but retains the previous `44108` value while mirroring the other
five valid words. A log entry with `mirrored_count: 5` and
`profile_blocked_count: 1` for `44105/6` is therefore expected. The high
2-bit pair duplicates the defined grid-charge field in both values, which is a
useful Tibber/V01 conflict to investigate but not authority to accept the
reserved bits.

### Smart-management writes do not affect my battery

That is intentional. Writes are mirrored only into the App's in-memory fake
holding bank so Tibber can read them back. The App never calls Home Assistant
services, never writes Home Assistant entities, and never forwards commands
to a physical inverter.

The fake overlay is cleared on restart. The configured failsafe can also clear
the fake remote-dispatch main switch and status. Defined time-of-use words
within `44100–44199` are opaque raw readback; protocol-reserved gaps remain
protected zeroes, and no schedules are interpreted or run. Invalid profile
writes retain their previous readback.

## Values look wrong

### PV power scale

If a kW source is configured with scale `1.0`, it is encoded as watts too
small. Use:

- W source: `pv_power_scale: 1.0`;
- kW source: `pv_power_scale: 1000.0`.

PV power is U32 W at `33057–33058`.

### Grid sign

The canonical meter register is positive export and negative import.

- Source positive for import: use `negate`.
- Source positive for export: use `direct`.

The result is S32 W at `33263–33264`.

### AC grid-port sign

The inverter AC grid-port pair is also positive export and negative import,
but it has its own source and sign option:

- Source positive for export: use `ac_grid_port_power_sign_convention: direct`.
- Source positive for import: use `ac_grid_port_power_sign_convention: negate`.

The result is S32 W at `33151–33152`. Do not configure this option from the
meter/net-grid source merely to duplicate `33263–33264`.

### Generation scale

Generation scales convert the source to kWh:

- Wh: `0.001`;
- kWh: `1.0`;
- MWh: `1000.0`.

Total generation encodes whole kWh at `33029–33030`; daily generation encodes
tenths of kWh at `33035`. Neither value is published at the old superseded
locations.

### Total generation does not decrease

This is intentional. A cumulative generation sample that decreases is
invalid, so the App retains the previous valid value and emits a
backoff-controlled metric-validation event.

### Daily generation stays zero after midnight

The App intentionally clears the previous local day's value at the first date
transition. It stays zero until Home Assistant provides a valid sample whose
`last_updated` or `last_changed` timestamp belongs to the current local day.
Check the source Utility Meter/helper, its update timestamp, and the resolved
Home Assistant timezone.

### Battery direction is reversed

Change `battery_power_sign_convention`, not the scale:

- `discharge_positive`: positive source means discharge;
- `charge_positive`: positive source means charge.

Direction is at `33135`; battery magnitude is at `33149–33150`. Operating
status at `33121` is unrelated and remains `0x0001`.

### Tibber no longer shows energy

The supplied steady-state Tibber requests do not include canonical generation
registers `33029–33030` or `33035`. Version 0.8.0 intentionally returns safe
zeroes to the unresolved queried blocks.

Do not restore a superseded payload. Capture a fresh sanitized request-only
trace, verify what Tibber displays, and update the evidence ledger before
adding any mapping.

## Debug logging

Temporarily set `log_raw_hex: true`, save, and restart the App. Requests and
responses are recorded as PDU hex in `events.jsonl`.

Disable raw logging after diagnosis. Even though peer addresses and entity IDs
are hashed in structured events, raw payloads can disclose identity or
measurements. Before sharing, remove network details, transaction data,
serials, entity references, measured values, and unrelated lines.

## Event log

The structured log is:

```text
/share/fake_solis_probe/events.jsonl
```

A normal 0.9.0 startup includes events similar to:

```json
{"kind":"probe_start","version":"0.9.0"}
{"kind":"config_validation_passed"}
{"kind":"profile_initialized","operating_status":1,"serial_words":16,"smart_management_enabled":false}
{"kind":"sensor_poll_started"}
{"kind":"modbus_server_started","port":502}
```

Repeated unavailable events use backoff and expose only a hashed diagnostic
reference:

```json
{"kind":"sensor_unavailable","source":"entity:<redacted>","consecutive_errors":1,"has_last_known":true}
```

Log rotation defaults to 5 MiB with three backups. `log_max_bytes: 0`
disables rotation; a nonpositive `log_backup_count` truncates without backups,
and positive backup counts may not exceed `100`.

## Verify signed grid words

For a canonical value of `-800 W`, S32 two's complement is:

```text
0xFFFFFCE0
high word = 0xFFFF
low word  = 0xFCE0
```

The encoder rejects values outside the S32 range instead of masking them.
