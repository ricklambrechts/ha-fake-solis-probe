#!/usr/bin/env python3
"""Modbus register, request-shape, bank, and file-loading tests."""

from __future__ import annotations

import json
import struct
import threading
import time
from pathlib import Path
from typing import NamedTuple
from unittest import mock

import pytest
from test_support import (
    AC_GRID_PORT_ENTITY,
    BACKUP_ENTITY,
    BATTERY_POWER_ENTITY,
    BATTERY_SOC_ENTITY,
    GRID_ENTITY,
    PV_ENTITY,
    ProbeTestCase,
    canonical_options,
    canonical_payloads,
    load_probe,
    process_pdu,
    read_request_pdu,
    response_words,
    set_cache,
    state_payload,
    validate_and_initialize,
    write_multiple_pdu,
    write_single_pdu,
)


class CorrectedReadCase(NamedTuple):
    id: str
    function_code: int
    unit_id: int
    start_address: int
    quantity: int
    corrected_words: tuple[int, ...]
    corrected_pdu_hex: str
    illustrative_before_pdu_hex: str


class ObservedReadCase(NamedTuple):
    id: str
    function_code: int
    unit_id: int
    start_address: int
    quantity: int
    expected_words: tuple[int, ...]


class RemoteDispatchBurst(NamedTuple):
    sequence: int
    elapsed_seconds_from_first_burst: int
    system_words: tuple[int, ...]
    realtime_words: tuple[int, ...]
    expected_readback: tuple[int, ...]


SERIAL_WORDS = (
    21573,
    21332,
    11603,
    17746,
    18753,
    19501,
    12336,
    12337,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
)

CORRECTED_FC4_CASES = (
    CorrectedReadCase(
        "steady_state_pv_power_unchanged",
        4,
        1,
        33057,
        2,
        (1, 4464),
        "040400011170",
        "040400011170",
    ),
    CorrectedReadCase(
        "parallel_inverter_power_remains_blocked",
        4,
        1,
        33245,
        1,
        (0,),
        "04020000",
        "04020000",
    ),
    CorrectedReadCase(
        "removed_generation_payload_at_34391",
        4,
        1,
        34391,
        3,
        (0, 0, 0),
        "0406000000000000",
        "0406000aae690000",
    ),
    CorrectedReadCase(
        "operating_status_replaces_historical_local_label",
        4,
        1,
        33121,
        1,
        (1,),
        "04020001",
        "04020000",
    ),
    CorrectedReadCase(
        "no_battery_observed_block_shape",
        4,
        1,
        33135,
        17,
        (0,) * 17,
        "042200000000000000000000000000000000000000000000000000000000000000000000",
        "042200000000000000000000000000000000000000000000000000000000000000000000",
    ),
    CorrectedReadCase(
        "meter_total_active_power_unchanged",
        4,
        1,
        33263,
        2,
        (0xFFFF, 0xFCE0),
        "0404fffffce0",
        "0404fffffce0",
    ),
    CorrectedReadCase(
        "unverified_34351_remains_blocked",
        4,
        1,
        34351,
        1,
        (0,),
        "04020000",
        "04020000",
    ),
    CorrectedReadCase(
        "removed_generation_payload_at_34621",
        4,
        1,
        34621,
        2,
        (0, 0),
        "040400000000",
        "04040000007b",
    ),
    CorrectedReadCase(
        "canonical_total_pv_generation_added",
        4,
        1,
        33029,
        2,
        (1, 4464),
        "040400011170",
        "040400000000",
    ),
    CorrectedReadCase(
        "canonical_daily_pv_generation_added",
        4,
        1,
        33035,
        1,
        (123,),
        "0402007b",
        "04020000",
    ),
    CorrectedReadCase(
        "serial_15_word_observed_subrange",
        4,
        1,
        33004,
        15,
        SERIAL_WORDS[:15],
        "041e544553542d53455249414c2d303030310000000000000000000000000000",
        "041e4d4f44454c2d4f4c4420544553542d53455249414c2d3030303100000000",
    ),
    CorrectedReadCase(
        "serial_16_word_canonical_field",
        4,
        1,
        33004,
        16,
        SERIAL_WORDS,
        "0420544553542d53455249414c2d3030303100000000000000000000000000000000",
        "04204d4f44454c2d4f4c4420544553542d53455249414c2d30303031000000000000",
    ),
    CorrectedReadCase(
        "incomplete_grid_port_pair_remains_blocked",
        4,
        1,
        33151,
        2,
        (0, 0),
        "040400000000",
        "040400000000",
    ),
)

CORRECTED_FC4_BY_REQUEST = {
    (
        case.function_code,
        case.start_address,
        case.quantity,
    ): case
    for case in CORRECTED_FC4_CASES
}

STEADY_STATE_CASES = tuple(
    pytest.param(
        CORRECTED_FC4_BY_REQUEST[key],
        id=f"{sequence:02d}-{CORRECTED_FC4_BY_REQUEST[key].id}",
    )
    for sequence, key in enumerate(
        (
            (4, 33057, 2),
            (4, 33245, 1),
            (4, 34391, 3),
            (4, 33121, 1),
            (4, 33135, 17),
            (4, 33263, 2),
            (4, 34351, 1),
            (4, 34621, 2),
        ),
        start=1,
    )
)

