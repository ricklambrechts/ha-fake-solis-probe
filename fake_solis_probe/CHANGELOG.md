# Changelog

## [Unreleased]

### Added

- Optional, independent inverter AC voltage A/B/C, current A/B/C, and signed
  active-power sources for FC4 `33073–33080`, with shared per-kind scales and
  unavailable policies. Inverter AC power has a configurable `direct` or
  `negate` source-sign mapping; the protocol's positive direction is unresolved.
- Fixed synthetic 230.0 V on unconfigured voltage channels: A for every fake
  type, plus B/C for `2050`/`2060`. Explicit HA sources take precedence even
  on B/C for a single-phase fake type; configured outages use the selected
  `zero` or `last_known` policy. The fake voltage is not an online-status
  signal or a physical 3P3W line-voltage measurement.

### Changed

- `33073–33080` are profile-owned, so `registers.json` can no longer seed
  those input addresses. AC active power remains separate from PV/DC and
  meter power. Tibber has been observed reading the containing `33070/26`
  block, but restoring its historical graphs is not yet verified.
- Updated the development and CI lint toolchain to Ruff 0.16.0 and adopted
  its expanded default rule set.
- Replaced the JSON interoperability fixtures and checksum sidecars with
  pytest parameter tables in `tests/test_register_mapping.py`. The tables keep
  sanitized request shapes and artificial before/after expectations directly
  beside the tests that consume them; the evidence documentation retains
  capture provenance and authority limits.

## [0.9.0] - 2026-07-26

### Added

- Optional backup-load telemetry:
  - `ha_sensor_backup_load_power`;
  - `backup_load_power_scale`;
  - `backup_load_power_unavailable_behavior`;
  - canonical nonnegative U16 W at `33148`.
- Optional inverter AC grid-port telemetry:
  - `ha_sensor_ac_grid_port_power`;
  - `ac_grid_port_power_scale`;
  - independent `direct` or `negate` sign convention;
  - `ac_grid_port_power_unavailable_behavior`;
  - canonical S32 W at `33151–33152`, positive export and negative import.
- `fake_hmi_sub_version`, a validated U16 discovery value at `33069`.
- An experimental smart-management profile behind
  `smart_management_enabled`:
  - requires `mirror_writes: true`;
  - advertises V01 remote dispatch through `34502 = 0xAA55` and
    `34503 = 0x0001`;
  - exposes a fake runtime status at `34504`;
  - initializes evidence-backed legacy holding-register defaults;
  - mirrors supported FC6/FC16 writes into fake FC3 readback;
  - provides an in-memory remote-dispatch surface at `44100–44199`;
  - applies an in-memory failsafe using the configured timeout.
- Parameterized regression coverage for the two observed Tibber FC16 Remote
  Dispatch frames at `44100–44104` and `44105–44110`.
- Semantic smart-management options for SoC limits, active-power limit,
  feed-in/backflow limits, grid charging, meter location/type, peak shaving,
  and the fake failsafe.

### Changed

- `33148` and `33151–33152` are now profile-owned optional telemetry and
  remain zero when unconfigured.
- Observed legacy smart-management holdings and `44100–44199` are
  profile-owned. They cannot be supplied through `registers.json`.
- Profile holding reads use validated defaults plus the fake write overlay
  when the experimental profile is enabled. Disabled and explicitly blocked
  profile words remain protected zeroes.
- Protocol-reserved gaps in `44100–44199` stay protected zeroes. Invalid
  profile writes retain the previous fake readback, and `0xFFFF` at `44103`
  or `44104` restores that word's configured default.
- The shared fake failsafe option is constrained to `1..30` minutes so it is
  valid for both legacy `43282` and remote-dispatch `44101`.
- Conflicting legacy `43110` mode combinations are rejected without changing
  fake readback. A zero raw TOU write no longer claims status 3.
- The total-generation `zero` unavailable policy now writes zero after a
  previously valid sample; `last_known` continues to retain it.

### Safety boundary

- Smart-management writes exist only in the fake in-memory holding bank. They
  never call Home Assistant services, write Home Assistant entities, contact
  an inverter, or control a battery.
- Time-of-use words are raw mirrored readback only. The App does not interpret
  or execute a schedule.
