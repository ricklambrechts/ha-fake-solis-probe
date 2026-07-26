# Tibber Discovery and Polling

This document separates observed Tibber request behavior from Solis register
semantics. Tibber has not published this consumer protocol, and a request does
not establish the meaning of an address.

## Regression-data provenance

The sanitized observations and artificial response expectations are maintained
directly in
[`test_register_mapping.py`](../fake_solis_probe/tests/test_register_mapping.py)
as pytest parameter tables:

| Parameter table | Provenance and authority |
|---|---|
| `STEADY_STATE_CASES` | Sanitized transcription of a user-supplied 2026-07-25 runtime excerpt; request behavior only |
| `DISCOVERY_READ_CASES` | Ordered discovery or identity burst from a user-supplied 0.8.0 runtime excerpt dated 2026-07-26; request behavior only |
| `REMOTE_DISPATCH_BURSTS` | Six FC16 command payloads, acknowledgements, and relative burst timing from a user-supplied 0.9.0 session; consumer behavior only |
| `IDENTITY_AND_INITIAL_READ_CASES` | Earlier connection, hourly, and initial-read ledger observations; request behavior only |
| `CORRECTED_FC4_CASES` | Artificial before/after regression expectations; not capture evidence, semantic authority, or a legacy compatibility mode |

The sanitized observation tables exclude network addresses, transaction IDs,
entity IDs, serials, measured values, absolute timestamps, and unrelated log
fields. They establish which requests were observed, their order where
recorded, and whether responses were required. They do not establish register
meaning, type, scale, sign, word order, Tibber UI acceptance, or physical
inverter behavior. The corrected response values come from the reconciled
protocol contract, not captured telemetry.

## Management-protocol evidence

The interpretation of the management scan is reconciled in
[the register ledger](register-map.md). In addition to the project-pinned
upstream plugin commit `1e811052…`, the following user-linked snapshots were
reviewed:

| Source | Immutable revision |
|---|---|
| [`switch_sensors.py`](https://github.com/Pho3niX90/solis_modbus/blob/7e446c982600fa5f1bea612a2fb80d47ab880450/custom_components/solis_modbus/sensor_data/switch_sensors.py) | commit `7e446c982600fa5f1bea612a2fb80d47ab880450`; SHA-256 `12b62c323f9e2e8106c901a598ef29c956cb60d1bdffa2acbfce2c419f94a512` |
| [Community hybrid protocol consolidation](https://github.com/joakimahlen/solis.modbus/blob/0994072dd95ccc8abcf4d121405f957d9ffd0cbc/docs/SOLIS_HYBRID_INVERTER_MODBUS_PROTOCOL.md) | commit `0994072dd95ccc8abcf4d121405f957d9ffd0cbc`; SHA-256 `aefa38aad4bea143b301168530283c10e6bd0db0e082f338dce70cbf6458c59c` |
| [S6-EH3P ESPHome controller specification](https://github.com/Pluimvee/ESPHome/blob/de926eefdec5bac6e1e5c0550e1e6c1095a771d3/nexus_control.md) | commit `de926eefdec5bac6e1e5c0550e1e6c1095a771d3`; SHA-256 `0d99c48e42fe38ac5a9f6077de41ccc46944ebd52635291c1d62adc59290f919` |
| [ReadTheDocs `latest` sensor catalogue source](https://solis-modbus.readthedocs.io/en/latest/_sources/sensors.md.txt) | reviewed-content SHA-256 `930d959cbc4e30bcc270b9eb28733cfa30901a6e3a62def50a72df93c483d5e3` |

The Solis/Ginlong
[Smart Control protocol V1.0](https://solarshop.baywa-re.lv/en/documents/solis-inverters-s6eh3p8k02nvydl-s6-eh3p8k02-nv-yd-l-0/381/96.pdf),
dated 2025-03-15 and SHA-256
`724128ae3a8b7343ce2022c6a031e7d796d21c459c955a6fc9843f55546648b2`,
provides the strongest evidence for `34502–34504` and `44100–44199`. Its
stated trial scope is only S5-EH1P(3–6)K-L at ARM `V4C-63` / DSP `V50B02`
and S6-EH3P(3–10)K-H at ARM `V12-05` / DSP `V06B05D01`, with one inverter
and no parallel system. Its TOU table is internally inconsistent, so the App
mirrors effective TOU words only as raw fake data and does not claim semantic
TOU control.

The community sources help explain client behavior but do not override the
Smart Control document. They also conflict: for example, the pinned plugin assigns
`43073` bit 4 to the grid feed-in limit switch while the community
consolidation calls `43073` meter/CT position.

## Phase 1 — LAN scan

Starting Solis setup in the Tibber app causes Tibber Bridge to look for a
Modbus TCP service on port 502. The App and Bridge must be on a network path
where that port is reachable.

## Phase 2 — Identity

Earlier observations record these FC4 requests for unit ID 1 at connection and
approximately hourly:

| Request | 0.9.0 response |
|---|---|
| `35000/1` | validated `fake_inverter_type_code`; default `2030` |
| `33004/15` | first 15 words of the canonical 16-word serial |
| `33067/1` | unowned input baseline, otherwise zero |
| `34502/2` | fake Remote Dispatch capability/version when enabled; otherwise zeroes |

The 2026-07-26 capture records this ordered in-session FC4 burst:

| Order | Request | 0.9.0 response policy |
|---:|---|---|
| 1 | `33000/20` | four identity/version words followed by all 16 canonical serial words |
| 2 | `33067/3` | baseline/zero at `33067–33068`, followed by `fake_hmi_sub_version` at `33069` |
| 3 | `34502/2` | `0xAA55, 0x0001` when fake smart management is enabled; otherwise zeroes |
| 4 | `35000/1` | validated `fake_inverter_type_code` |

The canonical serial occupies `33004–33019`. Tibber's shorter
historical `33004/15` read receives a normal prefix and does not shorten the
field. The newer `33000/20` read naturally includes all four version words and
the complete serial. `fake_inverter_model` is not inserted into these words;
it remains available only through FC17/FC43.

The newer grouped requests do not disprove the earlier request shapes. Each
sanitized parameter table preserves only the consumer behavior observed in its
own run.

Earlier installations accepted type `2030`, and one installation connected
with `2050`. Those observations do not enable different register profiles.

## Likely external/smart-management scan

The complete 2026-07-26 in-session burst contains ten reads in this exact
order:

| Order | FC | Request | Likely purpose |
|---:|---:|---|---|
| 1 | 4 | `33000/20` | identity, protocol versions, and full serial |
| 2 | 4 | `33067/3` | additional firmware/HMI identity |
| 3 | 4 | `34502/2` | Remote Dispatch capability and version |
| 4 | 4 | `35000/1` | inverter family/type |
| 5 | 3 | `43010/2` | configured SoC limits |
| 6 | 3 | `43052/23` | power-limit block, including `43052` and `43073–43074` |
| 7 | 3 | `43110/1` | storage-control mode flags |
| 8 | 3 | `43140/1` | meter type and location |
| 9 | 3 | `43384/1` | unresolved compatibility word; protected zero |
| 10 | 3 | `43483/6` | hybrid/peak-shaving settings |

It occurred at `13:02:31`, between the ordinary `13:02:23` and `13:02:33`
steady-state cycles, on the same TCP connection. The user reported enabling
external/smart management at about that moment. It is therefore likely a
click-triggered capability and configuration rescan, but the log has no Tibber
UI event with which to prove causation. All ten operations are reads; no FC6
or FC16 write appears in the burst.

The later raw-hex excerpt from `13:28:34` through `13:29:15` contains only the
normal eight-read FC4 loop. It confirms byte-level decoding of that loop but
does not capture another management click or add new scan registers.

A subsequent same-day 0.9.0 excerpt captures three two-frame FC16 bursts in a
session the user associated with Tibber smart scheduling. That later sequence
is documented under Phase 5; it does not change the fact that this earlier
discovery burst itself contained reads only.

The exact `34502/2` request is significant: Smart Control V1.0 defines
`34502 = 0xAA55` as the flag that makes `44100–44199` effective and
`34503 = 0x0001` as protocol V01. This strongly suggests a capability gate,
although Tibber's acceptance logic remains unpublished.

## Phase 3 — Pairing

For a system without a battery, leave `battery_attached` false and enter zero
when Tibber asks for battery capacity. For a real battery, enable the two
required battery sources in the App and enter the battery's actual capacity
in Tibber; capacity itself is not sent by this App.

The 2026-07-26 runtime capture confirms that a Tibber Bridge issued the
observed discovery request sequence and then continued steady-state polling.
It contains no response bytes or Tibber UI result, so pairing acceptance and
the values displayed by the app still require explicit verification before
release.

## Phase 4 — Initial and management holding reads

The `IDENTITY_AND_INITIAL_READ_CASES` table preserves these earlier one-time
FC3 reads:

| Request | Disabled response | Enabled fake readback |
|---|---|---|
| `43010/2` | zeroes | configured maximum/minimum SoC |
| `43052/1` | zero | configured active-power limit |
| `43073/2` | zeroes | configured feed-in switch and backflow limit |
| `43110/1` | zero | configured storage-control flags |
| `43140/1` | zero | configured meter location/type |
| `43483/6` | zeroes | configured `43483`, `43487–43488`; protected zeroes at `43484–43486` |

The observed zeroes are disabled-state observations. These target words are
now profile-owned settings or protected zeroes, not generic
`registers.json` values. When smart management is enabled, accepted FC6/FC16
writes can overlay the configured fake readback in memory.

The 2026-07-26 capture instead records this ordered FC3 sequence:

| Order | Request | 0.9.0 response policy |
|---:|---|---|
| 1 | `43010/2` | configured fake SoC limits; zeroes when disabled |
| 2 | `43052/23` | owned fake settings at `43052`, `43073–43074`; unresolved `43053–43072` retain ordinary unowned precedence |
| 3 | `43110/1` | configured fake storage-control flags; zero when disabled |
| 4 | `43140/1` | configured fake meter location/type; zero when disabled |
| 5 | `43384/1` | profile-owned protected zero |
| 6 | `43483/6` | configured `43483`, `43487–43488`; protected zeroes at `43484–43486` |

The grouped `43052/23` request covers both earlier subranges plus the
intervening words. `43384/1` is newly observed. A request remains consumer
evidence rather than semantic authority; the configured meanings above come
from the reconciled sources. Only the explicitly unresolved interior words
retain generic holding-overlay/file/zero precedence.

No write is ever forwarded to Home Assistant or a physical inverter.

## Phase 5 — Optional fake Remote Dispatch

`smart_management_enabled` defaults to false. Disabled mode returns zero at
`34502–34504`, the profile-owned legacy settings, and `44100–44199`, and
ignores writes to those addresses. Enabling it requires `mirror_writes: true`;
it advertises `34502 = 0xAA55`, `34503 = 1`, and provides fake-only FC3/FC6/FC16
readback. It never forwards a command to Home Assistant or physical equipment.

The verified `44100–44110` core models the master switch, failsafe, system
limits, real-time mode/target/function flags, and lower/upper SoC. Invalid or
unsupported core writes retain the previous fake readback. `0xFFFF` at
`44103` or `44104` restores the configured fake default.

Reserved words `44111–44115`, `44124–44129`, `44139–44143`,
`44153–44157`, `44167–44171`, `44181–44185`, and `44195–44199` remain
protected zero and ignore writes. Other TOU words are raw fake-mirror values
because the official V1.0 TOU layout is internally inconsistent.

Status `34504` is zero while dispatch is off, 1 for default/system activity,
2 for real-time activity, and 3 after a nonzero raw TOU write; an all-zero TOU
write reports 1. This classifies fake traffic and does not mean that a schedule
is executing. Since the App has no TOU clock, its generic fake failsafe also
applies to status 3 rather than modeling an active-period exception. The common
`smart_management_failsafe_minutes` option seeds both legacy `43282` and
Remote Dispatch `44101`; the option is limited to `1..30`, while a subsequent
official `44101` write may use `1..1440`. Once the current timeout expires,
the next register read lazily returns `44100` and `34504` to zero.

### Observed Tibber FC16 sequence

The complete 0.9.0 excerpt contains three acknowledged two-frame bursts:

| Order | Relative time | Request | U16 payload | Fake readback result |
|---:|---:|---|---|---|
| 1 | `+00:00` | FC16 `44100/5` | `[1, 27, 3, 30, 30]` | all five accepted; fake status 1 |
| 2 | `+00:00` | FC16 `44105/6` | `[2, 0, 0, 0x0820, 0, 100]` | five accepted; `44108` rejected; fake status 2 |
| 3 | `+15:07` | FC16 `44100/5` | `[1, 12, 3, 30, 30]` | all five accepted; fake status 1 |
| 4 | `+15:07` | FC16 `44105/6` | `[2, 0, 0, 0x0820, 0, 100]` | five accepted; `44108` rejected; fake status 2 |
| 5 | `+17:38` | FC16 `44100/5` | `[1, 24, 3, 30, 0]` | all five accepted; fake status 1 |
| 6 | `+17:38` | FC16 `44105/6` | `[2, 0xFFFF, 0xFEFB, 0x0410, 20, 95]` | five accepted; `44108` rejected; fake status 2 |

The first pair enables both system limits at `3000 W`, selects real-time
battery mode, requests zero power, and sets a `0–100%` SoC range. The second
pair repeats that target with a 12-minute failsafe. Its arrival 15 minutes and
7 seconds after the 27-minute first pair puts the two calculated expiries only
7 seconds apart, strongly suggesting a common intended deadline. This is an
inference from timing, not a proven general heartbeat interval.

The third pair keeps a `3000 W` import ceiling, changes the enabled export
ceiling to `0 W`, and requests a `20–95%` SoC window. Its high-word-first
target `0xFFFFFEFB` is signed raw `-261`, or `-2610 W`; official mode 2 makes
that a 2.61 kW battery discharge request.

Smart Control V1.0 reserves bits `8–15` of `44108`. Tibber's `0x0820` sets
bit 11 and its later `0x0410` sets bit 10. In both values, reserved bits
`10–11` duplicate the defined grid-charge field at bits `4–5`. The App
acknowledges each FC16 request while retaining the prior `44108` readback and
mirroring the other five words. The paired pattern establishes a concrete
consumer/V01 conflict, not meanings for the reserved bits or
physical-inverter acceptance.

No `44116–44199` word was written. Despite the reported smart-scheduling
association, all three bursts are system setup plus real-time control, not
observed Time-of-Use payloads. The excerpt contains no subsequent FC3
readback, UI-result record, cancellation, failsafe expiry, or evidence of
schedule execution.

## Phase 6 — Steady-state FC4 polling

The sanitized 2026-07-25 excerpt shows the following order approximately every
ten seconds:

| Order | Request | Correct base-profile response |
|---:|---|---|
| 1 | `33057/2` | canonical U32 total PV power |
| 2 | `33245/1` | safe zero; parallel-inverter scale unresolved |
| 3 | `34391/3` | safe zero; Smart Port profile not enabled |
| 4 | `33121/1` | operating status `0x0001` |
| 5 | `33135/17` | supported optional profile words take precedence; other unowned words use the input baseline then zero |
| 6 | `33263/2` | canonical S32 meter total active power |
| 7 | `34351/1` | safe zero; meaning unverified |
| 8 | `34621/2` | safe zero; meaning unverified |

Each valid request receives exactly the requested word count. Correcting the
payload does not remove any observed request response.

The `33135/17` range ends at `33151`, which is only the high word of the
two-word AC grid-port field. The App nevertheless owns and updates the complete
`33151–33152` S32 pair atomically when its distinct optional source is
configured; this particular Tibber request receives only the high word.
Leaving the source blank keeps both words zero. The App never duplicates meter
power from `33263–33264` into this field. The same block also includes optional
backup-load power at `33148`.

## Canonical generation is outside the observed cycle

Total and daily PV generation are encoded only at:

- `33029–33030`: U32 whole kWh;
- `33035`: U16 tenths of kWh.

Neither address appears in the supplied steady-state Tibber excerpt. Tibber
may therefore stop displaying lifetime or daily generation after the
correction. A missing display value is a reason to collect a new sanitized
capture and update the evidence ledger, not to restore a disproven meaning at
another address.

## Connection behavior

Historical testing observed a persistent TCP connection and approximately
ten-second steady-state cadence. If the App restarts, the connection drops and
the Bridge has previously reconnected without a complete re-pair. Treat this
as an observation, not a guarantee across future Tibber firmware.

The 2026-07-26 excerpt adds about 21 minutes of one-connection evidence. It
contains 125 complete steady-state sequences; the discovery burst did not
interrupt their order or cadence. The excerpt is too short to establish an
hourly identity interval.

## Release verification checklist

Before publishing 0.9.0:

1. Start from canonical options with no removed keys.
2. Complete a fresh Tibber discovery and pairing and record the UI outcome;
   the 2026-07-26 request trace covers only the wire-request portion.
3. Confirm the historical `33004/15` and latest `33000/20` reads both receive
   the correct canonical serial behavior.
4. Keep every newly observed request as a sanitized pytest parameter case,
   together with its provenance and authority limit.
5. With smart management disabled, verify that capability/settings remain zero
   and reject fake writes.
6. With it enabled, capture the Tibber UI result, later target updates, FC3
   readback, and every additional FC6/FC16 request; confirm that only fake
   readback and status change and that the failsafe returns `44100`/`34504`
   to zero.
7. Verify the PV, grid, battery, household load, backup load, AC grid-port,
   lifetime generation, and daily
   generation values Tibber actually displays.
8. If a display value is absent, investigate without restoring an address
   meaning contradicted by stronger protocol evidence.