IDENTITY_AND_INITIAL_READ_CASES = (
    ObservedReadCase(
        "connection-hourly-serial",
        4,
        1,
        33004,
        15,
        SERIAL_WORDS[:15],
    ),
    ObservedReadCase("connection-hourly-33067", 4, 1, 33067, 1, (0,)),
    ObservedReadCase("connection-hourly-34502", 4, 1, 34502, 2, (0, 0)),
    ObservedReadCase("connection-hourly-model-type", 4, 1, 35000, 1, (2030,)),
    ObservedReadCase("initial-holding-43010", 3, 1, 43010, 2, (0, 0)),
    ObservedReadCase("initial-holding-43052", 3, 1, 43052, 1, (0,)),
    ObservedReadCase("initial-holding-43073", 3, 1, 43073, 2, (0, 0)),
    ObservedReadCase("initial-holding-43110", 3, 1, 43110, 1, (0,)),
    ObservedReadCase("initial-holding-43140", 3, 1, 43140, 1, (0,)),
    ObservedReadCase(
        "initial-holding-43483",
        3,
        1,
        43483,
        6,
        (0, 0, 0, 0, 0, 0),
    ),
)

DISCOVERY_READ_CASES = (
    ObservedReadCase(
        "01-input-33000",
        4,
        1,
        33000,
        20,
        (0, 0, 0, 0) + SERIAL_WORDS,
    ),
    ObservedReadCase("02-input-33067", 4, 1, 33067, 3, (0, 0, 0)),
    ObservedReadCase("03-input-34502", 4, 1, 34502, 2, (0, 0)),
    ObservedReadCase("04-input-model-type", 4, 1, 35000, 1, (2030,)),
    ObservedReadCase("05-holding-43010", 3, 1, 43010, 2, (0, 0)),
    ObservedReadCase("06-holding-43052", 3, 1, 43052, 23, (0,) * 23),
    ObservedReadCase("07-holding-43110", 3, 1, 43110, 1, (0,)),
    ObservedReadCase("08-holding-43140", 3, 1, 43140, 1, (0,)),
    ObservedReadCase("09-holding-43384", 3, 1, 43384, 1, (0,)),
    ObservedReadCase("10-holding-43483", 3, 1, 43483, 6, (0,) * 6),
)

REMOTE_DISPATCH_BURSTS = (
    RemoteDispatchBurst(
        1,
        0,
        (1, 27, 3, 30, 30),
        (2, 0, 0, 0x0820, 0, 100),
        (1, 27, 3, 30, 30, 2, 0, 0, 0, 0, 100),
    ),
    RemoteDispatchBurst(
        2,
        907,
        (1, 12, 3, 30, 30),
        (2, 0, 0, 0x0820, 0, 100),
        (1, 12, 3, 30, 30, 2, 0, 0, 0, 0, 100),
    ),
    RemoteDispatchBurst(
        3,
        1058,
        (1, 24, 3, 30, 0),
        (2, 0xFFFF, 0xFEFB, 0x0410, 20, 95),
        (1, 24, 3, 30, 0, 2, 0xFFFF, 0xFEFB, 0, 20, 95),
    ),
)


def battery_options(**overrides):
    options = canonical_options(
        battery_attached=True,
        ha_sensor_battery_soc=BATTERY_SOC_ENTITY,
        ha_sensor_battery_power=BATTERY_POWER_ENTITY,
    )
    options.update(overrides)
    return options


def battery_payloads(*, soc="64", power="2500"):
    payloads = canonical_payloads()
    payloads[BATTERY_SOC_ENTITY] = state_payload(
        soc,
        unit="%",
        friendly_name="Test battery state of charge",
    )
    payloads[BATTERY_POWER_ENTITY] = state_payload(
        power,
        device_class="power",
        unit="W",
        friendly_name="Test battery power",
    )
    return payloads