- The fake write overlay is cleared on restart.

### Verification caveat

The supplied captures prove that Tibber reads the relevant discovery and
holding ranges and sends three acknowledged two-frame FC16 Remote Dispatch
bursts in a session the user associated with smart scheduling. The final
real-time block carries high-word-first S32 raw `-261`, a 2.61 kW battery
discharge target under V01 mode 2. The real-time blocks use
`44108 = 0x0820` and later `0x0410`; both conflict with V01's reserved high
byte and are therefore retained at the prior fake readback while the other
words mirror. The capture does not contain post-write FC3 readback,
cancellation, failsafe expiry, or independent proof that Tibber accepted or
executed a schedule. Treat this profile as experimental.

## [0.8.0] - 2026-07-26

> [!IMPORTANT]
> A fresh 2026-07-26 physical runtime trace confirms the discovery request
> sequence and continued steady-state polling. It does not contain response
> bytes or the Tibber UI outcome. In particular, the observed steady-state
> cycle does not request the corrected generation registers.

### Breaking changes

- Replaced the historical local payload with the canonical base Solis hybrid
  wire contract.
- Removed six ambiguous generation options. Startup rejects them with an
  actionable replacement; there are no aliases or automatic migrations:

  | Removed | Replacement |
  |---|---|
  | `ha_sensor_total_energy` | `ha_sensor_total_pv_generation` |
  | `ha_sensor_daily_energy` | `ha_sensor_daily_pv_generation` |
  | `total_energy_scale` | `total_pv_generation_scale` |
  | `daily_energy_scale` | `daily_pv_generation_scale` |
  | `total_energy_unavailable_behavior` | `total_pv_generation_unavailable_behavior` |
  | `daily_energy_unavailable_behavior` | `daily_pv_generation_unavailable_behavior` |

- Generation scales now convert each source to kWh and default to `1.0`.
  Total generation encodes whole kWh at `33029–33030`; daily generation
  encodes tenths of kWh at `33035`.
- Removed the **superseded and incorrect** local generation payloads from the
  queried ranges beginning at `34391` and `34621`. The base profile returns
  deterministic zeroes there.
- Corrected `33121` to the operating-status bitfield, fixed at `0x0001`.
- Corrected `33245` to a blocked parallel-inverter field with unresolved scale;
  it is no longer treated as battery SoC.
- Replaced the **superseded** 15-word model-plus-serial composite with the
  canonical 16-word serial at `33004–33019`. `fake_inverter_model` remains
  available only through FC17/FC43.
- Replaced the flat `registers.json` format. Only bank-qualified input and
  holding objects are accepted; the legacy parser is not retained.

### Added

- A maintainable `solis_probe` runtime package with focused modules for
  configuration, cache ownership, event logging, Home Assistant access,
  validation, registers, telemetry, polling, Modbus, HTTP, and startup
  composition. The original script is now a thin launcher.
- Ruff-based linting, import sorting, and formatting for development and CI,
  while keeping the App runtime standard-library-only.
- Optional household load power:
  - `ha_sensor_household_load_power`;
  - `household_load_power_scale`;
  - `household_load_power_unavailable_behavior`;
  - canonical U16 W encoding at `33147`.
- Optional battery telemetry behind `battery_attached`:
  - required SoC and one signed power source when enabled;
  - independent positive scales;
  - `charge_positive` and `discharge_positive` source conventions;
  - canonical direction at `33135`, SoC at `33139`, and nonnegative S32 power
    magnitude at `33149–33150`;
  - deterministic zero startup and unavailable behavior.
- Home Assistant timezone resolution through `/api/config`, date-scoped daily
  last-known state, current-day source-timestamp checks, and a safe zero state
  that suppresses daily samples when timezone resolution fails.
- Strict finite-number, metadata, semantic, range, serial, inverter-type, and
  conditional-feature validation before port 502 opens.
- Profile ownership and blocked ranges that cannot be overridden by files or
  Modbus writes.
- Separate input and holding banks with a distinct fake holding write overlay.
- Atomic whole-range register snapshots and atomic live-telemetry updates.
- Deduplicated, bounded parallel Home Assistant polling with observable cycle
  duration.
