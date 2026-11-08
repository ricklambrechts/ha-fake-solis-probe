#!/usr/bin/env python3
"""Dependency-free regression tests for fake Remote Dispatch V02."""

from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_support import (
    ProbeTestCase,
    canonical_options,
    process_pdu,
    read_request_pdu,
    response_words,
    write_multiple_pdu,
    write_single_pdu,
)


class RemoteDispatchV02Tests(ProbeTestCase):
    def setUp(self):
        super().setUp()
        self.new_probe(
            canonical_options(mirror_writes=True, smart_management_enabled=True)
        )
        self.assert_valid_and_initialize()

    def test_enabled_profile_advertises_v02(self):
        response = process_pdu(self.module, read_request_pdu(4, 34502, 3))
        self.assertEqual(response_words(response, 4), [0xAA55, 2, 0])

    def test_runtime_version_matches_app_manifest(self):
        manifest = Path(__file__).resolve().parents[1] / "config.yaml"
        version_line = next(
            line
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.startswith("version:")
        )
        manifest_version = version_line.split(":", 1)[1].strip().strip("\"'")
        self.assertEqual(self.module.VERSION, manifest_version)

    def test_observed_function_words_round_trip(self):
        for value in (0x0410, 0x0820):
            with self.subTest(value=value):
                request = write_single_pdu(44108, value)
                self.assertEqual(process_pdu(self.module, request), request)
                response = process_pdu(self.module, read_request_pdu(3, 44108, 1))
                self.assertEqual(response_words(response, 3), [value])

    def test_each_v02_function_field_accepts_one_and_two(self):
        for shift in (0, 2, 4, 6, 8, 10, 12):
            for choice in (1, 2):
                value = choice << shift
                with self.subTest(shift=shift, choice=choice):
                    process_pdu(self.module, write_single_pdu(44108, value))
                    self.assertEqual(
                        self.module.read_holding_registers(44108, 1), [value]
                    )

    def test_invalid_v02_function_word_retains_previous_readback(self):
        process_pdu(self.module, write_single_pdu(44108, 0x0410))
        invalid_words = (0, 0x4000, 0x8000) + tuple(
            3 << shift for shift in (0, 2, 4, 6, 8, 10, 12)
        )
        for value in invalid_words:
            with self.subTest(value=value):
                request = write_single_pdu(44108, value)
                self.assertEqual(process_pdu(self.module, request), request)
                self.assertEqual(self.module.read_holding_registers(44108, 1), [0x0410])

    def test_mixed_zero_fields_mirror_raw_command_without_merging(self):
        process_pdu(self.module, write_single_pdu(44108, 0x0410))
        process_pdu(self.module, write_single_pdu(44108, 0x0800))
        self.assertEqual(self.module.read_holding_registers(44108, 1), [0x0800])

    def test_v02_modes_are_reflected_in_fake_status(self):
        process_pdu(self.module, write_single_pdu(44100, 1))
        self.assertEqual(self.module.read_input_registers(34504, 1), [1])
        for mode in (5, 6):
            with self.subTest(mode=mode):
                process_pdu(self.module, write_single_pdu(44105, mode))
                self.assertEqual(self.module.read_holding_registers(44105, 1), [mode])
                self.assertEqual(
                    self.module.read_input_registers(34504, 1), [(mode << 8) | 2]
                )

        process_pdu(self.module, write_single_pdu(44105, 7))
        self.assertEqual(self.module.read_holding_registers(44105, 1), [6])
        self.assertEqual(self.module.read_input_registers(34504, 1), [0x0602])

    def test_raw_tou_status_has_no_claimed_mode_and_disable_clears_status(self):
        process_pdu(self.module, write_single_pdu(44100, 1))
        process_pdu(self.module, write_single_pdu(44105, 5))
        process_pdu(self.module, write_single_pdu(44116, 1))
        self.assertEqual(self.module.read_input_registers(34504, 1), [3])
        process_pdu(self.module, write_single_pdu(44116, 0))
        self.assertEqual(self.module.read_input_registers(34504, 1), [1])
        process_pdu(self.module, write_single_pdu(44100, 0))
        self.assertEqual(self.module.read_input_registers(34504, 1), [0])

    def test_reserve_soc_default_and_inclusive_limits(self):
        self.assertEqual(self.module.read_holding_registers(44111, 1), [40])
        for value, expected in ((19, 40), (20, 20), (95, 95), (96, 95)):
            with self.subTest(value=value):
                request = write_single_pdu(44111, value)
                self.assertEqual(process_pdu(self.module, request), request)
                self.assertEqual(
                    self.module.read_holding_registers(44111, 1), [expected]
                )

    def test_reserve_limits_follow_nondefault_soc_options(self):
        self.new_probe(
            canonical_options(
                mirror_writes=True,
                smart_management_enabled=True,
                smart_management_min_soc=40,
                smart_management_max_charge_soc=70,
            )
        )
        self.assert_valid_and_initialize()
        for value, expected in ((39, 40), (40, 40), (70, 70), (71, 70)):
            with self.subTest(value=value):
                process_pdu(self.module, write_single_pdu(44111, value))
                self.assertEqual(
                    self.module.read_holding_registers(44111, 1), [expected]
                )

    def test_equal_and_inverted_soc_limits_retain_readback(self):
        for limits in ([45, 45], [70, 60]):
            with self.subTest(limits=limits):
                process_pdu(self.module, write_multiple_pdu(44109, limits))
                self.assertEqual(self.module.read_holding_registers(44109, 2), [20, 95])
        process_pdu(self.module, write_multiple_pdu(44109, [45, 46]))
        self.assertEqual(self.module.read_holding_registers(44109, 2), [45, 46])

    def test_fc16_reserve_uses_accepted_not_rejected_upper_word(self):
        request = write_multiple_pdu(44109, [30, 70, 65])
        self.assertEqual(process_pdu(self.module, request), b"\x10\xac\x4d\x00\x03")
        self.assertEqual(self.module.read_holding_registers(44109, 3), [30, 70, 65])

        process_pdu(self.module, write_multiple_pdu(44109, [30, 120, 80]))
        self.assertEqual(self.module.read_holding_registers(44109, 3), [30, 70, 65])

        process_pdu(self.module, write_multiple_pdu(44110, [60, 60]))
        self.assertEqual(self.module.read_holding_registers(44110, 2), [60, 60])

    def test_v03_and_tou_reserved_words_remain_protected(self):
        for address in (44112, 44113, 44114, 44115, 44124, 44125, 44139, 44195):
            with self.subTest(address=address):
                process_pdu(self.module, write_single_pdu(address, 0xBEEF))
                self.assertEqual(self.module.read_holding_registers(address, 1), [0])

    def test_reserve_soc_cannot_be_overridden_by_register_file(self):
        with self.assertRaisesRegex(ValueError, "profile-owned"):
            self.module._validate_register_file({"holding": {"44111": 99}})

    def test_rejected_reserve_hot_reload_keeps_baseline_and_overlay(self):
        register_file = Path(self.module.REGISTER_FILE)
        register_file.write_text(
            json.dumps({"holding": {"45000": 7}}), encoding="utf-8"
        )
        self.assertTrue(self.module.load_register_file_if_changed(startup=True))
        process_pdu(self.module, write_single_pdu(44111, 30))

        register_file.write_text(
            json.dumps({"holding": {"45000": 8, "44111": 77}}), encoding="utf-8"
        )
        self.assertTrue(self.module.load_register_file_if_changed())
        self.assertEqual(self.module.read_holding_registers(45000, 1), [7])
        self.assertEqual(self.module.read_holding_registers(44111, 1), [30])
        self.assertTrue(
            any(
                event["kind"] == "register_file_load_error"
                and event["retained_last_valid"]
                for event in self.events
            )
        )

    def test_disabled_profile_stays_zero_despite_generic_mirroring(self):
        self.new_probe(canonical_options(mirror_writes=True))
        self.assert_valid_and_initialize()
        process_pdu(self.module, write_single_pdu(44111, 30))
        process_pdu(self.module, write_single_pdu(44108, 0x0410))
        self.assertEqual(self.module.read_input_registers(34502, 3), [0, 0, 0])
        self.assertEqual(self.module.read_holding_registers(44108, 4), [0, 0, 0, 0])
        with self.assertRaisesRegex(ValueError, "profile-owned"):
            self.module._validate_register_file({"holding": {"44111": 99}})

    def test_restart_clears_v02_overlay_and_status(self):
        process_pdu(self.module, write_single_pdu(44100, 1))
        process_pdu(self.module, write_single_pdu(44108, 0x0410))
        process_pdu(self.module, write_single_pdu(44111, 30))
        self.module.initialize_profile_registers()
        self.assertEqual(self.module.read_holding_registers(44108, 4), [0, 20, 95, 40])
        self.assertEqual(self.module.read_input_registers(34502, 3), [0xAA55, 2, 0])

    def test_failsafe_clears_real_time_status_and_main_switch(self):
        registers = self.module._owners["registers"]
        with mock.patch.object(registers.time, "monotonic", return_value=1000.0):
            process_pdu(self.module, write_single_pdu(44100, 1))
            process_pdu(self.module, write_single_pdu(44105, 5))
            self.assertEqual(self.module.read_input_registers(34504, 1), [0x0502])
        with mock.patch.object(registers.time, "monotonic", return_value=1301.0):
            self.assertEqual(self.module.read_input_registers(34504, 1), [0])
        self.assertEqual(self.module.read_holding_registers(44100, 1), [0])

    def test_v02_writes_never_perform_external_io_or_change_telemetry(self):
        ha_client = self.module._owners["home_assistant"]
        before_pv = self.module.read_input_registers(33057, 2)
        before_meter = self.module.read_input_registers(33263, 2)
        with (
            mock.patch.object(ha_client, "_ha_api_json") as ha_request,
            mock.patch("urllib.request.urlopen") as urlopen,
            mock.patch("socket.socket.connect") as connect,
        ):
            process_pdu(self.module, write_single_pdu(44100, 1))
            process_pdu(
                self.module, write_multiple_pdu(44105, [2, 0, 1, 0x0410, 20, 95, 40])
            )
            process_pdu(self.module, write_single_pdu(44116, 1))
            self.assertEqual(self.module.read_input_registers(33057, 2), before_pv)
            self.assertEqual(self.module.read_input_registers(33263, 2), before_meter)
            ha_request.assert_not_called()
            urlopen.assert_not_called()
            connect.assert_not_called()

    def test_concurrent_mode_updates_keep_status_and_readback_consistent(self):
        process_pdu(self.module, write_single_pdu(44100, 1))
        process_pdu(self.module, write_single_pdu(44105, 5))
        start = threading.Event()
        failures = []

        def writer():
            start.wait()
            for index in range(500):
                process_pdu(self.module, write_single_pdu(44105, (5, 6)[index % 2]))
                if index % 20 == 0:
                    time.sleep(0)

        def reader():
            start.wait()
            for index in range(1000):
                with self.module.REG_LOCK:
                    mode = self.module.HOLDING_WRITE_OVERLAY[44105]
                    status = self.module.PROFILE_INPUT_REGISTERS[34504]
                if status != ((mode << 8) | 2):
                    failures.append((mode, status))
                    return
                if index % 20 == 0:
                    time.sleep(0)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive(), "concurrent register test hung")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