class EncoderAndIdentityTests(ProbeTestCase):
    def test_u16_and_s16_boundaries_and_types(self):
        self.assertEqual(self.module._to_u16_word(0), 0)
        self.assertEqual(self.module._to_u16_word(65535), 65535)
        for invalid in (-1, 65536):
            with (
                self.subTest(kind="u16-range", invalid=invalid),
                self.assertRaises(ValueError),
            ):
                self.module._to_u16_word(invalid)
        for invalid in (True, 1.0, "1"):
            with (
                self.subTest(kind="u16-type", invalid=invalid),
                self.assertRaises(TypeError),
            ):
                self.module._to_u16_word(invalid)

        expected = {
            -32768: 0x8000,
            -1: 0xFFFF,
            0: 0,
            32767: 0x7FFF,
        }
        for value, word in expected.items():
            with self.subTest(kind="s16", value=value):
                self.assertEqual(self.module._to_s16_word(value), word)
        for invalid in (-32769, 32768):
            with (
                self.subTest(kind="s16-range", invalid=invalid),
                self.assertRaises(ValueError),
            ):
                self.module._to_s16_word(invalid)
        with self.assertRaises(TypeError):
            self.module._to_s16_word(False)

    def test_u32_and_s32_boundaries_word_order_and_twos_complement(self):
        u32_cases = {
            0: (0, 0),
            65536: (1, 0),
            70000: (1, 4464),
            (1 << 32) - 1: (0xFFFF, 0xFFFF),
        }
        for value, words in u32_cases.items():
            with self.subTest(kind="u32", value=value):
                self.assertEqual(self.module._to_u32_pair(value), words)
        for invalid in (-1, 1 << 32):
            with (
                self.subTest(kind="u32-range", invalid=invalid),
                self.assertRaises(ValueError),
            ):
                self.module._to_u32_pair(invalid)
        with self.assertRaises(TypeError):
            self.module._to_u32_pair(True)

        s32_cases = {
            -(1 << 31): (0x8000, 0),
            -800: (0xFFFF, 0xFCE0),
            -1: (0xFFFF, 0xFFFF),
            0: (0, 0),
            (1 << 31) - 1: (0x7FFF, 0xFFFF),
        }
        for value, words in s32_cases.items():
            with self.subTest(kind="s32", value=value):
                self.assertEqual(self.module._to_s32_pair(value), words)
        for invalid in (-(1 << 31) - 1, 1 << 31):
            with (
                self.subTest(kind="s32-range", invalid=invalid),
                self.assertRaises(ValueError),
            ):
                self.module._to_s32_pair(invalid)
        with self.assertRaises(TypeError):
            self.module._to_s32_pair(1.5)

    def test_serial_is_exactly_sixteen_words_and_never_contains_model(self):
        self.module.OPTIONS["fake_inverter_model"] = "MODEL-OLD"
        self.assert_valid_and_initialize()
        expected = [
            21573,
            21332,
            11603,
            17746,
            18753,
            19501,
            12336,
            12337,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]

        self.assertEqual(
            self.module.read_input_registers(33004, 15),
            expected[:15],
        )
        self.assertEqual(
            self.module.read_input_registers(33004, 16),
            expected,
        )
        wire = b"".join(struct.pack(">H", word) for word in expected)
        self.assertEqual(wire[:16], b"TEST-SERIAL-0001")
        self.assertNotIn(b"MODEL-OLD", wire)

    def test_serial_encoder_accepts_32_ascii_bytes_and_rejects_longer(self):
        serial = "x" * 32
        words = self.module._encode_serial_words(serial)
        self.assertEqual(len(words), 16)
        self.assertEqual(
            b"".join(struct.pack(">H", word) for word in words),
            serial.encode("ascii"),
        )
        with self.assertRaises(ValueError):
            self.module._encode_serial_words("x" * 33)
        with self.assertRaises(UnicodeEncodeError):
            self.module._encode_serial_words("\N{SNOWMAN}")

    def test_reads_can_start_or_end_inside_multi_register_values(self):
        self.assert_valid_and_initialize()
        self.assertEqual(self.module.read_input_registers(33029, 1), [1])
        self.assertEqual(self.module.read_input_registers(33030, 1), [4464])
        self.assertEqual(self.module.read_input_registers(33057, 1), [1])
        self.assertEqual(self.module.read_input_registers(33058, 1), [4464])
        self.assertEqual(
            self.module.read_input_registers(33263, 1),
            [0xFFFF],
        )
        self.assertEqual(
            self.module.read_input_registers(33264, 1),
            [0xFCE0],
        )

    def test_power_scales_and_both_grid_signs_are_applied_before_encoding(self):
        self.new_probe(
            canonical_options(
                pv_power_scale=2.0,
                grid_power_scale=2.0,
                grid_power_sign_convention="direct",
            )
        )
        self.assert_valid_and_initialize(canonical_payloads(pv="35000.9", grid="-400"))
        self.assertEqual(
            self.module.read_input_registers(33057, 2),
            [1, 4465],
        )
        self.assertEqual(
            self.module.read_input_registers(33263, 2),
            [0xFFFF, 0xFCE0],
        )

        set_cache(self.module, {GRID_ENTITY: 400.0})
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33263, 2),
            [0, 800],
        )

        self.module.OPTIONS["grid_power_sign_convention"] = "negate"
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33263, 2),
            [0xFFFF, 0xFCE0],
        )

        set_cache(self.module, {PV_ENTITY: float(self.module.U32_MAX) + 1})
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33057, 2),
            [0, 0],
            "instantaneous out-of-range PV power must fall back to zero",
        )

    def test_battery_pair_subrange_reads_keep_high_word_first(self):
        self.new_probe(battery_options())
        self.assert_valid_and_initialize(battery_payloads(power="70000"))
        self.assertEqual(self.module.read_input_registers(33149, 1), [1])
        self.assertEqual(self.module.read_input_registers(33150, 1), [4464])

    def test_backup_and_ac_grid_port_power_are_distinct_optional_metrics(self):
        self.new_probe(
            canonical_options(
                ha_sensor_backup_load_power=BACKUP_ENTITY,
                backup_load_power_scale=1.5,
                ha_sensor_ac_grid_port_power=AC_GRID_PORT_ENTITY,
                ac_grid_port_power_scale=2.0,
                ac_grid_port_power_sign_convention="direct",
            )
        )
        payloads = canonical_payloads()
        payloads[BACKUP_ENTITY] = state_payload(
            "1000.9",
            device_class="power",
            unit="W",
        )
        payloads[AC_GRID_PORT_ENTITY] = state_payload(
            "-400",
            device_class="power",
            unit="W",
        )
        self.assert_valid_and_initialize(payloads)

        self.assertEqual(self.module.read_input_registers(33148, 1), [1501])
        self.assertEqual(
            self.module.read_input_registers(33151, 2),
            [0xFFFF, 0xFCE0],
        )
        self.assertEqual(
            self.module.read_input_registers(33151, 1),
            [0xFFFF],
            "the observed Tibber block reads only the high grid-port word",
        )

        self.module.OPTIONS["ac_grid_port_power_sign_convention"] = "negate"
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33151, 2),
            [0, 800],
        )

    def test_blank_backup_and_ac_grid_port_sources_remain_owned_zeroes(self):
        self.assert_valid_and_initialize()
        with self.module.REG_LOCK:
            self.module.INPUT_REGISTER_BASELINE[33148] = 0xBEEF
            self.module.INPUT_REGISTER_BASELINE[33151] = 0xBEEF
            self.module.INPUT_REGISTER_BASELINE[33152] = 0xBEEF

        self.assertEqual(self.module.read_input_registers(33148, 1), [0])
        self.assertEqual(self.module.read_input_registers(33151, 2), [0, 0])


def initialize_pytest_probe(tmp_path: Path, options=None):
    module, events = load_probe(options)
    module.EVENT_DIR = str(tmp_path)
    module.EVENT_LOG = str(tmp_path / "events.jsonl")
    module.REGISTER_FILE = str(tmp_path / "registers.json")
    validate_and_initialize(module, canonical_payloads())
    return module, events


