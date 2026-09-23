# Solis Hybrid Register Reconciliation Ledger

This ledger separates upstream-defined Solis wire semantics from Tibber request
behavior and from the Fake Solis Probe base-profile implementation. A Tibber
request proves only what the consumer asks for; it does not prove the meaning,
type, scale, sign, or width of the requested address.

## Evidence authority

Evidence is applied in this order:

1. The Solis/Ginlong
   [Smart Control protocol V1.0](https://solarshop.baywa-re.lv/en/documents/solis-inverters-s6eh3p8k02nvydl-s6-eh3p8k02-nv-yd-l-0/381/96.pdf),
   dated 2025-03-15, is authoritative for the remote-dispatch fields it
   explicitly defines. Its SHA-256 is
   `724128ae3a8b7343ce2022c6a031e7d796d21c459c955a6fc9843f55546648b2`.
   Its stated trial scope is narrow: S5-EH1P(3–6)K-L with ARM `V4C-63` / DSP
   `V50B02`, or S6-EH3P(3–10)K-H with ARM `V12-05` / DSP `V06B05D01`, one
   inverter, and no parallel system. The fake profile described below is
   emulator behavior; it does not assert that every selectable fake type code
   and firmware combination is in that trial scope.
2. The [Solis-hosted hybrid Modbus table](https://solis-service.solisinverters.com/helpdesk/attachments/2043689326152),
   attachment `2043689326152` linked by Solis's
   [public Modbus-table article](https://solis-service.solisinverters.com/es/support/solutions/articles/44002663852-tabla-de-modbus-no-nda),
   defines the hybrid AC voltage, phase-current, and active-power telemetry at
   `33073–33080`. It is the official source for those addresses, types, and
   scales; it does not establish a positive/negative direction convention for
   inverter AC active power or guarantee that every hybrid model supplies it.
3. The reviewed
   [`solis_modbus` commit `1e811052a5571e1a141420767407c6f360501508`](https://github.com/Pho3niX90/solis_modbus/tree/1e811052a5571e1a141420767407c6f360501508)
   documents integration behavior, derived entities, and candidate extensions.
   Relevant immutable files are
   [`hybrid_sensors.py`](https://github.com/Pho3niX90/solis_modbus/blob/1e811052a5571e1a141420767407c6f360501508/custom_components/solis_modbus/sensor_data/hybrid_sensors.py)
   for the inventory,
   [`switch_sensors.py`](https://github.com/Pho3niX90/solis_modbus/blob/1e811052a5571e1a141420767407c6f360501508/custom_components/solis_modbus/sensor_data/switch_sensors.py),
   [`select_sensors.py`](https://github.com/Pho3niX90/solis_modbus/blob/1e811052a5571e1a141420767407c6f360501508/custom_components/solis_modbus/sensor_data/select_sensors.py), and
   [`time_sensors.py`](https://github.com/Pho3niX90/solis_modbus/blob/1e811052a5571e1a141420767407c6f360501508/custom_components/solis_modbus/sensor_data/time_sensors.py)
   for fake legacy-control candidates,
   [`string_sensors.py`](https://github.com/Pho3niX90/solis_modbus/blob/1e811052a5571e1a141420767407c6f360501508/custom_components/solis_modbus/sensor_data/string_sensors.py)
   for the separate string-inverter boundary,
   [`solis_base_sensor.py`](https://github.com/Pho3niX90/solis_modbus/blob/1e811052a5571e1a141420767407c6f360501508/custom_components/solis_modbus/sensors/solis_base_sensor.py)
   and
   [`helpers.py`](https://github.com/Pho3niX90/solis_modbus/blob/1e811052a5571e1a141420767407c6f360501508/custom_components/solis_modbus/helpers.py)
   for decoder behavior, and
   [`solis_derived_sensor.py`](https://github.com/Pho3niX90/solis_modbus/blob/1e811052a5571e1a141420767407c6f360501508/custom_components/solis_modbus/sensors/solis_derived_sensor.py)
   for derived formulas. Plugin behavior never overrides an established
   base-profile type, scale, sign, or word order. The pinned
   `switch_sensors.py` content has SHA-256
   `12b62c323f9e2e8106c901a598ef29c956cb60d1bdffa2acbfce2c419f94a512`.
4. The
   [public stable Home Assistant sensor catalogue](https://solis-modbus.readthedocs.io/en/stable/sensors.html)
   was reviewed on 2026-07-25; the reviewed content had SHA-256
   `b3362b9d9b930f0d09946f474480be58dc480ea1b0e51c82ac91314f9096c3d1`.
   Its relevant observations are incorporated below, so no local catalogue copy
   is required. It is a moving generated integration catalogue: useful for
   names, Home Assistant metadata, candidate spans, client decode options, and
   derived formulas, but not independent protocol evidence or authority for
   wire type, word order, scale, sign, or model applicability.
5. Sanitized pytest request-shape parameter tables and the later sanitized
   `33070/26` runtime observation establish consumer behavior only.

The existing base-profile rows below remain the implementation contract, not a
new source of protocol evidence. New or changed semantic claims still require
one of the evidence sources above.

An unresolved meaning, type, scale, sign, or model applicability is not
guessed. The base profile leaves it unowned or explicitly blocks it at zero.

### Supplemental source snapshots and conflicts

Four user-linked sources were reviewed in addition to the evidence baseline.
The immutable commit or content hash identifies the exact revision reviewed;
the branch and `latest` links themselves can change:

| Source | Immutable revision | Use and limitation |
|---|---|---|
| [User-linked `switch_sensors.py` snapshot](https://github.com/Pho3niX90/solis_modbus/blob/7e446c982600fa5f1bea612a2fb80d47ab880450/custom_components/solis_modbus/sensor_data/switch_sensors.py) | commit `7e446c982600fa5f1bea612a2fb80d47ab880450`; SHA-256 `59f3cb9cdbf27ca3605e52a043ec47f0be8303683b34d622078593fdf5bf7fac` | Later integration behavior only; it omits the pinned baseline's `44280` PV-shutdown entry and does not move the project baseline away from `1e811052…` |
| [Joakim Åhlén’s hybrid protocol consolidation](https://github.com/joakimahlen/solis.modbus/blob/0994072dd95ccc8abcf4d121405f957d9ffd0cbc/docs/SOLIS_HYBRID_INVERTER_MODBUS_PROTOCOL.md) | commit `0994072dd95ccc8abcf4d121405f957d9ffd0cbc`; SHA-256 `aefa38aad4bea143b301168530283c10e6bd0db0e082f338dce70cbf6458c59c` | Community, machine-readable synthesis; useful for candidates such as `33069`, but not official wire evidence |
| [Pluimvee’s S6-EH3P ESPHome controller specification](https://github.com/Pluimvee/ESPHome/blob/de926eefdec5bac6e1e5c0550e1e6c1095a771d3/nexus_control.md) | commit `de926eefdec5bac6e1e5c0550e1e6c1095a771d3`; SHA-256 `0d99c48e42fe38ac5a9f6077de41ccc46944ebd52635291c1d62adc59290f919` | Installation-specific working-control evidence and safety warnings; not a universal Solis profile |
| [ReadTheDocs `latest` sensor catalogue source](https://solis-modbus.readthedocs.io/en/latest/_sources/sensors.md.txt) | reviewed-content SHA-256 `930d959cbc4e30bcc270b9eb28733cfa30901a6e3a62def50a72df93c483d5e3` | Moving generated catalogue; names and feature inventory only, not independent protocol evidence |

The supplemental sources disagree in places. In particular, the pinned plugin
uses `43073` bit 4 for the grid feed-in limit switch, while the community
protocol consolidation labels `43073` as meter/CT position. This implementation
follows the pinned plugin for its fake legacy readback. The community
consolidation also conflicts with the pinned `43110` bit layout, so it does not
override that immutable plugin evidence. Pluimvee’s fixed values such as
`43110 = 33` and `43140 = 0x0105` describe one S6-EH3P installation, not
universal defaults independent of the selected fake options.

At the pinned plugin commit, a two-register entity is decoded as
high-word-first S32 unless it explicitly declares U32. None of the relevant
hybrid generation or cumulative-energy pairs declares U32. The plugin
therefore corroborates their addresses, names, units, and configured
multipliers while conflicting with this profile's U32 representation for
`33029–33030`, `33057–33058`, and the total-energy pairs in `33161–33180`.
That client decoder default is recorded as a conflict; it does not change the
emulator contract.

## Address and encoding rules

- Documented `3xxxx` addresses are input registers served by FC4.
- Documented `4xxxx` addresses are holding registers served by FC3 and
  writable only in the fake bank through FC6/FC16.
- Addresses are used exactly as documented, with no one-register offset.
- Bytes within each U16 word are big-endian.
- All implemented 32-bit pairs are high-word first.
- U16/U32 values are unsigned. S16/S32 use two's-complement encoding.
- Invalid, negative-when-unsigned, non-finite, or out-of-range physical values
  are rejected; they are never clamped, masked, or wrapped.

The stable catalogue separates string-inverter ranges `2xxx`, `3xxx`, and
`36xxx` from hybrid ranges `33xxx`, `34xxx`, `35xxx`, and `43xxx`, while
classifying `90xxx` as integration-derived. The pinned `string_sensors.py`
targets a different protocol generation and applies a one-register decode
offset. Neither source authorizes mixing those string mappings into this
hybrid profile.

## Canonical hybrid telemetry

“Ownership” describes the 0.9.0 profile:

- **live**: profile-owned and supplied by validated App options;
- **fixed/reserved**: profile-owned identity, status, disabled optional
  telemetry, or blocked zero;
- **unowned**: optional `registers.json` input baseline, otherwise zero.

Every row in this section belongs to the reconciled base hybrid contract unless
the basis or ownership column explicitly limits it to a future feature
profile. None of these rows authorizes a string-inverter mapping.

| Address | Bank / FC | Representation and order | Physical meaning and scale/sign | 0.9.0 ownership | Tibber observed | Basis |
|---|---|---|---|---|---|---|
| `33000–33003` | input / FC4 | 4 × U16 | Model, DSP, HMI, protocol versions | fixed/reserved; zero | inside `33000/20` discovery read | pinned plugin; stable catalogue naming; request-shape table |
| `33004–33019` | input / FC4 | 16 U16 ASCII words, high byte first | Inverter serial, 32 encoded bytes, zero-padded | fixed/reserved from `fake_serial` | historical `33004/15`; complete field inside `33000/20` | community consolidation; pinned plugin; stable catalogue span; request-shape tables |
| `33029–33030` | input / FC4 | U32, high word first | Total PV generation, 1 kWh/raw | live | not in supplied steady-state capture | community consolidation; pinned plugin/stable catalogue name and scale; plugin S32 conflict |
| `33035` | input / FC4 | U16 | Today’s PV generation, 0.1 kWh/raw | live | not in supplied steady-state capture | community consolidation; pinned plugin; stable catalogue |
| `33057–33058` | input / FC4 | U32, high word first | Total DC output / total PV power, 1 W/raw | live | `33057/2` steady-state | Smart Control input diagram; community consolidation; pinned plugin/stable catalogue name and scale; plugin S32 conflict; request-shape table |
| `33069` | input / FC4 | U16 | HMI sub-version candidate; raw fake discovery value | fixed/reserved from `fake_hmi_sub_version` | inside `33067/3` discovery read | community protocol snapshot; request-shape table |
| `33073–33075` | input / FC4 | 3 × U16, high byte first | AC voltage channels A/B/C, 0.1 V/raw | configured HA sources take precedence; otherwise fixed synthetic 230.0 V on A for all fake types and B/C only for `2050`/`2060` | inside `33070/26` | Solis-hosted hybrid Modbus table for wire mapping; emulator-only synthetic policy; later request observation |
| `33076–33078` | input / FC4 | 3 × U16, high byte first | AC current channels A/B/C, 0.1 A/raw | live when configured; otherwise zero | inside `33070/26` | Solis-hosted hybrid Modbus table; later request observation |
| `33079–33080` | input / FC4 | S32, high word first; big-endian bytes | Inverter AC active power, 1 W/raw; positive/negative direction unresolved | live from independent signed AC-power source when configured; otherwise zero | inside `33070/26` | Solis-hosted hybrid Modbus table; Smart Control diagram; later request observation |
| `33121` | input / FC4 | U16 bitfield | Operating status; the emulator uses bit 0 for normal operation | fixed `0x0001` | `33121/1` steady-state | community consolidation names the address only; established emulator contract; request-shape table |
| `33135` | input / FC4 | U16 | Battery direction: `0=charge`, `1=discharge`; no protocol idle code | live when battery enabled; otherwise zero | inside `33135/17` | Smart Control input diagram; community consolidation; pinned derived logic; stable catalogue naming; request-shape table |
| `33139` | input / FC4 | U16 | Battery state of charge, 1%/raw | live when battery enabled; otherwise zero | inside `33135/17` | community consolidation; pinned plugin; stable catalogue; request-shape table |
| `33147` | input / FC4 | U16 | Household load power, 1 W/raw | live when configured; otherwise zero | inside `33135/17` | Smart Control input diagram; community consolidation; pinned plugin/stable catalogue; request-shape table |
| `33148` | input / FC4 | U16 | Backup load power, 1 W/raw | live when configured; otherwise zero | inside `33135/17` | Smart Control input diagram; community consolidation; pinned plugin/stable catalogue; request-shape table |
| `33149–33150` | input / FC4 | S32, high word first | Battery power, 1 W/raw | live nonnegative magnitude when battery enabled; otherwise zero | inside `33135/17` | Smart Control input diagram; community consolidation; pinned plugin/stable catalogue; request-shape table |
| `33151–33152` | input / FC4 | S32, high word first | AC grid-port power, 1 W/raw; positive to grid, negative from grid | live when configured; otherwise zero | Tibber requests only `33151` within `33135/17` | Smart Control input diagram; community consolidation; pinned plugin/stable catalogue; Pluimvee sign; request-shape table |
| `33161–33168` | input / FC4 | total U32; today/yesterday U16 | Battery charge/discharge energy; total 1 kWh/raw, daily 0.1 kWh/raw | unowned, future slice | no supplied observation | community consolidation; pinned plugin/stable catalogue names and scales; plugin S32-total conflict |
| `33169–33176` | input / FC4 | total U32; today/yesterday U16 | Grid import/export energy; total 1 kWh/raw, daily 0.1 kWh/raw | unowned, future slice | no supplied observation | community consolidation; pinned plugin/stable catalogue names and scales; plugin S32-total conflict |
| `33177–33180` | input / FC4 | total U32; today/yesterday U16 | Household consumption energy; total 1 kWh/raw, daily 0.1 kWh/raw | unowned, future slice | no supplied observation | community consolidation; pinned plugin/stable catalogue names and scales; plugin S32-total conflict |
| `33245` | input / FC4 | U16, scale unresolved | Parallel PV-inverter AC power candidate; plugin uses 0.1 kW/raw, while the existing 1 W/raw contract lacks surviving corroboration | blocked zero | `33245/1` steady-state | pinned plugin candidate; request-shape table |
| `33263–33264` | input / FC4 | S32, high word first | Meter total active power, 1 W/raw; positive export, negative import | live | `33263/2` steady-state | Smart Control input diagram; community consolidation; pinned plugin/stable catalogue; plugin-derived and Pluimvee sign behavior; request-shape table |
| `34351` | input / FC4 | unresolved | Meaning unverified by supplied semantic sources | blocked zero | `34351/1` steady-state | request-shape table only |
| `34391–34393` | input / FC4 | plugin candidate: 3 × S16 | Pinned plugin proposes three Smart Port phase powers at 10 W/raw, feature-gated | blocked zero; no Smart Port profile | `34391/3` steady-state | pinned plugin candidate; request-shape table |
| `34502–34504` | input / FC4 | 3 × U16 | Remote-dispatch capability `0xAA55`, version `0x0001`, and status `0..3` | opt-in fake smart-management profile; all zero when disabled | `34502/2` discovery read; `34504` not observed | Smart Control V1.0; request-shape table |
| `34621–34622` | input / FC4 | unresolved | Meaning unverified by supplied semantic sources | blocked zero | `34621/2` steady-state | request-shape table only |
| `35000` | input / FC4 | U16 | Inverter model/type definition; community examples include `2030` and `2050` | fixed/reserved from validated option | `35000/1` connection/discovery | community consolidation; pinned plugin/stable catalogue address and name; request-shape tables |

The exact energy layout reserved for later work is:

- battery charge: total `33161–33162`, today `33163`, yesterday `33164`;
- battery discharge: total `33165–33166`, today `33167`, yesterday `33168`;
- grid import: total `33169–33170`, today `33171`, yesterday `33172`;
- grid export: total `33173–33174`, today `33175`, yesterday `33176`;
- household consumption: total `33177–33178`, today `33179`, yesterday
  `33180`.

These contract meanings do not imply that 0.9.0 owns or synthesizes those
energy counters.

### Reviewed but unowned hybrid-input candidates

The stable catalogue, community consolidation, and pinned plugin enumerate
additional hybrid inputs. They are recorded here so deleting the local
catalogue copy does not erase the research, but they are not added to the
profile merely because an integration can display them. The reviewed sources
do not jointly establish model applicability and wire semantics strongly
enough for this emulator to own them.

The most relevant gap is inside Tibber's observed `33135/17` read:

| Address | Candidate meaning and reviewed decode behavior | Base-profile decision |
|---|---|---|
| `33136` | LLC bus voltage; pinned plugin and community guide use U16 at 0.1 V/raw | unowned; input baseline then zero |
| `33137–33138` | Backup phase-A voltage/current; reviewed integrations use U16 at 0.1 V/A per raw | unowned; input baseline then zero |
| `33140` | Battery state of health; U16 percentage candidate | unowned; input baseline then zero |
| `33141` | BMS battery voltage; U16 at 0.01 V/raw candidate | unowned; input baseline then zero |
| `33142` | BMS battery current; S16 at 0.1 A/raw in the base plugin decode, with client/model-specific 0.01 alternatives | unowned; input baseline then zero |
| `33143–33144` | BMS charge/discharge current limits; U16 at 0.1 A/raw candidates | unowned; input baseline then zero |
| `33145–33146` | BMS fault-status words; representation and scale remain unresolved because the catalogue supplies no unit while the plugin applies a numeric multiplier | unowned; input baseline then zero |

Other reviewed candidates are grouped below. These groupings preserve the
candidate inventory, not ownership:

| Addresses | Candidate inventory | Evidence limitation |
|---|---|---|
| `33031–33040` | current/last month, yesterday, current/last year PV generation | integration/community names and scales; not implemented |
| `33049–33056` | PV voltage/current channels 1–4 | integration/community candidates; also feed derived PV-power entities |
| `33072`, `33081–33084`, `33093–33096` | DC bus, reactive/apparent power, temperature, frequency, and raw status | integration/community candidates; `33095` is distinct from `33121` |
| `33132–33134` | storage-control switching value, battery voltage, and signed battery current | input-register candidates; never confuse them with holding `43132–43133` |
| `33153–33156` | backup phase-B/C voltage and current | pinned-plugin/community candidates absent from the reviewed stable catalogue |
| `33251–33262` | meter phase voltage/current and phase active power | Smart Control names the three power pairs; other semantics remain integration/community evidence |
| `33281–33284` | meter power factor, frequency, and cumulative import energy | community-only candidates |
| `33580–33596` | household and backup load total/year/month/today energy | stable-catalogue and pinned-plugin candidates; not part of `33177–33180` |

The catalogue's “Input Control Sensors” heading is a Home Assistant integration
category, not a claim that its `43xxx` settings belong to the Modbus input bank.

### Integration-derived entities and decode profiles

The pinned integration defines the following derived values. They do not own
additional Modbus registers:

| Derived entity | Source words or formula |
|---|---|
| Status String | decode raw status `33095` |
| PV Power 1–4 | combine each voltage/current pair in `33049–33056` |
| Power Factor | derive from active `33079–33080` and reactive `33081–33082` power |
| Battery Charge / Discharge / Net Power | combine `33149–33150` with direction `33135`; charge is selected by `0`, discharge by `1` |
| Grid Power Net | negate raw meter total power `33263–33264` for the integration's house convention |
| Today Net Grid Energy | subtract export `33175` from import `33171` |
| Inverter model description | decode type word `35000` |
| Last data update / clock adjustment | synthetic `90006`/`90007` entities backed by timestamp or clock words |

The catalogue classifies hybrid `90xxx` values as derived. Neither catalogue
nor plugin-derived formulas establish a physical `90xxx` register family for
this emulator.

Client decode workarounds also remain separate from the base wire contract:

| Decode profile | Affected entity starts | Client behavior |
|---|---|---|
| Stable-catalogue “Waveshare” option | `33142`, `33161`, `33163–33165`, `33167–33168` | changes selected multipliers to `0.01` |
| Pinned `S6-EH3P10K-H-ZP` / `ZONNEPLAN` adjustment | `33142`, `33161–33168` | changes the plugin multiplier to `0.01` |

These profiles overlap but are not the same evidence. Never apply either
globally, and never scale an already normalized Home Assistant value twice.

## Emulator battery representation

The base contract defines direction and battery power as separate fields. The
profile takes one signed Home Assistant power source and:

1. applies `battery_power_scale`;
2. interprets its sign using the configured convention;
3. writes `33135 = 0` for charge or `33135 = 1` for discharge;
4. writes the absolute nonnegative W magnitude as an S32 pair at
   `33149–33150`.

For zero or unavailable power, direction and magnitude are written atomically
as zero. Direction zero is only a deterministic emulator fallback; it is not
presented as a protocol-defined idle code.

The plugin’s Battery Charge Power and Battery Discharge Power entities are
derived from `33135` and `33149–33150`; they do not prove additional physical
registers.

## Resolved historical conflicts

The following local behavior existed before 0.8.0 and is explicitly
**superseded**. It is not a compatibility contract or protocol evidence.

| Address | Corrected decision |
|---|---|
| `33004–33019` | Serve only the canonical 16-word serial; never splice the model into the field |
| `33057–33058` | Keep the value but name it total DC/PV power, not AC active power |
| `33121` | Keep the emulator's normal-operation bit 0 set; never derive it from battery power, and never alias it to the integration's distinct raw-status word `33095` |
| `33245` | Keep zero until a corroborated parallel-inverter profile resolves the plugin's 0.1 kW/raw candidate and the uncorroborated historical 1 W/raw contract |
| `34391–34393` | Remove the superseded local generation payload; base profile returns zero |
| `34351` | Keep zero because semantic evidence is absent |
| `34621–34622` | Remove the superseded local generation payload; base profile returns zero |

Canonical generation is encoded only as:

```text
total_kWh = total_source_state * total_pv_generation_scale
daily_kWh = daily_source_state * daily_pv_generation_scale

33029–33030 U32 raw = floor(total_kWh)
33035 U16 raw = floor(daily_kWh * 10)
```

The reviewed catalogue and pinned plugin label `33095` as inverter current
status and derive a Status String from it. The community consolidation labels
`33121` as operating status but does not independently establish this
profile's bit-0 meaning. The two addresses remain distinct; `33121 = 0x0001`
is an established emulator contract, not a new inference from the catalogue.

## Canonical serial and identity reads

`fake_serial` must contain at most 32 ASCII bytes. It is encoded across all 16
words at `33004–33019`, two bytes per register, then zero-padded.

The historically observed Tibber request `FC4 33004/15` receives the first 15
canonical serial words. The 2026-07-26 capture instead contains `33000/20`,
which receives four identity/version words followed by all 16 serial words. A
valid `33004/16` request also receives the complete serial. These are ordinary
Modbus range reads, not legacy identity modes.

`fake_inverter_model` remains available to FC17 and FC43 device
identification. It is never concatenated with `fake_serial` in the input
register bank.

## Opt-in fake smart-management profile

`smart_management_enabled` defaults to `false`. In that state the
profile-owned capability words `34502–34504`, the legacy fake-management
holding words listed below, and all of `44100–44199` read as zero and ignore
FC6/FC16 writes. This prevents the App from advertising a control surface by
accident.

Enabling the option requires `mirror_writes: true` and exposes only an
in-memory fake control target:

- `34502 = 0xAA55` advertises the Smart Control effective-function flag;
- `34503 = 0x0001` advertises V01;
- `34504` reports fake dispatch status: `0=not running`, `1=default/system`,
  `2=real-time`, or `3=time-of-use`;
- accepted FC6/FC16 writes update fake holding-register readback only;
- no write is forwarded to Home Assistant, a physical inverter, a battery, or
  any other equipment.

This is deliberately opt-in because advertising `0xAA55` tells a client that
the `44100–44199` Remote Dispatch surface is effective. It is a protocol
emulator for consumer testing, not energy-management control.

### Legacy settings readback

The sanitized Tibber scan covers some legacy `43xxx` settings. Supplemental
sources motivate additional fake readback words, but do not prove that Tibber
requested them. The table keeps consumer observation separate from semantic
provenance:

| Address | Fake readback contract | Tibber observed | Basis and qualification |
|---|---|---|---|
| `43010` | maximum charge SoC, U16 at 1%/raw | `43010/2` | pinned plugin and stable catalogue; upstream defaults conflict |
| `43011` | minimum/overdischarge SoC, U16 at 1%/raw | `43010/2` | pinned plugin and stable catalogue |
| `43052` | active-power limit, U16 at 0.01%/raw | `43052/23` and earlier `43052/1` | community consolidation candidate |
| `43073` | grid feed-in limit switch at bit 4 | inside `43052/23`; earlier `43073/2` | pinned switch file; community consolidation instead calls this meter/CT position |
| `43074` | backflow/export limit, U16 at 100 W/raw | inside `43052/23`; earlier `43073/2` | pinned plugin candidate |
| `43110` | storage-control bitfield seeded from fake mode options | `43110/1` | pinned switch file and stable catalogue bit inventory |
| `43128` | S16 grid-port target at 10 W/raw; raw fake readback only | no | pinned plugin; Pluimvee safety warning |
| `43129` | U16 force-discharge power at 10 W/raw; raw fake readback only | no | pinned plugin and Pluimvee |
| `43132` | U16 grid adjustment: `0=off`, `1=system point`, `2=inverter port` | no | pinned plugin and Pluimvee |
| `43133` | S16 system-grid target at 10 W/raw; positive export, negative import | no | pinned plugin and Pluimvee |
| `43135` | U16 force mode: `0=off`, `1=charge`, `2=discharge` | no | pinned plugin, community consolidation, and Pluimvee |
| `43136` | U16 force-charge power at 10 W/raw; raw fake readback only | no | pinned plugin and Pluimvee |
| `43140` | meter location in the high byte and meter type in the low byte | `43140/1` | community consolidation and Pluimvee installation evidence |
| `43282` | legacy fake remote-control timeout in minutes | no | pinned plugin uses `1..30`; Pluimvee reports `2..30`; fake follows the plugin |
| `43384` | unresolved protected zero | `43384/1` | request-shape evidence only |
| `43483` | hybrid-function low-byte raw readback; bit 7 is option-seeded for peak shaving | inside `43483/6` | pinned switch file and stable catalogue bit inventory |
| `43484–43486` | unresolved protected zeroes | inside `43483/6` | request-shape evidence only |
| `43487` | peak baseline SoC, U16 at 1%/raw; accepted fake range `7..100` | inside `43483/6` | pinned plugin candidate |
| `43488` | peak maximum usable grid power, U16 at 100 W/raw; accepted fake range `0..15000 W` | inside `43483/6` | pinned plugin candidate |

With the documented option defaults, enabling the profile yields
`43010–43011 = [95, 20]`, `43052 = 10000`, `43073–43074 = [0, 0]`,
`43110 = 33`, `43282 = 5`, and `43483–43488 = [0, 0, 0, 0, 20, 0]`.
Automatic meter selection makes `43140 = 0x0104` for default fake type `2030`
and `0x0105` for type `2050`; explicit meter options can select a different
validated value. Fake writes to `43110` also enforce the pinned plugin's mode
conflicts and Time-of-Use dependency; invalid bit combinations retain their
previous readback.

The fake `43110` layout follows the pinned switch file:

| Bit | Integration label | Fake validation relationship |
|---:|---|---|
| 0 | self-use | conflicts with 2, 6, and 11 |
| 1 | Time of Use | requires 0 or 6 |
| 2 | off-grid | conflicts with 0, 1, 6, and 11 |
| 3 | battery wakeup | none beyond U16 validation |
| 4 | reserve battery | conflicts with 11 |
| 5 | allow grid charging | none beyond U16 validation |
| 6 | feed-in priority | conflicts with 0, 2, and 11 |
| 7 | battery OVC | none beyond U16 validation |
| 8 | force-charge peak shaving | none beyond U16 validation |
| 9 | battery-current correction | none beyond U16 validation |
| 10 | battery healing | none beyond U16 validation |
| 11 | peak shaving | conflicts with 0, 4, and 6 |

The community consolidation assigns materially different meanings to several
of those bits, and Pluimvee treats bits 0, 1, and 6 as mutually exclusive
instead of making bit 1 depend on 0 or 6. The fake profile records rather than
blends that conflict and follows the pinned switch file.

For `43483`, the reviewed integration labels bits 0–7 as dual backup, AC
coupling, forced Smart-load output, self-use export, Backup-to-Load mode,
manual Backup-to-Load enable, off-grid Smart-load stop, and grid peak shaving.
The plugin marks bit 3 inverted. Only bit 7 is seeded by a semantic App option;
accepted low-byte writes otherwise remain raw fake readback. Catalogue
cross-register constraints involving `43391` and `43365` are candidate
integration behavior, not universal wire rules.

The fake maximum-charge default of 95% is an App choice: the pinned plugin
defaults `43010` to 90%, while the community consolidation lists 95%. It is not
an upstream-consensus default.

Within the observed `43052/23` read, `43052` and `43073–43074` therefore have
profile readback; unresolved `43053–43072` remain unowned. With smart
management disabled, every profile-owned word above remains zero even if a
generic file baseline or fake write attempts to set it.

The Pluimvee source is especially important as a safety boundary: it warns
that writing zero to a physical inverter's `43128` can actively request a
zero-grid target and uses atomic FC16 frames for related commands. This App
does not reproduce those physical effects. It stores accepted words only in
the fake bank.

#### Unowned legacy-control candidates

The reviewed catalogue and pinned integration also enumerate the following
holdings. They remain unowned because the evidence does not establish a safe,
model-scoped fake contract and Tibber has not been observed requesting them:

| Addresses | Candidate inventory |
|---|---|
| `43018`, `43024`, `43027–43028`, `43137`, `43141–43142`, `43195` | force-charge/backup/off-grid SoC, charge-source and power/current limits, and export calibration |
| `43143–43150`, `43153–43160`, `43163–43170`, `43173–43180`, `43183–43190` | five legacy charge/discharge time slots with separate hour/minute words |
| `43249` bits 0–7 | MPPT parallel, IgFollow, relay, leakage, PV-isolation, grid-interference, DC-component, and constant-voltage candidates |
| `43340`, `43363–43369`, `43815` | generator mode, connection, limits, targets, and six period-enable bits |
| `43707–43791` | integration Time-of-Use V2 switch plus six charge and six discharge slots |

The `437xx` integration family is distinct from official Remote Dispatch
`44100–44199`; the two schedule layouts must never be blended.

### Remote Dispatch `44100–44199`

The implemented semantic core follows Smart Control V1.0:

| Address | Representation | Official meaning and fake behavior |
|---|---|---|
| `44100` | U16 | master switch, `0=off`, `1=on`; fake default zero |
| `44101` | U16 minutes | failsafe; official range `1..1440`, fake option default 5 |
| `44102` | U16 bitfield | bit 0 import limit, bit 1 export limit; bits 2–15 are officially reserved and the fake rejects them when nonzero |
| `44103` | U16, 100 W/raw | import limit; conservative fake default zero |
| `44104` | U16, 100 W/raw | export limit; fake default from `smart_management_backflow_limit_w` |
| `44105` | U16 | real-time mode: `1=standby`, `2=battery`, `3=grid point`, `4=AC grid port` |
| `44106–44107` | S32 at 10 W/raw; fake encoding is high-word first | real-time signed target; in mode 2, negative is discharge and positive is charge; in modes 3–4, negative is import and positive is export; fake default zero |
| `44108` | U16 packed 2-bit fields | bits `0–7` hold PV shutdown, DO, grid-charge permission, and off-grid battery standby; bits `8–15` are officially reserved and rejected by the fake when nonzero |
| `44109–44110` | 2 × U16, 1%/raw | lower and upper SoC limits |
| `44111–44115` | reserved | profile-owned zero; writes ignored |
| `44116–44199` | U16 words | TOU blocks; effective words are raw fake mirror only and protected gaps remain zero |

The default enabled readback at `44100–44110` is
`[0, 5, 0, 0, 0, 1, 0, 0, 0, 20, 95]`.

Smart Control defines `44106` as S32 at 10 W/raw but does not explicitly state
the two-word order. High-word-first is the reconciled fake encoding; the
observed Tibber payload is consistent with it but is consumer behavior, not
semantic authority.

Each `44108` two-bit field defines values 1 and 2, calls 3 invalid, calls 0
invalid while also using 0 as the documented default, and says an invalid
function-switch write retains the prior setting. The fake resolves that
document inconsistency by accepting 0 as default/no request, accepting the
defined 1/2 values, and rejecting 3 or any nonzero reserved bit. Rejection of
reserved bits is strict fake V01 validation; the document marks them reserved
but does not separately prescribe that rejection rule.

Observed Tibber writes used `44108 = 0x0820` and later `0x0410`. Their defined
low-byte fields at bits `4–5` are respectively `2` (grid charging not allowed)
and `1` (grid charging allowed), while the values also set reserved bits 11
and 10. The fake profile therefore acknowledges each containing FC16 request,
rejects that whole word, and mirrors the other valid words. The repeated
low-field duplication into reserved bits suggests systematic client behavior,
but that is an inference; it does not establish meanings for bits 10–11 or
justify weakening the V01 mask.

The protected TOU gaps are `44124–44129`, `44139–44143`, `44153–44157`,
`44167–44171`, `44181–44185`, and `44195–44199`. They, together with
`44111–44115`, always read zero and ignore writes. The remaining TOU words are
owned but intentionally raw-only.

Smart Control V1.0 is internally inconsistent in its TOU table: it declares
`44120` as S32 while assigning `44121` to the following U16 field, and its
period-1 block length differs from periods 2–6. The document also contains
misdirected cross-references. Consequently this App does not claim semantic
TOU decoding; accepted effective TOU words only round-trip in fake memory.

The official defaults for `44103–44104` depend on rated inverter power and
parallel-unit count. This App has neither a rated-power option nor a parallel
control profile, so it intentionally uses the fake defaults documented above
instead of inventing those physical values.

The App validates the verified core enums, bit masks, ranges, and paired SoC
limits. Unsupported or invalid writes retain their prior readback. Writing
`0xFFFF` to `44103` or `44104` restores that word's configured fake default.
The shared `smart_management_failsafe_minutes` option seeds both `43282` and
`44101` and is constrained to `1..30` because it also represents the narrower
legacy timeout; after startup, the official `44101` write range remains
`1..1440`.

An accepted Remote Dispatch write updates `34504`: it becomes zero when
`44100` is off, 1 for system/default writes while enabled, 2 for real-time
words, and 3 for a nonzero raw TOU write. An all-zero TOU write reports 1.
This is a classification of fake traffic, not a claim that a schedule is
executing. Because the App has no TOU clock or schedule engine, it cannot
model the official active-period failsafe exception and instead applies its
generic timeout to the fake status. If no accepted Remote Dispatch write
arrives before the current `44101` timeout, the next register read lazily sets
`44100` and `34504` to zero and logs the failsafe event. Other fake readback
words are retained.

## Sanitized interoperability parameter tables

The sanitized observations and artificial response expectations live directly
in the pytest parameter tables in
[`test_register_mapping.py`](../fake_solis_probe/tests/test_register_mapping.py):

| Parameter table | Provenance and authority |
|---|---|
| `STEADY_STATE_CASES` | Sanitized transcription of a user-supplied 2026-07-25 runtime excerpt; request behavior only |
| `DISCOVERY_READ_CASES` | Sanitized ordered discovery or identity burst from a user-supplied 0.8.0 runtime excerpt dated 2026-07-26; request behavior only |
| `REMOTE_DISPATCH_BURSTS` | Sanitized FC16 command payloads, relative burst timing, and acknowledgement shapes from a user-supplied 0.9.0 runtime excerpt; consumer behavior only |
| `IDENTITY_AND_INITIAL_READ_CASES` | Sanitized transcription of earlier ledger observations; request behavior only |
| `CORRECTED_FC4_CASES` | Artificial before/after regression values; documents removed and corrected responses, not field semantics or compatibility |

The raw user excerpts are not checked in. The sanitized observation tables
exclude network addresses, transaction IDs, entity IDs, serials, absolute
timestamps, measured values, and unrelated logs. They establish consumer
request behavior only; the synthetic corrected values come from the
reconciled protocol contract.

## Observed steady-state FC4 sequence

Unit ID 1 issued the following sequence approximately every ten seconds:

| Order | Start / quantity | Base-profile response policy |
|---:|---|---|
| 1 | `33057/2` | canonical total PV power |
| 2 | `33245/1` | blocked zero |
| 3 | `34391/3` | blocked zero |
| 4 | `33121/1` | operating status `0x0001` |
| 5 | `33135/17` | supported optional profile words take precedence; other unowned words use the input baseline then zero |
| 6 | `33263/2` | canonical meter total active power |
| 7 | `34351/1` | blocked zero |
| 8 | `34621/2` | blocked zero |

Every valid request receives exactly the requested word count.

A later sanitized runtime log also shows Tibber repeatedly requesting FC4
`33070/26` (`33070–33095`). The captured responses had zeroes at the AC
voltage, current, and inverter-active-power words before this telemetry was
implemented. That read establishes consumer interest in the block, not the
register meanings or a cause of missing historical graphs. This profile now
supplies `33073–33080` from the independent optional AC sources and the
synthetic voltage policy described above. The other words in the block retain
their existing ownership and baseline/zero behavior.

## Discovery, connection/hourly, and one-time observations

The `DISCOVERY_READ_CASES` table preserves this ordered 2026-07-26 in-session
burst between ordinary steady-state cycles:

| Order | FC | Start / quantity | 0.9.0 response policy |
|---:|---:|---|---|
| 1 | 4 | `33000/20` | four zero identity/version words and all 16 canonical serial words |
| 2 | 4 | `33067/3` | baseline/zero at `33067–33068`, then `fake_hmi_sub_version` at `33069` |
| 3 | 4 | `34502/2` | `0xAA55, 0x0001` when fake smart management is enabled; otherwise zeroes |
| 4 | 4 | `35000/1` | validated inverter type code |
| 5 | 3 | `43010/2` | configured fake maximum/minimum SoC; zeroes when disabled |
| 6 | 3 | `43052/23` | owned settings at `43052`, `43073–43074`; unresolved interior words use generic precedence |
| 7 | 3 | `43110/1` | configured fake storage-control bitfield; zero when disabled |
| 8 | 3 | `43140/1` | configured fake meter location/type; zero when disabled |
| 9 | 3 | `43384/1` | protected zero |
| 10 | 3 | `43483/6` | configured values at `43483`, `43487–43488`; protected zeroes at `43484–43486` |

This capture establishes the full `33000–33019` identity read, the wider
`33067/3` input read, the grouped `43052/23` holding read, and the new
`43384/1` holding read. The burst occurred at `13:02:31`, after the regular
`13:02:23` cycle and before the `13:02:33` cycle, on the same connection. The
user reported enabling external/smart management at about this time, so a
click-triggered capability/configuration rescan is the strongest explanation.
There is no logged UI event, however, so causation is inferred rather than
proven. All ten requests are reads; the capture contains no FC6 or FC16 write.

### Later observed FC16 Remote Dispatch sequence

A later same-day 0.9.0 raw-PDU session captured three two-frame bursts in a
session the user associated with Tibber smart scheduling:

The request and payload columns are capture evidence. The final column is the
separately regression-tested emulator result, not something observed on the
wire:

| Order | Relative time | Request | Observed U16 words | Regression-tested fake result |
|---:|---:|---|---|---|
| 1 | `+00:00` | FC16 `44100/5` | `[1, 27, 3, 30, 30]` | all five mirrored; status `0 → 1`; standard FC16 acknowledgement |
| 2 | `+00:00` | FC16 `44105/6` | `[2, 0, 0, 0x0820, 0, 100]` | five mirrored; `44108` retained because `0x0820` sets reserved bit 11; status `1 → 2`; standard acknowledgement |
| 3 | `+15:07` | FC16 `44100/5` | `[1, 12, 3, 30, 30]` | all five mirrored; status `2 → 1`; standard acknowledgement |
| 4 | `+15:07` | FC16 `44105/6` | `[2, 0, 0, 0x0820, 0, 100]` | five mirrored; `44108` retained; status `1 → 2`; standard acknowledgement |
| 5 | `+17:38` | FC16 `44100/5` | `[1, 24, 3, 30, 0]` | all five mirrored; status `2 → 1`; standard acknowledgement |
| 6 | `+17:38` | FC16 `44105/6` | `[2, 0xFFFF, 0xFEFB, 0x0410, 20, 95]` | five mirrored; `44108` retained because `0x0410` sets reserved bit 10; status `1 → 2`; standard acknowledgement |

Under Smart Control V1.0, each pair writes the five-word system-settings block
and the six effective real-time words `44105–44110`. Tibber did not include
reserved `44111–44115`. The first pair enables both limits at raw 30
(`3000 W`), selects battery mode, requests zero power, and supplies a
`0–100%` SoC window. The second pair changes the failsafe from 27 to 12 minutes
while repeating that zero target. Because the pairs are 15 minutes and
7 seconds apart, their resulting expiry times differ by only 7 seconds. That
strongly suggests Tibber recalculated remaining validity toward a common
deadline; it does not establish a general heartbeat cadence.

The third pair sets a 24-minute failsafe, keeps the import ceiling at
`3000 W`, sets the enabled export ceiling to `0 W`, selects battery mode, and
writes words consistent with the fake high-word-first S32 value
`0xFFFFFEFB`. Under that reconciled encoding the raw value is `-261`, or
`-2610 W` at `10 W/raw`; in mode 2 the official sign convention makes it a
2.61 kW battery discharge request. Its valid SoC window is `20–95%`.

Both rejected `44108` values duplicate their defined grid-charge field from
bits `4–5` into reserved bits `10–11`: value 2 in `0x0820`, then value 1 in
`0x0410`. That repeated structure suggests systematic duplication and records
a concrete Tibber/V01 interoperability conflict. It still does not establish
the reserved field's meaning or prove that a covered physical inverter accepts
it.

No address at or above `44116` was written, so none of the three pairs is a
Time-of-Use payload in protocol terms. The excerpt proves the exact frames,
relative timing at log-second resolution, acknowledgements, requested targets,
and continued steady-state polling. Regression tests separately verify fake
readback and `34504` transitions. The excerpt does not include FC3 readback, a
`34504` status read, an independently recorded Tibber UI result, cancellation,
failsafe expiry, or evidence that a schedule or physical command ran. The
write values are consumer behavior, not authority for physical-inverter
operation or for the reserved bits.

The `IDENTITY_AND_INITIAL_READ_CASES` table preserves these earlier FC4 reads
at connection and approximately hourly:

| Start / quantity | Base-profile response |
|---|---|
| `33004/15` | first 15 canonical serial words |
| `33067/1` | unowned input baseline, otherwise zero |
| `34502/2` | fake management capability/version when enabled; otherwise zero |
| `35000/1` | validated inverter type code |

It also records one-time FC3 requests for `43010/2`, `43052/1`, `43073/2`,
`43110/1`, `43140/1`, and `43483/6`. They returned zero in the observed
disabled/default state. These are now profile-owned settings or protected
zeroes except for unresolved gaps within wider reads. When opt-in smart
management is enabled, their configured fake defaults and accepted fake-write
overlays are returned. The newer grouped requests do not invalidate the
earlier observed shapes.

## Register ownership and file precedence

FC4 input reads resolve:

```text
profile-owned input -> registers.json input baseline -> zero
```

FC3 holding reads resolve according to ownership and feature state:

```text
enabled fake-management address:
    accepted fake write overlay -> configured profile default
disabled/protected fake-management address:
    profile-owned zero
unowned holding address:
    fake write overlay -> registers.json holding baseline -> zero
```

Profile-owned input and holding addresses always win and are rejected in their
respective `registers.json` banks. Disabled optional telemetry and disabled
fake management remain reserved at zero. FC6/FC16 can change only accepted
fake holding readback when `mirror_writes` is enabled; they never affect an
input baseline or external system. A file reload replaces the two baselines
atomically and never erases the overlay; restart clears it.

The newly profile-owned `33073–33080` input words therefore cannot be seeded
from `registers.json`. The fixed synthetic 230.0 V (`2300` raw) applies only
where no HA voltage source is configured: at `33073` for every fake type and
also at `33074–33075` for fake types `2050`/`2060`. Types `2030`/`2040` and
all other type codes receive synthetic A only. Explicit HA sources take
precedence on all channels, including B/C on a single-phase fake type. A
configured source outage follows `inverter_ac_voltage_unavailable_behavior`
(`zero` or `last_known`), never synthetic fallback. This is emulator policy,
not a claim that the inverter is online or that a 3P3W line-to-line voltage
equals 230 V. Inverter AC active power at `33079–33080` is never copied from
PV/DC power at `33057–33058` or meter power at `33263–33264`.

The only valid file shape is:

```json
{
  "input": {"33067": 0},
  "holding": {"45000": 0}
}
```

A flat object, unknown bank, profile-owned address including `35000`, invalid
address, Boolean, non-integer, or value outside `0..65535` is rejected. Invalid
startup content prevents the server from starting. Invalid hot reload content
retains the last valid baselines and overlay.

## Verification boundary

The parameterized tests verify regression behavior and preserve observed
request shapes, but they do not replace a complete consumer test. The
2026-07-26 runtime evidence now confirms an observed Tibber discovery burst,
continued polling, and three acknowledged two-frame FC16 Remote Dispatch
bursts. The final payload is consistent with the fake profile's signed
nonzero-discharge interpretation. The evidence still lacks independent UI
acceptance, FC3 readback after the writes, cancellation, failsafe expiry, or
proof of schedule execution. Before releasing 0.9.0, record those outcomes
and which values Tibber displays. The supplied steady-state requests do not
include `33029–33030` or `33035`, so loss of an energy display remains a known
investigation point. The later `33070/26` read shows that Tibber samples the
AC block; it does not establish that populating it restores historical graphs.
