# Architecture

## Scope

Fake Solis Probe is a Home Assistant OS App that emulates the telemetry
surface of the base Solis hybrid Modbus profile for Tibber Bridge. It reads
semantic Home Assistant entities; it never communicates with a physical
inverter.

The physical PV source may use any Home Assistant integration. That does not
change the emulated wire family: string-inverter, Smart Port,
parallel-inverter, and physical charging-control profiles remain outside the
base profile. Version 0.9.0 adds an experimental opt-in smart-management
register model, but its writes and runtime state exist only inside this fake
process.

## Source layout

`fake_solis_probe/fake_solis_probe.py` is a thin executable launcher. Runtime
code lives in the `fake_solis_probe/solis_probe/` package:

- `config.py` owns constants, option defaults, and option loading.
- `sensor_cache.py` owns the current and last-known sensor caches and their
  lock-protected access.
- `event_log.py` owns structured event logging, redaction references, and log
  rotation.
- `home_assistant.py` owns Supervisor API requests and Home Assistant local
  date handling.
- `validation.py` validates options, entity metadata, and startup samples.
- `registers.py` owns register encoders, profile/baseline banks, write
  overlays, and `registers.json` reloads.
- `telemetry.py` converts cached semantic values and commits canonical
  register snapshots.
- `polling.py` performs bounded concurrent sensor polling.
- `modbus.py` contains `ModbusHandler` and Modbus PDU handling.
- `http_probe.py` contains the optional HTTP discovery endpoint.
- `app.py` composes startup, polling, and the HTTP and Modbus servers.

This dependency direction keeps the protocol and storage layers independent
of process startup, while preserving the lock ownership described below.

## Data flow

```text
Physical PV system
  -> Home Assistant integration
  -> sensor.* states
  -> Supervisor REST API
  -> validation, scaling, fallback, and canonical encoding
  -> profile-owned Modbus input registers
  -> Tibber Bridge over Modbus TCP :502
```

The App has no network path to the user's inverter or datalogger.

## Startup sequence

Before opening port 502, the process:

1. Loads `/data/options.json` once and retains the raw key set.
2. Rejects malformed JSON and every removed generation key with an actionable
   replacement.
3. Validates required entities and conditionally enabled household, backup,
   AC grid-port, and battery entities through the Supervisor API.
4. Validates current state, metadata, positive finite scales, sign
   conventions, unavailable policies, physical ranges, serial encoding, and
   inverter type, HMI sub-version, and enabled smart-management defaults.
5. Reads the Home Assistant `time_zone` from `/api/config`.
6. Initializes every profile-owned input and holding word, including the
   canonical serial, status `0x0001`, disabled optional telemetry, blocked
   zero ranges, and smart-management defaults or zeroes.
7. Strictly loads the optional bank-qualified `registers.json` baseline.
8. Encodes the validated startup states so clients cannot observe an
   uninitialized profile.
9. Starts the polling thread and then the Modbus server.

An invalid startup configuration or invalid startup register file prevents
the server from opening port 502.

## Home Assistant polling

The four core sources are always enabled. Household load, backup load, and
inverter AC grid-port power are each added only when their entity option is
nonblank. Battery sources are added only when `battery_attached` is true.

Entity IDs are deduplicated, then distinct states are fetched concurrently
with a bounded worker pool and a five-second request timeout. The effective
poll cycle targets five seconds and logs duration and overrun state.

Each result updates both sensor caches under one `CACHE_LOCK` acquisition:

- the current cache becomes the finite numeric value or `None` on every
  failure;
- the last-known cache changes only after a successful finite sample.

Repeated sensor and fallback errors use backoff. Entity IDs are represented in
runtime logs by stable one-way diagnostic references.

## Metric conversion

Every configured scale converts its source to a physical unit before range
validation:

| Metric | Physical normalized value | Wire encoding |
|---|---|---|
| Total PV power | W | U32 at `33057–33058` |
| Meter total active power | W and configured sign | S32 at `33263–33264` |
| Total PV generation | kWh | floor(kWh) U32 at `33029–33030` |
| Daily PV generation | kWh | floor(kWh × 10) U16 at `33035` |
| Household load | W | U16 at `33147` |
| Backup load | W | U16 at `33148` |
| Inverter AC grid-port power | W and configured sign | S32 at `33151–33152` |
| Battery SoC | percent | U16 at `33139` |
| Battery power | signed W source | direction at `33135`, absolute S32 magnitude at `33149–33150` |

Multiword values are big-endian and high-word first. Encoder functions reject
out-of-range values rather than masking or clamping.

Total generation cannot decrease. Invalid runtime samples retain the previous
valid cumulative register and emit a backoff-controlled validation event.

## Home Assistant local date

Daily state is keyed to the IANA timezone explicitly returned by Home
Assistant. On the first observed local-date transition:

1. the previous daily last-known state is discarded;
2. `33035` is cleared to zero;
3. the entity's Home Assistant update timestamp is converted to that timezone;
4. only a finite sample updated on the current local date can repopulate it.

When a daily `last_known` policy is configured but the Home Assistant timezone
cannot be resolved, the effective policy is forced to `zero`, numeric daily
samples are suppressed, and `33035` remains zero until the App restarts with
a resolvable timezone.
The container's default timezone is never treated as semantic authority.

For installations missing energy entities, users should create Home
Assistant's native Integral and Utility Meter helpers through
**Settings > Devices & services > Helpers**. Integration is intentionally not
implemented in this App.

## Register storage

The process maintains five logically separate maps:

```text
profile-owned input values
profile-owned holding defaults
unowned input file baseline
unowned holding file baseline
fake holding write overlay
```

There is no shared-bank compatibility adapter.

### FC4 input resolution

```text
profile-owned input value
  -> unowned input baseline
  -> deterministic zero
```

Profile ownership includes canonical identity, supported live telemetry,
optional telemetry even when disabled, status, HMI sub-version, inverter type,
smart-management capability/status words, and explicitly blocked ranges.

### FC3 holding resolution

For an unowned word:

```text
fake holding write overlay
  -> unowned holding baseline
  -> deterministic zero
```

Observed legacy smart-management holdings and `44100–44199` are profile-owned.
When smart management is disabled they resolve to their protected zeroes. When
enabled, supported words resolve as:

```text
fake holding write overlay
  -> validated profile default
```

Blocked profile words remain zero even when smart management is enabled.

### FC6 and FC16

When `mirror_writes` is false, valid writes are acknowledged without altering
readback. When true, they change only the fake holding overlay. Smart
management requires both `smart_management_enabled` and `mirror_writes`; that
combination permits supported profile holding words to be overlaid and read
back. Writes cannot call Home Assistant and are never forwarded to an
inverter.

The overlay is separate from the file baseline, survives hot reload, and is
cleared on restart.

### Experimental smart-management state

With `smart_management_enabled: true`, input register `34502` is `0xAA55` and
`34503` is `0x0001`, advertising V01 remote dispatch. `34504` tracks only the
fake runtime state:

- `0`: not running;
- `1`: default-settings activity;
- `2`: real-time activity;
- `3`: a nonzero raw time-of-use write.

An all-zero TOU write reports status 1. This status classifies accepted fake
traffic; it does not claim that a schedule is executing.

Profile options initialize semantic defaults for the observed legacy holdings
and `44100–44110`. FC6/FC16 writes can mirror defined words in
`44100–44199`; protocol-reserved gaps remain protected zeroes. Words beyond
the semantic defaults—including time-of-use schedule words—are opaque
readback only; there is no schedule parser or charge controller. Invalid
profile values retain their previous readback. A value of `0xFFFF` at
`44103` or `44104` restores the configured default for that word.