@pytest.fixture
def initialized_probe(tmp_path):
    return initialize_pytest_probe(tmp_path)


# The request shapes below are sanitized consumer observations. They establish
# which requests need responses, while the expected values come from the
# canonical register profile rather than from captured telemetry.
@pytest.mark.parametrize("case", STEADY_STATE_CASES)
def test_ordered_eight_block_steady_state_requests_replay_exactly(
    initialized_probe,
    case,
):
    module, _events = initialized_probe
    response = process_pdu(
        module,
        read_request_pdu(
            case.function_code,
            case.start_address,
            case.quantity,
        ),
        unit_id=case.unit_id,
    )

    assert response.hex() == case.corrected_pdu_hex
    assert response_words(response, case.function_code) == list(case.corrected_words)
    assert response[1] == case.quantity * 2


@pytest.mark.parametrize(
    "case",
    [pytest.param(case, id=case.id) for case in CORRECTED_FC4_CASES],
)
def test_every_before_after_case_serves_only_corrected_payload(
    initialized_probe,
    case,
):
    module, _events = initialized_probe
    response = process_pdu(
        module,
        read_request_pdu(
            case.function_code,
            case.start_address,
            case.quantity,
        ),
        unit_id=case.unit_id,
    )

    assert response.hex() == case.corrected_pdu_hex
    if case.illustrative_before_pdu_hex != case.corrected_pdu_hex:
        assert response.hex() != case.illustrative_before_pdu_hex


@pytest.mark.parametrize(
    "case",
    [pytest.param(case, id=case.id) for case in IDENTITY_AND_INITIAL_READ_CASES],
)
def test_identity_hourly_and_initial_fc3_shapes_receive_full_responses(
    initialized_probe,
    case,
):
    module, _events = initialized_probe
    response = process_pdu(
        module,
        read_request_pdu(
            case.function_code,
            case.start_address,
            case.quantity,
        ),
        unit_id=case.unit_id,
    )
    words = response_words(response, case.function_code)

    assert words == list(case.expected_words)
    assert len(words) == case.quantity
    assert response[1] == case.quantity * 2


@pytest.mark.parametrize(
    "case",
    [pytest.param(case, id=case.id) for case in DISCOVERY_READ_CASES],
)
def test_2026_07_26_discovery_shapes_receive_full_responses(
    initialized_probe,
    case,
):
    module, _events = initialized_probe
    response = process_pdu(
        module,
        read_request_pdu(
            case.function_code,
            case.start_address,
            case.quantity,
        ),
        unit_id=case.unit_id,
    )
    words = response_words(response, case.function_code)

    assert words == list(case.expected_words)
    assert len(words) == case.quantity
    assert response[1] == case.quantity * 2


class CanonicalProfileTests(ProbeTestCase):
    def setUp(self):
        super().setUp()
        self.assert_valid_and_initialize()

    def test_canonical_and_blocked_profile_values_have_exact_precedence(self):
        self.assertEqual(
            self.module.read_input_registers(33029, 2),
            [1, 4464],
        )
        self.assertEqual(self.module.read_input_registers(33035, 1), [123])
        self.assertEqual(
            self.module.read_input_registers(33057, 2),
            [1, 4464],
        )
        self.assertEqual(
            self.module.read_input_registers(33263, 2),
            [0xFFFF, 0xFCE0],
        )
        self.assertEqual(self.module.read_input_registers(33121, 1), [1])
        self.assertEqual(self.module.read_input_registers(35000, 1), [2030])

        blocked_ranges = (
            (33245, 1),
            (34351, 1),
            (34391, 3),
            (34502, 3),
            (34621, 2),
        )
        with self.module.REG_LOCK:
            for start, quantity in blocked_ranges:
                for address in range(start, start + quantity):
                    self.module.INPUT_REGISTER_BASELINE[address] = 0xBEEF

        for start, quantity in blocked_ranges:
            with self.subTest(start=start, quantity=quantity):
                self.assertEqual(
                    self.module.read_input_registers(start, quantity),
                    [0] * quantity,
                )