- Privacy-safe diagnostic references for entity IDs and peers.
- Sanitized consumer-request and synthetic before/after regression coverage,
  maintained as pytest parameter tables in `tests/test_register_mapping.py`.

### Changed

- Kept canonical total PV power at `33057–33058` and meter total active power
  at `33263–33264`, with strict range validation and high-word-first encoding.
- Reserved disabled optional telemetry at zero.
- Blocked `33151–33152`, `33245`, `34351`, `34391–34393`, and
  `34621–34622` in the base profile.
- Invalid startup `registers.json` content is fatal. Invalid hot reloads retain
  the last valid input and holding baselines plus the holding overlay.
- FC6/FC16 mirroring can change only unowned fake holding readback. It never
  changes FC4 input registers or calls Home Assistant.
- Documentation now recommends Home Assistant's native Integral and Utility
  Meter helpers through **Settings > Devices & services > Helpers**, not YAML
  templates or integration inside the App.

### Known verification caveat

The 2026-07-26 request trace newly records `33000/20`, `33067/3`,
`43052/23`, and `43384/1`. The App replays all newly observed ranges with a
complete response, while the earlier sanitized request-shape cases remain
valid historical evidence.

The supplied steady-state Tibber excerpt does not include reads of
`33029–33030` or `33035`. Tibber may stop displaying lifetime or daily
generation even while every observed request continues receiving a valid
response. Investigate any missing display with a new sanitized capture; do not
restore a register meaning contradicted by the protocol evidence.

## [0.7.0] - 2026-05-18

### Added

- Log rotation for `events.jsonl`:
  - `log_max_bytes`, default 5 MiB;
  - `log_backup_count`, default 3;
  - rotation under `LOG_LOCK`;
  - safe behavior for rotation failures.
- Standalone log-rotation regression tests.

## [0.6.0] - 2026-05-17

### Added

- Configurable `fake_inverter_type_code` with `2030` as the default.

### Historical note

The original implementation allowed a later flat-file reload to override
`35000`. That behavior is **superseded and removed in 0.8.0**. The type code is
now profile-owned and rejected in either `registers.json` bank.

## [0.5.1] - 2026-05-17

### Fixed

- Correctly set the current sensor cache entry to `None` on every failed poll
  while retaining the previous successful value in a separate last-known
  cache.
- Renamed the unavailable event field from `using_last_value` to
  `last_known_value`.
- Added standalone fallback regression tests.

### Historical note

This release diagnosed phantom production in the then-current local daily
payload. That payload and its raw-register multiplier are **superseded and
removed in 0.8.0**; the cache-separation lesson remains applicable.

## [0.5.0] - 2026-05-16

### Added

- Per-sensor `zero` and `last_known` unavailable policies.
- Backoff-controlled `register_fallback` events.

### Historical note

The daily fallback was introduced to mitigate phantom values in a historical
local mapping. That mapping is **superseded and removed in 0.8.0**.

## [0.4.0] - 2026-05-15

### Changed

- Made the four original Home Assistant entity IDs configurable.
- Added configurable source scales and grid sign convention.
- Added startup entity validation and unavailable-sensor backoff.

### Historical note

The original generation option names and scale meanings from this release are
**superseded and rejected in 0.8.0**. See the migration table under
`[Unreleased]`.

## [0.3.0] - 2026-05-15

### Changed

- Enabled automatic boot.
- Disabled raw PDU logging and write mirroring by default.
- Used a signed net-grid Home Assistant source.

## [0.2.0] - 2026-05-15

### Added

- Home Assistant sensor polling through the Supervisor API.
- Live PV and meter power encoding.
- An early local energy and no-battery payload.

### Historical note

The early energy addresses and battery labels in this release were local
assumptions, not verified protocol semantics. They are **superseded and
removed in 0.8.0**. Only the corrected ledger in
`docs/register-map.md` describes the current wire contract.

## [0.1.0] - 2026-05-15

### Added

- Initial Modbus TCP service on port 502.
- Tibber discovery experiments.
- Event logging and an early flat register-file hot reload.
- FC43 device identification.

### Historical note

The initial 15-word identity composite and flat register-file format are
**superseded and removed in 0.8.0**.