The monotonic in-memory failsafe uses `44101`. When it expires, the App clears
the fake `44100` main switch and `34504` status. With no TOU clock or schedule
engine, the App deliberately applies this generic fake timeout to status 3
instead of claiming the official active-period exception. This state
transition has no effect outside the emulator. No Home Assistant service,
entity write, or physical-inverter command path exists.

## `registers.json` reload

The optional file at `/share/fake_solis_probe/registers.json` accepts only:

```json
{
  "input": {"33067": 0},
  "holding": {"45000": 0}
}
```

Parsing and validation occur before `REG_LOCK` is acquired. A valid revision
replaces both baselines atomically under the lock. A hot reload therefore
cannot expose a partially parsed file.

Invalid startup content is fatal. Invalid hot reload content retains both
last-valid baselines and the write overlay. A rejected file fingerprint is
remembered so every threaded read does not repeat the same error. Removing a
previously loaded file clears both baselines and preserves the overlay.

Profile-owned addresses are rejected in their bank, so the file cannot
override supported telemetry, blocked zeroes, smart-management holdings,
`44100–44199`, or `35000`.

## Atomic snapshots and lock ownership

| Lock | Ownership |
|---|---|
| `CACHE_LOCK` | current/last-known sensor caches, HA sample dates, and sensor error counters |
| `REG_LOCK` | all five register layers, fake remote-dispatch state, and metric date/cumulative state changed with register values |
| `REGISTER_RELOAD_LOCK` | file fingerprint and one-at-a-time reload work |
| `LOG_LOCK` | event append and log rotation |

Each FC3 or FC4 range is resolved as one snapshot under `REG_LOCK`; clients
cannot receive high and low words from different updates. All live metrics,
including battery direction and magnitude, are committed in one register
transaction.

## Threading model

```text
main thread             threaded Modbus TCP server
sensor-poll thread      schedules bounded parallel HA requests
ha-poll workers         fetch distinct sensor states
optional HTTP thread    discovery experiment endpoint
client threads          one per Modbus TCP connection
```

## Modbus function codes

| FC | Name | Base behavior |
|---:|---|---|
| 1, 2 | Read coils/discrete inputs | Zero bits |
| 3 | Read holding registers | Profile defaults or holding overlay/baseline/zero |
| 4 | Read input registers | Canonical profile/baseline/zero |
| 5, 15 | Coil writes | Validate and acknowledge; no state or external effect |
| 6, 16 | Register writes | Optional fake holding overlay only; supported smart-management readback when opted in |
| 8 | Diagnostics | Echo |
| 17 | Report Server ID | Vendor/model text |
| 43 | Device identification | Vendor/model/version/serial/logger objects |

All Modbus dispatch remains in `ModbusHandler`.

## Network and security

Port 502 is exposed because Tibber Bridge scans for the standard Modbus TCP
service on the LAN. The protocol has no authentication, so the service should
not be exposed beyond the trusted local network.

`homeassistant_api: true` gives the App a Supervisor token. It is used only in
the Authorization header for Home Assistant API calls and is never logged.
Peer addresses, entity IDs, and HTTP request targets are hashed before event
logging. Raw PDU logging is disabled by default because payloads can still
contain identity or measured data.

The App implements telemetry and a fake smart-management register model only.
Charging control, Home Assistant service calls, entity writes, and writes to a
physical inverter are explicitly absent.

## Verification boundary

Sanitized request-shape and synthetic before/after parameter tables in
[`test_register_mapping.py`](../fake_solis_probe/tests/test_register_mapping.py)
verify the software contract. The 2026-07-26 runtime evidence confirms a
physical discovery burst, continued polling with response bytes, and three
acknowledged two-frame FC16 Remote Dispatch bursts in a session associated
with smart scheduling. Each real-time frame contains a V01-invalid `44108`
word and is mirrored only for its other five words; the last also carries a
signed 2.61 kW discharge target. Post-write FC3 readback, cancellation,
failsafe expiry, pairing/UI acceptance, displayed values, and schedule
execution remain verification requirements for 0.9.0.