class RegisterBankAndWriteTests(ProbeTestCase):
    def setUp(self):
        super().setUp()
        self.assert_valid_and_initialize()

    def test_fc4_and_fc3_read_distinct_banks(self):
        with self.module.REG_LOCK:
            self.module.INPUT_REGISTER_BASELINE[42000] = 111
            self.module.HOLDING_REGISTER_BASELINE[42000] = 222

        fc4 = process_pdu(
            self.module,
            read_request_pdu(4, 42000, 1),
        )
        fc3 = process_pdu(
            self.module,
            read_request_pdu(3, 42000, 1),
        )
        self.assertEqual(response_words(fc4, 4), [111])
        self.assertEqual(response_words(fc3, 3), [222])

    def test_fc6_mirror_disabled_acknowledges_without_mutation(self):
        with self.module.REG_LOCK:
            self.module.HOLDING_REGISTER_BASELINE[45000] = 7
        request = write_single_pdu(45000, 99)

        response = process_pdu(self.module, request)

        self.assertEqual(response, request)
        self.assertEqual(
            self.module.read_holding_registers(45000, 1),
            [7],
        )
        self.assertNotIn(45000, self.module.HOLDING_WRITE_OVERLAY)

    def test_fc6_mirror_changes_only_holding_overlay(self):
        self.module.OPTIONS["mirror_writes"] = True
        input_before = self.module.read_input_registers(33057, 2)
        request = write_single_pdu(33057, 0xCAFE)

        response = process_pdu(self.module, request)

        self.assertEqual(response, request)
        self.assertEqual(
            self.module.read_holding_registers(33057, 1),
            [0xCAFE],
        )
        self.assertEqual(
            self.module.read_input_registers(33057, 2),
            input_before,
        )

    def test_fc16_writes_only_holding_and_returns_standard_ack(self):
        self.module.OPTIONS["mirror_writes"] = True
        request = write_multiple_pdu(45000, [1, 0xFFFF, 42])

        response = process_pdu(self.module, request)

        self.assertEqual(
            response,
            bytes([16]) + struct.pack(">HH", 45000, 3),
        )
        self.assertEqual(
            self.module.read_holding_registers(45000, 3),
            [1, 0xFFFF, 42],
        )
        self.assertEqual(
            self.module.read_input_registers(45000, 3),
            [0, 0, 0],
        )

    def test_fc16_mirror_disabled_acknowledges_without_mutation(self):
        with self.module.REG_LOCK:
            self.module.HOLDING_REGISTER_BASELINE[45000] = 7
            self.module.HOLDING_REGISTER_BASELINE[45001] = 8
        request = write_multiple_pdu(45000, [91, 92])

        response = process_pdu(self.module, request)

        self.assertEqual(
            response,
            bytes([16]) + struct.pack(">HH", 45000, 2),
        )
        self.assertEqual(
            self.module.read_holding_registers(45000, 2),
            [7, 8],
        )
        self.assertEqual(self.module.HOLDING_WRITE_OVERLAY, {})

    def test_malformed_fc6_and_fc16_never_mutate_overlay(self):
        self.module.OPTIONS["mirror_writes"] = True
        malformed_fc6 = (
            b"\x06",
            b"\x06\x00\x01",
            b"\x06\x00\x01\x00\x02\x00",
        )
        for request in malformed_fc6:
            with self.subTest(function_code=6, request=request.hex()):
                before = dict(self.module.HOLDING_WRITE_OVERLAY)
                self.assertEqual(
                    process_pdu(self.module, request),
                    bytes([0x86, 3]),
                )
                self.assertEqual(
                    self.module.HOLDING_WRITE_OVERLAY,
                    before,
                )

        malformed_fc16 = (
            b"\x10",
            bytes([16]) + struct.pack(">HHB", 43010, 0, 0),
            bytes([16]) + struct.pack(">HHB", 43010, 2, 2) + b"\x00\x01",
            bytes([16]) + struct.pack(">HHB", 43010, 1, 2) + b"\x00\x01\x00",
            bytes([16]) + struct.pack(">HHB", 43010, 124, 248) + bytes(248),
        )
        for request in malformed_fc16:
            with self.subTest(function_code=16, request_length=len(request)):
                before = dict(self.module.HOLDING_WRITE_OVERLAY)
                self.assertEqual(
                    process_pdu(self.module, request),
                    bytes([0x90, 3]),
                )
                self.assertEqual(
                    self.module.HOLDING_WRITE_OVERLAY,
                    before,
                )

        overflow = bytes([16]) + struct.pack(">HHB", 65535, 2, 4) + b"\x00\x01\x00\x02"
        before = dict(self.module.HOLDING_WRITE_OVERLAY)
        self.assertEqual(
            process_pdu(self.module, overflow),
            bytes([0x90, 2]),
        )
        self.assertEqual(self.module.HOLDING_WRITE_OVERLAY, before)

    def test_profile_reinitialization_clears_write_overlay(self):
        self.module.write_holding_registers(45000, [123])
        self.assertEqual(
            self.module.read_holding_registers(45000, 1),
            [123],
        )

        self.module.initialize_profile_registers()

        self.assertEqual(
            self.module.read_holding_registers(45000, 1),
            [0],
        )


@pytest.fixture
def smart_management_probe(tmp_path):
    return initialize_pytest_probe(
        tmp_path,
        canonical_options(
            mirror_writes=True,
            smart_management_enabled=True,
            fake_hmi_sub_version=7,
            fake_inverter_type_code=2050,
        ),
    )


@pytest.mark.parametrize(
    "burst",
    [
        pytest.param(
            burst,
            id=(f"burst-{burst.sequence}-at-{burst.elapsed_seconds_from_first_burst}s"),
        )
        for burst in REMOTE_DISPATCH_BURSTS
    ],
)
def test_observed_tibber_remote_dispatch_fc16_bursts(
    smart_management_probe,
    burst,
):
    module, events = smart_management_probe

    for start_address, words in (
        (44100, burst.system_words),
        (44105, burst.realtime_words),
    ):
        response = process_pdu(
            module,
            write_multiple_pdu(start_address, words),
            unit_id=1,
        )
        assert response == bytes([16]) + struct.pack(
            ">HH",
            start_address,
            len(words),
        )

    assert module.read_holding_registers(44100, 11) == list(burst.expected_readback)
    assert 44108 not in module.HOLDING_WRITE_OVERLAY
    assert module.read_input_registers(34504, 1) == [2]
    assert [
        (event["previous"], event["current"])
        for event in events
        if event["kind"] == "remote_dispatch_status_changed"
    ] == [(0, 1), (1, 2)]

    write_events = [
        event for event in events if event["kind"] == "modbus_write_multiple_registers"
    ]
    assert [
        (
            event["addr"],
            event["qty"],
            event["mirrored_count"],
            event["profile_blocked_count"],
        )
        for event in write_events
    ] == [
        (44100, 5, 5, 0),
        (44105, 6, 5, 1),
    ]


class SmartManagementProfileTests(ProbeTestCase):
    def setUp(self):
        super().setUp()
        self.new_probe(
            canonical_options(
                mirror_writes=True,
                smart_management_enabled=True,
                fake_hmi_sub_version=7,
                fake_inverter_type_code=2050,
            )
        )
        self.assert_valid_and_initialize()

    def test_capability_and_verified_defaults_cover_the_tibber_scan(self):
        self.assertEqual(self.module.read_input_registers(33067, 3), [0, 0, 7])
        self.assertEqual(
            self.module.read_input_registers(34502, 3),
            [0xAA55, 1, 0],
        )
        self.assertEqual(self.module.read_holding_registers(43010, 2), [95, 20])
        self.assertEqual(self.module.read_holding_registers(43052, 1), [10000])
        self.assertEqual(self.module.read_holding_registers(43073, 2), [0, 0])
        self.assertEqual(self.module.read_holding_registers(43110, 1), [33])
        self.assertEqual(self.module.read_holding_registers(43140, 1), [0x0105])
        self.assertEqual(self.module.read_holding_registers(43282, 1), [5])
        self.assertEqual(
            self.module.read_holding_registers(43483, 6),
            [0, 0, 0, 0, 20, 0],
        )
        self.assertEqual(
            self.module.read_holding_registers(44100, 11),
            [0, 5, 0, 0, 0, 1, 0, 0, 0, 20, 95],
        )

    def test_remote_dispatch_writes_are_fake_atomic_readback_with_status(self):
        response = process_pdu(self.module, write_single_pdu(44100, 1))
        self.assertEqual(response, write_single_pdu(44100, 1))
        self.assertEqual(self.module.read_holding_registers(44100, 1), [1])
        self.assertEqual(self.module.read_input_registers(34504, 1), [1])

        response = process_pdu(
            self.module,
            write_multiple_pdu(44105, [2, 0xFFFF, 0xFF9C]),
        )
        self.assertEqual(
            response,
            bytes([16]) + struct.pack(">HH", 44105, 3),
        )
        self.assertEqual(
            self.module.read_holding_registers(44105, 3),
            [2, 0xFFFF, 0xFF9C],
        )
        self.assertEqual(self.module.read_input_registers(34504, 1), [2])

        process_pdu(self.module, write_single_pdu(44116, 1))
        self.assertEqual(self.module.read_input_registers(34504, 1), [3])

        process_pdu(self.module, write_single_pdu(44100, 0))
        self.assertEqual(self.module.read_input_registers(34504, 1), [0])

    def test_remote_dispatch_failsafe_expires_lazily_on_next_read(self):
        registers_module = self.module._owners["registers"]
        with mock.patch.object(
            registers_module.time,
            "monotonic",
            return_value=1000.0,
        ):
            process_pdu(self.module, write_single_pdu(44100, 1))
            self.assertEqual(self.module.read_input_registers(34504, 1), [1])

        with mock.patch.object(
            registers_module.time,
            "monotonic",
            return_value=1301.0,
        ):
            self.assertEqual(self.module.read_input_registers(34504, 1), [0])
        self.assertEqual(self.module.read_holding_registers(44100, 1), [0])
        self.assertTrue(
            any(
                event["kind"] == "remote_dispatch_failsafe_expired"
                for event in self.events
            )
        )

    def test_blocked_unknown_holding_words_ignore_fake_writes(self):
        for address in (
            43384,
            43484,
            43485,
            43486,
            44111,
            44124,
            44139,
            44153,
            44167,
            44181,
            44195,
        ):
            with self.subTest(address=address):
                process_pdu(self.module, write_single_pdu(address, 0xBEEF))
                self.assertEqual(
                    self.module.read_holding_registers(address, 1),
                    [0],
                )
                self.assertNotIn(address, self.module.HOLDING_WRITE_OVERLAY)

    def test_invalid_remote_dispatch_writes_retain_previous_readback(self):
        cases = (
            (44100, 2),
            (44101, 0),
            (44102, 4),
            (44105, 5),
            (44108, 3),
            (44108, 0x0820),
            (44108, 0x0410),
            (44109, 96),
            (44110, 19),
        )
        for address, invalid in cases:
            with self.subTest(address=address, invalid=invalid):
                before = self.module.read_holding_registers(address, 1)
                process_pdu(
                    self.module,
                    write_single_pdu(address, invalid),
                )
                self.assertEqual(
                    self.module.read_holding_registers(address, 1),
                    before,
                )

        process_pdu(
            self.module,
            write_multiple_pdu(44109, [90, 95]),
        )
        self.assertEqual(
            self.module.read_holding_registers(44109, 2),
            [90, 95],
        )

    def test_legacy_storage_control_rejects_conflicting_modes(self):
        invalid_values = (
            (1 << 0) | (1 << 2),
            (1 << 0) | (1 << 6),
            (1 << 0) | (1 << 11),
            1 << 1,
            (1 << 1) | (1 << 2),
            (1 << 4) | (1 << 11),
            (1 << 6) | (1 << 11),
        )
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                process_pdu(self.module, write_single_pdu(43110, invalid))
                self.assertEqual(
                    self.module.read_holding_registers(43110, 1),
                    [33],
                )

        for valid in (
            (1 << 0) | (1 << 1),
            (1 << 1) | (1 << 6),
            1 << 2,
            (1 << 5) | (1 << 11),
        ):
            with self.subTest(valid=valid):
                process_pdu(self.module, write_single_pdu(43110, valid))
                self.assertEqual(
                    self.module.read_holding_registers(43110, 1),
                    [valid],
                )

    def test_zero_tou_write_does_not_claim_active_tou_control(self):
        process_pdu(self.module, write_single_pdu(44100, 1))
        process_pdu(self.module, write_single_pdu(44116, 0))
        self.assertEqual(self.module.read_input_registers(34504, 1), [1])

        process_pdu(self.module, write_single_pdu(44116, 1))
        self.assertEqual(self.module.read_input_registers(34504, 1), [3])

    def test_remote_dispatch_limit_reset_uses_fake_profile_default(self):
        process_pdu(self.module, write_single_pdu(44104, 120))
        self.assertEqual(self.module.read_holding_registers(44104, 1), [120])

        process_pdu(
            self.module,
            write_single_pdu(44104, self.module.U16_MAX),
        )
        self.assertEqual(self.module.read_holding_registers(44104, 1), [0])

    def test_disabled_profile_does_not_advertise_or_accept_control_words(self):
        self.new_probe(canonical_options(mirror_writes=True))
        self.assert_valid_and_initialize()

        process_pdu(self.module, write_single_pdu(44100, 1))
        process_pdu(self.module, write_single_pdu(43010, 99))

        self.assertEqual(self.module.read_input_registers(34502, 3), [0, 0, 0])
        self.assertEqual(self.module.read_holding_registers(44100, 1), [0])
        self.assertEqual(self.module.read_holding_registers(43010, 1), [0])


class RegisterFileTests(ProbeTestCase):
    def setUp(self):
        super().setUp()
        self.assert_valid_and_initialize()
        self.register_path = Path(self.module.REGISTER_FILE)

    def _write_json(self, value):
        self.register_path.write_text(
            json.dumps(value, sort_keys=True),
            encoding="utf-8",
        )

    def test_only_bank_qualified_strict_values_are_accepted(self):
        accepted = {
            "input": {"33067": 0, "42000": 65535, "43010": 2},
            "holding": {"35000": 1, "45000": 0, "65535": 65535},
        }
        input_values, holding_values = self.module._validate_register_file(accepted)
        self.assertEqual(input_values, {33067: 0, 42000: 65535, 43010: 2})
        self.assertEqual(
            holding_values,
            {35000: 1, 45000: 0, 65535: 65535},
        )

        invalid_values = (
            {"33067": 1},
            {"unknown": {}},
            {"input": []},
            {"input": {"-1": 0}},
            {"input": {"1.5": 0}},
            {"input": {"65536": 0}},
            {"input": {"33067": True}},
            {"input": {"33067": 1.5}},
            {"input": {"33067": -1}},
            {"input": {"33067": 65536}},
            {"input": {"35000": 1}},
            {"input": {"33057": 1}},
            {"input": {"33069": 1}},
            {"input": {"34502": 1}},
            {"holding": {"43010": 1}},
            {"holding": {"44100": 1}},
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module._validate_register_file(value)

    def test_valid_startup_file_loads_both_baselines(self):
        self._write_json(
            {
                "input": {"33067": 7},
                "holding": {"45000": 8},
            }
        )

        self.assertTrue(self.module.load_register_file_if_changed(startup=True))
        self.assertEqual(
            self.module.read_input_registers(33067, 1),
            [7],
        )
        self.assertEqual(
            self.module.read_holding_registers(45000, 1),
            [8],
        )
        self.assertEqual(self.module.read_input_registers(35000, 1), [2030])

    def test_invalid_startup_file_fails_and_main_never_starts_server(self):
        self._write_json({"33067": 7})
        self.assertFalse(self.module.load_register_file_if_changed(startup=True))

        called = []
        self.module.validate_config = lambda: True
        self.module.initialize_profile_registers = lambda: called.append("initialize")
        self.module.load_register_file_if_changed = lambda startup=False: not startup
        self.module.serve_modbus = lambda: called.append("serve")

        with mock.patch.object(self.module.os, "makedirs"):
            self.assertEqual(self.module.main(), 1)
        self.assertEqual(called, ["initialize"])

    def test_invalid_hot_reload_retains_last_valid_baselines_and_overlay(self):
        self._write_json(
            {
                "input": {"33067": 7},
                "holding": {"45000": 8},
            }
        )
        self.assertTrue(self.module.load_register_file_if_changed(startup=True))
        self.module.write_holding_registers(45000, [99])

        self._write_json(
            {
                "input": {"33067": -12345},
                "holding": {},
                "padding": "force a different fingerprint",
            }
        )
        self.assertTrue(self.module.load_register_file_if_changed())

        self.assertEqual(
            self.module.read_input_registers(33067, 1),
            [7],
        )
        self.assertEqual(
            self.module.read_holding_registers(45000, 1),
            [99],
        )
        errors = [
            event
            for event in self.events
            if event["kind"] == "register_file_load_error"
        ]
        self.assertTrue(errors)
        self.assertTrue(errors[-1]["retained_last_valid"])

    def test_valid_hot_reload_replaces_baselines_but_preserves_overlay(self):
        self._write_json(
            {
                "input": {"33067": 7},
                "holding": {"45000": 8, "45001": 9},
            }
        )
        self.assertTrue(self.module.load_register_file_if_changed(startup=True))
        self.module.write_holding_registers(45000, [99])

        self._write_json(
            {
                "input": {"33067": 17, "33068": 18},
                "holding": {"45000": 28, "45001": 29},
            }
        )
        self.assertTrue(self.module.load_register_file_if_changed())

        self.assertEqual(
            self.module.read_input_registers(33067, 2),
            [17, 18],
        )
        self.assertEqual(
            self.module.read_holding_registers(45000, 2),
            [99, 29],
        )

    def test_file_removal_clears_baselines_but_not_write_overlay(self):
        self._write_json(
            {
                "input": {"33067": 7},
                "holding": {"45000": 8},
            }
        )
        self.assertTrue(self.module.load_register_file_if_changed(startup=True))
        self.module.write_holding_registers(45000, [99])
        self.register_path.unlink()

        self.assertTrue(self.module.load_register_file_if_changed())
        self.assertEqual(
            self.module.read_input_registers(33067, 1),
            [0],
        )
        self.assertEqual(
            self.module.read_holding_registers(45000, 1),
            [99],
        )

    def test_profile_layer_wins_even_if_baseline_is_mutated_internally(self):
        with self.module.REG_LOCK:
            self.module.INPUT_REGISTER_BASELINE[33121] = 0xBEEF
            self.module.INPUT_REGISTER_BASELINE[35000] = 0xBEEF

        self.assertEqual(self.module.read_input_registers(33121, 1), [1])
        self.assertEqual(self.module.read_input_registers(35000, 1), [2030])


class AtomicBatterySnapshotTests(ProbeTestCase):
    def test_concurrent_reads_never_observe_mixed_direction_and_magnitude(self):
        self.new_probe(battery_options())
        self.assert_valid_and_initialize(battery_payloads(soc="64", power="111111"))
        states = (
            (111111.0, 1, self.module._to_s32_pair(111111)),
            (-222222.0, 0, self.module._to_s32_pair(222222)),
        )
        set_cache(
            self.module,
            {BATTERY_POWER_ENTITY: states[0][0]},
        )
        self.module.update_live_registers()

        allowed = {(direction, pair[0], pair[1]) for _power, direction, pair in states}
        start = threading.Event()
        failures = []

        def writer():
            start.wait()
            for index in range(1500):
                power, _direction, _pair = states[index % len(states)]
                set_cache(
                    self.module,
                    {BATTERY_POWER_ENTITY: power},
                )
                self.module.update_live_registers()
                if index % 20 == 0:
                    time.sleep(0)

        def reader():
            start.wait()
            for index in range(3000):
                words = self.module.read_input_registers(33135, 16)
                snapshot = (words[0], words[14], words[15])
                if snapshot not in allowed:
                    failures.append(snapshot)
                    return
                if index % 20 == 0:
                    time.sleep(0)

        writer_thread = threading.Thread(target=writer, name="test-writer")
        reader_thread = threading.Thread(target=reader, name="test-reader")
        writer_thread.start()
        reader_thread.start()
        start.set()
        writer_thread.join(timeout=10)
        reader_thread.join(timeout=10)

        self.assertFalse(writer_thread.is_alive(), "writer thread hung")
        self.assertFalse(reader_thread.is_alive(), "reader thread hung")
        self.assertEqual(failures, [])


class ProtocolFramingTests(ProbeTestCase):
    class FakeSocket:
        def __init__(self, incoming):
            self.incoming = bytearray(incoming)
            self.sent = bytearray()

        def recv(self, quantity):
            if not self.incoming:
                return b""
            chunk = bytes(self.incoming[:quantity])
            del self.incoming[:quantity]
            return chunk

        def sendall(self, data):
            self.sent.extend(data)

    def setUp(self):
        super().setUp()
        self.assert_valid_and_initialize()

    def _handle_frame(self, frame):
        handler = object.__new__(self.module.ModbusHandler)
        handler.request = self.FakeSocket(frame)
        handler.client_address = ("192.0.2.1", 1502)
        handler.handle()
        return bytes(handler.request.sent)

    def test_mbap_accepts_253_byte_pdu_and_rejects_larger_length(self):
        pdu = bytes([8]) + bytes(252)
        header = struct.pack(
            ">HHHB",
            7,
            0,
            self.module.MAX_MBAP_LENGTH,
            1,
        )
        sent = self._handle_frame(header + pdu)
        self.assertEqual(len(sent), 7 + self.module.MAX_MODBUS_PDU_LENGTH)
        transaction_id, protocol, length, unit_id = struct.unpack(
            ">HHHB",
            sent[:7],
        )
        self.assertEqual(
            (transaction_id, protocol, length, unit_id),
            (7, 0, self.module.MAX_MBAP_LENGTH, 1),
        )
        self.assertEqual(sent[7:], pdu)

        oversized_header = struct.pack(
            ">HHHB",
            8,
            0,
            self.module.MAX_MBAP_LENGTH + 1,
            1,
        )
        self.assertEqual(self._handle_frame(oversized_header), b"")

    def test_bit_and_multiple_write_address_overflow_use_exception_two(self):
        for function_code in (1, 2):
            with self.subTest(function_code=function_code):
                response = process_pdu(
                    self.module,
                    read_request_pdu(function_code, 65535, 2),
                )
                self.assertEqual(
                    response,
                    bytes([function_code | 0x80, 2]),
                )

        fc15 = bytes([15]) + struct.pack(">HHB", 65535, 2, 1) + b"\x00"
        self.assertEqual(
            process_pdu(self.module, fc15),
            bytes([0x8F, 2]),
        )

    def test_diagnostics_require_minimum_framing(self):
        self.assertEqual(
            process_pdu(self.module, b"\x08\x00"),
            bytes([0x88, 3]),
        )
        valid = b"\x08\x00\x00\x12\x34"
        self.assertEqual(process_pdu(self.module, valid), valid)

    def test_device_identification_paginates_without_exceeding_pdu_cap(self):
        self.module.OPTIONS.update(
            {
                "fake_vendor": "V" * 240,
                "fake_inverter_model": "M" * 240,
                "fake_logger_model": "L" * 240,
            }
        )

        first = process_pdu(self.module, bytes([43, 0x0E, 1, 0]))
        self.assertLessEqual(
            len(first),
            self.module.MAX_MODBUS_PDU_LENGTH,
        )
        self.assertEqual(first[:4], bytes([0x2B, 0x0E, 1, 0x03]))
        self.assertEqual(first[4], 0xFF)
        self.assertEqual(first[5], 1)
        self.assertEqual(first[6], 1)

        second = process_pdu(self.module, bytes([43, 0x0E, 1, 1]))
        self.assertLessEqual(
            len(second),
            self.module.MAX_MODBUS_PDU_LENGTH,
        )
        self.assertEqual(second[4], 0xFF)
        self.assertEqual(second[5], 2)
        self.assertEqual(second[6], 1)
