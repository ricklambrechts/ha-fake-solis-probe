#!/usr/bin/env python3
"""Standalone Home Assistant validation and telemetry behavior tests."""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import math
import unittest

from test_support import (
    AC_GRID_PORT_ENTITY,
    BACKUP_ENTITY,
    BATTERY_POWER_ENTITY,
    BATTERY_SOC_ENTITY,
    DAILY_ENTITY,
    GRID_ENTITY,
    HOUSEHOLD_ENTITY,
    PV_ENTITY,
    SOURCE_PATH,
    TOTAL_ENTITY,
    ProbeTestCase,
    canonical_options,
    canonical_payloads,
    config_errors,
    install_ha_stubs,
    load_probe,
    set_cache,
    state_payload,
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
    payloads.update(
        {
            BATTERY_SOC_ENTITY: state_payload(
                soc,
                unit="%",
                friendly_name="Test battery state of charge",
            ),
            BATTERY_POWER_ENTITY: state_payload(
                power,
                device_class="power",
                unit="W",
                friendly_name="Test battery power",
            ),
        }
    )
    return payloads


class ValidationTests(ProbeTestCase):
    def _validation_errors(self, payloads):
        install_ha_stubs(self.module, payloads)
        with contextlib.redirect_stdout(io.StringIO()):
            valid = self.module.validate_config()
        self.assertFalse(valid)
        errors = config_errors(self.events)
        self.assertTrue(errors, "validation failure must emit actionable errors")
        return errors

    def test_canonical_configuration_validates_and_seeds_current_values(self):
        payloads = canonical_payloads()
        install_ha_stubs(self.module, payloads)

        self.assertTrue(self.module.validate_config())

        with self.module.CACHE_LOCK:
            self.assertEqual(self.module.SENSOR_CACHE[PV_ENTITY], 70000.0)
            self.assertEqual(
                self.module.LAST_KNOWN_CACHE[TOTAL_ENTITY],
                70000.9,
            )
            self.assertEqual(
                self.module.SENSOR_SAMPLE_DATE[DAILY_ENTITY],
                self.module._local_date(),
            )

    def test_every_removed_generation_option_names_its_replacement(self):
        values = {
            "ha_sensor_total_energy": "sensor.removed_total",
            "ha_sensor_daily_energy": "sensor.removed_daily",
            "total_energy_scale": 1.0,
            "daily_energy_scale": 1.0,
            "total_energy_unavailable_behavior": "last_known",
            "daily_energy_unavailable_behavior": "zero",
        }
        replacements = {
            "ha_sensor_total_energy": "ha_sensor_total_pv_generation",
            "ha_sensor_daily_energy": "ha_sensor_daily_pv_generation",
            "total_energy_scale": "total_pv_generation_scale",
            "daily_energy_scale": "daily_pv_generation_scale",
            "total_energy_unavailable_behavior": "total_pv_generation_unavailable_behavior",
            "daily_energy_unavailable_behavior": "daily_pv_generation_unavailable_behavior",
        }

        for removed, value in values.items():
            with self.subTest(option=removed):
                self.new_probe(canonical_options(**{removed: value}))
                errors = self._validation_errors(canonical_payloads())
                joined = "\n".join(errors)
                self.assertIn(f"Option '{removed}' was removed", joined)
                self.assertIn(f"'{replacements[removed]}'", joined)

    def test_negative_and_nonfinite_generation_states_fail_startup(self):
        cases = (
            (TOTAL_ENTITY, "-0.1", "ha_sensor_total_pv_generation"),
            (DAILY_ENTITY, "-0.1", "ha_sensor_daily_pv_generation"),
            (TOTAL_ENTITY, "nan", "ha_sensor_total_pv_generation"),
            (DAILY_ENTITY, "inf", "ha_sensor_daily_pv_generation"),
        )
        for entity_id, state, option in cases:
            with self.subTest(entity=entity_id, state=state):
                self.new_probe()
                payloads = canonical_payloads()
                payloads[entity_id] = state_payload(
                    state,
                    device_class="energy",
                    unit="kWh",
                    friendly_name="Test PV generation",
                )
                errors = self._validation_errors(payloads)
                self.assertTrue(
                    any(option in error for error in errors),
                    errors,
                )

    def test_generation_scales_must_be_independently_positive_and_finite(self):
        for option in (
            "total_pv_generation_scale",
            "daily_pv_generation_scale",
        ):
            for value in (0, -1, math.nan, math.inf, True):
                with self.subTest(option=option, value=value):
                    self.new_probe(canonical_options(**{option: value}))
                    errors = self._validation_errors(canonical_payloads())
                    self.assertTrue(
                        any(
                            option in error and "positive finite number" in error
                            for error in errors
                        ),
                        errors,
                    )

    def test_required_core_entities_and_unavailable_policies_are_strict(self):
        cases = (
            (
                {"ha_sensor_pv_power": ""},
                "ha_sensor_pv_power",
            ),
            (
                {"ha_sensor_grid_power": "input_number.grid"},
                "ha_sensor_grid_power",
            ),
            (
                {"pv_power_unavailable_behavior": "stale"},
                "pv_power_unavailable_behavior",
            ),
            (
                {"grid_power_sign_convention": "guess"},
                "grid_power_sign_convention",
            ),
        )
        for overrides, expected_option in cases:
            with self.subTest(overrides=overrides):
                self.new_probe(canonical_options(**overrides))
                errors = self._validation_errors(canonical_payloads())
                self.assertTrue(
                    any(expected_option in error for error in errors),
                    errors,
                )

    def test_boolean_and_log_rotation_option_types_are_strict(self):
        cases = (
            ({"enable_http": 1}, "enable_http"),
            ({"log_raw_hex": "false"}, "log_raw_hex"),
            ({"mirror_writes": 0}, "mirror_writes"),
            ({"log_max_bytes": -1}, "log_max_bytes"),
            ({"log_max_bytes": True}, "log_max_bytes"),
            ({"log_backup_count": 1.5}, "log_backup_count"),
            ({"log_backup_count": 101}, "log_backup_count"),
        )
        for overrides, expected_option in cases:
            with self.subTest(overrides=overrides):
                self.new_probe(canonical_options(**overrides))
                errors = self._validation_errors(canonical_payloads())
                self.assertTrue(
                    any(expected_option in error for error in errors),
                    errors,
                )

    def test_generation_metadata_rejects_grid_semantics_and_power_units(self):
        payloads = canonical_payloads()
        payloads[TOTAL_ENTITY] = state_payload(
            "1200",
            device_class="energy",
            unit="kWh",
            friendly_name="Net grid import energy",
        )
        errors = self._validation_errors(payloads)
        self.assertTrue(
            any("not grid flow" in error for error in errors),
            errors,
        )

        self.new_probe()
        payloads = canonical_payloads()
        payloads[DAILY_ENTITY] = state_payload(
            "12",
            device_class="energy",
            unit="W",
            friendly_name="Daily PV generation",
        )
        errors = self._validation_errors(payloads)
        self.assertTrue(
            any("energy-compatible unit" in error for error in errors),
            errors,
        )

    def test_generation_metadata_rejects_import_export_and_net_entities(self):
        cases = (
            ("sensor.energy_import", "Imported energy"),
            ("sensor.energy_export", "Exported energy"),
            ("sensor.net_energy", "Net energy"),
        )
        for entity_id, friendly_name in cases:
            with self.subTest(entity_id=entity_id):
                self.new_probe(
                    canonical_options(
                        ha_sensor_total_pv_generation=entity_id,
                    )
                )
                payloads = canonical_payloads()
                payloads.pop(TOTAL_ENTITY)
                payloads[entity_id] = state_payload(
                    "1200",
                    device_class="energy",
                    unit="kWh",
                    friendly_name=friendly_name,
                )
                errors = self._validation_errors(payloads)
                self.assertTrue(
                    any("not grid flow" in error for error in errors),
                    errors,
                )

    def test_serial_and_type_code_validation_is_strict(self):
        cases = (
            ({"fake_serial": "x" * 33}, "fake_serial"),
            ({"fake_serial": "not-ascii-\N{SNOWMAN}"}, "fake_serial"),
            ({"fake_hmi_sub_version": -1}, "fake_hmi_sub_version"),
            ({"fake_hmi_sub_version": 1.0}, "fake_hmi_sub_version"),
            ({"fake_hmi_sub_version": 65536}, "fake_hmi_sub_version"),
            ({"fake_inverter_type_code": 2030.0}, "fake_inverter_type_code"),
            ({"fake_inverter_type_code": True}, "fake_inverter_type_code"),
            ({"fake_inverter_type_code": 65536}, "fake_inverter_type_code"),
        )
        for overrides, option in cases:
            with self.subTest(overrides=overrides):
                self.new_probe(canonical_options(**overrides))
                errors = self._validation_errors(canonical_payloads())
                self.assertTrue(
                    any(option in error for error in errors),
                    errors,
                )

    def test_smart_management_requires_mirroring_and_strict_safe_defaults(self):
        cases = (
            ({"smart_management_enabled": True}, "mirror_writes"),
            (
                {
                    "smart_management_enabled": True,
                    "mirror_writes": True,
                    "smart_management_max_charge_soc": 69,
                },
                "smart_management_max_charge_soc",
            ),
            (
                {
                    "smart_management_enabled": True,
                    "mirror_writes": True,
                    "smart_management_min_soc": 41,
                },
                "smart_management_min_soc",
            ),
            (
                {
                    "smart_management_enabled": True,
                    "mirror_writes": True,
                    "smart_management_backflow_limit_w": 150,
                },
                "smart_management_backflow_limit_w",
            ),
            (
                {
                    "smart_management_enabled": True,
                    "mirror_writes": True,
                    "smart_management_peak_baseline_soc": 6,
                },
                "smart_management_peak_baseline_soc",
            ),
            (
                {
                    "smart_management_enabled": True,
                    "mirror_writes": True,
                    "smart_management_failsafe_minutes": 31,
                },
                "smart_management_failsafe_minutes",
            ),
            (
                {
                    "smart_management_enabled": True,
                    "mirror_writes": True,
                    "smart_management_meter_location": "unknown",
                },
                "smart_management_meter_location",
            ),
            (
                {
                    "smart_management_enabled": True,
                    "mirror_writes": True,
                    "smart_management_meter_type": "unknown",
                },
                "smart_management_meter_type",
            ),
        )
        for overrides, expected_option in cases:
            with self.subTest(overrides=overrides):
                self.new_probe(canonical_options(**overrides))
                errors = self._validation_errors(canonical_payloads())
                self.assertTrue(
                    any(expected_option in error for error in errors),
                    errors,
                )

    def test_transient_core_states_have_deterministic_zero_startup(self):
        payloads = canonical_payloads(
            pv="unavailable",
            grid="unknown",
            total="unavailable",
            daily="unknown",
        )
        self.assert_valid_and_initialize(payloads)

        self.assertEqual(
            self.module.read_input_registers(33029, 2),
            [0, 0],
        )
        self.assertEqual(self.module.read_input_registers(33035, 1), [0])
        self.assertEqual(
            self.module.read_input_registers(33057, 2),
            [0, 0],
        )
        self.assertEqual(
            self.module.read_input_registers(33263, 2),
            [0, 0],
        )

    def test_ha_state_sample_uses_bounded_entity_request(self):
        calls = []

        def fake_api(path, timeout):
            calls.append((path, timeout))
            return (
                True,
                state_payload(
                    "12.5",
                    device_class="power",
                    unit="W",
                ),
                "",
            )

        self.module._ha_api_json = fake_api
        value, _sample_date = self.module.ha_api_get_state_sample(PV_ENTITY)

        self.assertEqual(value, 12.5)
        self.assertEqual(
            calls,
            [
                (
                    f"states/{PV_ENTITY}",
                    self.module.HA_REQUEST_TIMEOUT_SECONDS,
                )
            ],
        )


class PollCacheTests(ProbeTestCase):
    def test_poll_deduplicates_and_failed_poll_keeps_last_known_only(self):
        calls = []
        current_date = dt.date(2026, 7, 26)
        samples = iter(((12.5, current_date), (None, None)))

        def get_sample(entity_id):
            calls.append(entity_id)
            return next(samples)

        self.module.ha_api_get_state_sample = get_sample
        self.module.update_live_registers = lambda: None

        self.module.poll_sensor_entities_once([PV_ENTITY, PV_ENTITY])
        self.assertEqual(calls, [PV_ENTITY])
        with self.module.CACHE_LOCK:
            self.assertEqual(self.module.SENSOR_CACHE[PV_ENTITY], 12.5)
            self.assertEqual(
                self.module.LAST_KNOWN_CACHE[PV_ENTITY],
                12.5,
            )
            self.assertEqual(
                self.module.SENSOR_SAMPLE_DATE[PV_ENTITY],
                current_date,
            )

        self.module.poll_sensor_entities_once([PV_ENTITY, PV_ENTITY])
        self.assertEqual(calls, [PV_ENTITY, PV_ENTITY])
        with self.module.CACHE_LOCK:
            self.assertIsNone(self.module.SENSOR_CACHE[PV_ENTITY])
            self.assertEqual(
                self.module.LAST_KNOWN_CACHE[PV_ENTITY],
                12.5,
            )
            self.assertIsNone(self.module.SENSOR_SAMPLE_DATE[PV_ENTITY])
            self.assertEqual(
                self.module.SENSOR_ERROR_COUNT[PV_ENTITY],
                1,
            )

    def test_nonfinite_api_sample_is_unavailable(self):
        self.module.ha_api_get_entity = lambda *args, **kwargs: (
            True,
            state_payload("nan", device_class="power", unit="W"),
            "",
        )
        self.assertEqual(
            self.module.ha_api_get_state_sample(PV_ENTITY),
            (None, None),
        )


class GenerationBehaviorTests(ProbeTestCase):
    def test_independent_scales_encode_only_canonical_generation_registers(self):
        self.new_probe(
            canonical_options(
                total_pv_generation_scale=0.001,
                daily_pv_generation_scale=0.001,
            )
        )
        payloads = canonical_payloads(
            total="70000900",
            daily="12390",
        )
        self.assert_valid_and_initialize(payloads)

        self.assertEqual(
            self.module.read_input_registers(33029, 2),
            [1, 4464],
        )
        self.assertEqual(self.module.read_input_registers(33035, 1), [123])
        self.assertEqual(
            self.module.read_input_registers(34391, 3),
            [0, 0, 0],
        )
        self.assertEqual(
            self.module.read_input_registers(34621, 2),
            [0, 0],
        )

    def test_total_generation_rejects_decrease_negative_nonfinite_and_range(self):
        payloads = canonical_payloads(total="100.9")
        self.assert_valid_and_initialize(payloads)
        self.assertEqual(
            self.module.read_input_registers(33029, 2),
            [0, 100],
        )

        for invalid in (
            99.9,
            -1.0,
            math.nan,
            float(self.module.U32_MAX) + 1.0,
        ):
            with self.subTest(invalid=invalid):
                set_cache(
                    self.module,
                    {TOTAL_ENTITY: invalid},
                    last_known={TOTAL_ENTITY: invalid},
                )
                self.module.update_live_registers()
                self.assertEqual(
                    self.module.read_input_registers(33029, 2),
                    [0, 100],
                )

        set_cache(
            self.module,
            {TOTAL_ENTITY: None},
            last_known={TOTAL_ENTITY: 100.9},
            error_count=1,
        )
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33029, 2),
            [0, 100],
        )

    def test_total_generation_zero_policy_zeros_only_while_unavailable(self):
        self.new_probe(
            canonical_options(
                total_pv_generation_unavailable_behavior="zero",
            )
        )
        self.assert_valid_and_initialize(canonical_payloads(total="100.9"))
        self.assertEqual(self.module.read_input_registers(33029, 2), [0, 100])

        set_cache(
            self.module,
            {TOTAL_ENTITY: None},
            last_known={TOTAL_ENTITY: 100.9},
            error_count=1,
        )
        self.module.update_live_registers()
        self.assertEqual(self.module.read_input_registers(33029, 2), [0, 0])

        set_cache(
            self.module,
            {TOTAL_ENTITY: 99.9},
            last_known={TOTAL_ENTITY: 99.9},
        )
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33029, 2),
            [0, 100],
            "a decreased sample must restore the last valid cumulative value",
        )

        set_cache(
            self.module,
            {TOTAL_ENTITY: 101.1},
            last_known={TOTAL_ENTITY: 101.1},
        )
        self.module.update_live_registers()
        self.assertEqual(self.module.read_input_registers(33029, 2), [0, 101])

    def test_daily_zero_policy_does_not_publish_stale_value(self):
        payloads = canonical_payloads(daily="12.3")
        self.assert_valid_and_initialize(payloads)
        self.assertEqual(self.module.read_input_registers(33035, 1), [123])

        for invalid in (-1.0, math.nan, 7000.0):
            with self.subTest(invalid=invalid):
                set_cache(
                    self.module,
                    {DAILY_ENTITY: invalid},
                    last_known={DAILY_ENTITY: invalid},
                )
                self.module.update_live_registers()
                self.assertEqual(
                    self.module.read_input_registers(33035, 1),
                    [123],
                )

        set_cache(
            self.module,
            {DAILY_ENTITY: None},
            last_known={DAILY_ENTITY: 12.3},
            error_count=1,
        )
        self.module.update_live_registers()

        self.assertEqual(self.module.read_input_registers(33035, 1), [0])
        self.assertEqual(
            self.module.read_input_registers(34621, 2),
            [0, 0],
        )

    def test_daily_last_known_never_crosses_ha_midnight(self):
        self.new_probe(
            canonical_options(daily_pv_generation_unavailable_behavior="last_known")
        )
        payloads = canonical_payloads(daily="12.3")
        self.assert_valid_and_initialize(payloads)
        first_date = self.module._local_date()
        self.assertIsNotNone(first_date)
        self.assertEqual(self.module.read_input_registers(33035, 1), [123])

        set_cache(
            self.module,
            {DAILY_ENTITY: 11.0},
            sample_dates={DAILY_ENTITY: first_date},
        )
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33035, 1),
            [123],
            "daily generation must not decrease within one HA date",
        )

        next_date = first_date + dt.timedelta(days=1)
        self.module._local_date = lambda: next_date
        set_cache(
            self.module,
            {DAILY_ENTITY: None},
            last_known={DAILY_ENTITY: 12.3},
            sample_dates={DAILY_ENTITY: None},
            error_count=1,
        )
        self.module.update_live_registers()
        self.assertEqual(self.module.read_input_registers(33035, 1), [0])

        set_cache(
            self.module,
            {DAILY_ENTITY: 12.3},
            sample_dates={DAILY_ENTITY: first_date},
        )
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33035, 1),
            [0],
            "a stale prior-date HA state must not repopulate the new day",
        )

        set_cache(
            self.module,
            {DAILY_ENTITY: 0.4},
            sample_dates={DAILY_ENTITY: next_date},
        )
        self.module.update_live_registers()
        self.assertEqual(self.module.read_input_registers(33035, 1), [4])

        set_cache(
            self.module,
            {DAILY_ENTITY: 12.3},
            sample_dates={DAILY_ENTITY: first_date},
        )
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33035, 1),
            [4],
            "a restored stale HA sample must remain rejected after a "
            "current-date sample was already accepted",
        )

    def test_unresolved_timezone_forces_daily_last_known_to_zero(self):
        self.new_probe(
            canonical_options(daily_pv_generation_unavailable_behavior="last_known")
        )
        payloads = canonical_payloads(daily="unavailable")
        self.assert_valid_and_initialize(
            payloads,
            timezone_name=None,
        )

        self.assertIsNone(self.module.HA_TIME_ZONE)
        self.assertEqual(
            self.module.EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR,
            "zero",
        )
        self.assertEqual(self.module.read_input_registers(33035, 1), [0])

    def test_operating_status_survives_all_sensor_fallbacks(self):
        self.assert_valid_and_initialize()
        set_cache(
            self.module,
            {
                PV_ENTITY: None,
                GRID_ENTITY: None,
                TOTAL_ENTITY: None,
                DAILY_ENTITY: None,
            },
            last_known={
                PV_ENTITY: 70000,
                GRID_ENTITY: 800,
                TOTAL_ENTITY: 70000.9,
                DAILY_ENTITY: 12.39,
            },
            error_count=2,
        )
        self.module.update_live_registers()

        self.assertEqual(self.module.read_input_registers(33121, 1), [1])


class BatteryAndHouseholdTests(ProbeTestCase):
    def _validation_errors(self, payloads):
        install_ha_stubs(self.module, payloads)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(self.module.validate_config())
        return config_errors(self.events)

    def test_no_battery_ignores_battery_options_and_never_polls_them(self):
        self.new_probe(
            canonical_options(
                battery_attached=False,
                ha_sensor_battery_soc="not-a-sensor",
                ha_sensor_battery_power="also-invalid",
                battery_soc_scale=-1,
                battery_power_scale=-1,
                battery_power_sign_convention="invalid",
            )
        )
        self.assert_valid_and_initialize()

        enabled = self.module.enabled_sensor_entity_ids()
        self.assertNotIn("not-a-sensor", enabled)
        self.assertNotIn("also-invalid", enabled)
        self.assertEqual(
            self.module.read_input_registers(33135, 1),
            [0],
        )
        self.assertEqual(
            self.module.read_input_registers(33139, 1),
            [0],
        )
        self.assertEqual(
            self.module.read_input_registers(33149, 2),
            [0, 0],
        )
        self.assertEqual(self.module.read_input_registers(33121, 1), [1])

    def test_battery_mode_requires_both_entities(self):
        cases = (
            ("ha_sensor_battery_soc", ""),
            ("ha_sensor_battery_power", ""),
        )
        for missing, value in cases:
            with self.subTest(missing=missing):
                options = battery_options(**{missing: value})
                self.new_probe(options)
                errors = self._validation_errors(battery_payloads())
                self.assertTrue(
                    any(missing in error for error in errors),
                    errors,
                )

    def test_battery_state_and_power_validation(self):
        cases = (
            (
                "soc-range",
                battery_payloads(soc="101"),
                "ha_sensor_battery_soc",
            ),
            (
                "soc-nonnumeric",
                battery_payloads(soc="full"),
                "ha_sensor_battery_soc",
            ),
            (
                "power-range",
                battery_payloads(power=str(1 << 31)),
                "ha_sensor_battery_power",
            ),
        )
        for name, payloads, expected_option in cases:
            with self.subTest(case=name):
                self.new_probe(battery_options())
                errors = self._validation_errors(payloads)
                self.assertTrue(
                    any(expected_option in error for error in errors),
                    errors,
                )

    def test_battery_domain_existence_scale_sign_and_metadata_validation(self):
        cases = []

        options = battery_options(ha_sensor_battery_soc="input_number.battery_soc")
        cases.append(("domain", options, battery_payloads(), "battery_soc"))

        options = battery_options(
            ha_sensor_battery_power="sensor.missing_battery_power"
        )
        cases.append(("missing", options, battery_payloads(), "battery_power"))

        options = battery_options(battery_soc_scale=0)
        cases.append(("soc-scale", options, battery_payloads(), "battery_soc_scale"))

        options = battery_options(battery_power_scale=math.inf)
        cases.append(
            ("power-scale", options, battery_payloads(), "battery_power_scale")
        )

        options = battery_options(battery_power_sign_convention="unsigned")
        cases.append(
            (
                "sign",
                options,
                battery_payloads(),
                "battery_power_sign_convention",
            )
        )

        payloads = battery_payloads()
        payloads[BATTERY_POWER_ENTITY] = state_payload(
            "2500",
            device_class="energy",
            unit="kWh",
        )
        cases.append(
            (
                "metadata",
                battery_options(),
                payloads,
                "ha_sensor_battery_power",
            )
        )

        for name, options, payloads, expected_option in cases:
            with self.subTest(case=name):
                self.new_probe(options)
                errors = self._validation_errors(payloads)
                self.assertTrue(
                    any(expected_option in error for error in errors),
                    errors,
                )

    def test_battery_transient_startup_is_deterministic_zero(self):
        self.new_probe(battery_options())
        payloads = battery_payloads(
            soc="unavailable",
            power="unknown",
        )
        self.assert_valid_and_initialize(payloads)

        self.assertEqual(self.module.read_input_registers(33135, 1), [0])
        self.assertEqual(self.module.read_input_registers(33139, 1), [0])
        self.assertEqual(
            self.module.read_input_registers(33149, 2),
            [0, 0],
        )

    def test_battery_soc_boundaries_and_both_power_sign_conventions(self):
        self.new_probe(battery_options())
        self.assert_valid_and_initialize(battery_payloads())

        for soc in (0.0, 64.9, 100.0):
            with self.subTest(soc=soc):
                set_cache(self.module, {BATTERY_SOC_ENTITY: soc})
                self.module.update_live_registers()
                self.assertEqual(
                    self.module.read_input_registers(33139, 1),
                    [math.floor(soc)],
                )

        cases = (
            ("discharge_positive", 2500.0, 1, 2500),
            ("discharge_positive", -2400.0, 0, 2400),
            ("charge_positive", 2300.0, 0, 2300),
            ("charge_positive", -2200.0, 1, 2200),
            ("discharge_positive", 0.0, 0, 0),
        )
        for convention, power, direction, magnitude in cases:
            with self.subTest(convention=convention, power=power):
                self.module.OPTIONS["battery_power_sign_convention"] = convention
                set_cache(
                    self.module,
                    {BATTERY_POWER_ENTITY: power},
                )
                self.module.update_live_registers()
                self.assertEqual(
                    self.module.read_input_registers(33135, 1),
                    [direction],
                )
                self.assertEqual(
                    self.module.read_input_registers(33149, 2),
                    list(self.module._to_s32_pair(magnitude)),
                )

    def test_battery_scales_apply_before_soc_range_and_power_direction(self):
        self.new_probe(
            battery_options(
                battery_soc_scale=2.0,
                battery_power_scale=2.0,
                battery_power_sign_convention="discharge_positive",
            )
        )
        self.assert_valid_and_initialize(battery_payloads(soc="32", power="-1250"))

        self.assertEqual(self.module.read_input_registers(33139, 1), [64])
        self.assertEqual(self.module.read_input_registers(33135, 1), [0])
        self.assertEqual(
            self.module.read_input_registers(33149, 2),
            [0, 2500],
        )

    def test_unavailable_battery_power_is_idle_and_soc_retains_last_known(self):
        self.new_probe(battery_options())
        self.assert_valid_and_initialize(battery_payloads(soc="64", power="2500"))

        set_cache(
            self.module,
            {
                BATTERY_SOC_ENTITY: None,
                BATTERY_POWER_ENTITY: None,
            },
            last_known={
                BATTERY_SOC_ENTITY: 64.0,
                BATTERY_POWER_ENTITY: 2500.0,
            },
            error_count=1,
        )
        self.module.update_live_registers()

        self.assertEqual(self.module.read_input_registers(33139, 1), [64])
        self.assertEqual(self.module.read_input_registers(33135, 1), [0])
        self.assertEqual(
            self.module.read_input_registers(33149, 2),
            [0, 0],
        )

    def test_household_load_is_independent_of_battery_mode(self):
        self.new_probe(
            canonical_options(
                battery_attached=False,
                ha_sensor_household_load_power=HOUSEHOLD_ENTITY,
                household_load_power_scale=1.5,
            )
        )
        payloads = canonical_payloads()
        payloads[HOUSEHOLD_ENTITY] = state_payload(
            "1000.9",
            device_class="power",
            unit="W",
            friendly_name="Test household load",
        )
        self.assert_valid_and_initialize(payloads)

        self.assertIn(
            HOUSEHOLD_ENTITY,
            self.module.enabled_sensor_entity_ids(),
        )
        self.assertNotIn(
            BATTERY_POWER_ENTITY,
            self.module.enabled_sensor_entity_ids(),
        )
        self.assertEqual(
            self.module.read_input_registers(33147, 1),
            [1501],
        )

        set_cache(
            self.module,
            {HOUSEHOLD_ENTITY: None},
            last_known={HOUSEHOLD_ENTITY: 1000.9},
            error_count=1,
        )
        self.module.update_live_registers()
        self.assertEqual(
            self.module.read_input_registers(33147, 1),
            [0],
        )

    def test_household_load_range_is_validated(self):
        self.new_probe(
            canonical_options(
                ha_sensor_household_load_power=HOUSEHOLD_ENTITY,
            )
        )
        payloads = canonical_payloads()
        payloads[HOUSEHOLD_ENTITY] = state_payload(
            "65536",
            device_class="power",
            unit="W",
        )
        errors = self._validation_errors(payloads)
        self.assertTrue(
            any("ha_sensor_household_load_power" in error for error in errors),
            errors,
        )

    def test_backup_and_ac_grid_port_metrics_validate_independently(self):
        options = canonical_options(
            battery_attached=False,
            ha_sensor_backup_load_power=BACKUP_ENTITY,
            ha_sensor_ac_grid_port_power=AC_GRID_PORT_ENTITY,
        )
        payloads = canonical_payloads()
        payloads[BACKUP_ENTITY] = state_payload(
            "1200",
            device_class="power",
            unit="W",
        )
        payloads[AC_GRID_PORT_ENTITY] = state_payload(
            "-800",
            device_class="power",
            unit="W",
        )
        self.new_probe(options)
        self.assert_valid_and_initialize(payloads)
        enabled = self.module.enabled_sensor_entity_ids()
        self.assertIn(BACKUP_ENTITY, enabled)
        self.assertIn(AC_GRID_PORT_ENTITY, enabled)

        cases = (
            (
                {"ha_sensor_backup_load_power": BACKUP_ENTITY},
                BACKUP_ENTITY,
                state_payload("65536", device_class="power", unit="W"),
                "ha_sensor_backup_load_power",
            ),
            (
                {"ha_sensor_backup_load_power": BACKUP_ENTITY},
                BACKUP_ENTITY,
                state_payload("100", device_class="energy", unit="kWh"),
                "ha_sensor_backup_load_power",
            ),
            (
                {
                    "ha_sensor_ac_grid_port_power": AC_GRID_PORT_ENTITY,
                    "ac_grid_port_power_sign_convention": "guess",
                },
                AC_GRID_PORT_ENTITY,
                state_payload("100", device_class="power", unit="W"),
                "ac_grid_port_power_sign_convention",
            ),
            (
                {
                    "ha_sensor_ac_grid_port_power": AC_GRID_PORT_ENTITY,
                    "ac_grid_port_power_scale": 0,
                },
                AC_GRID_PORT_ENTITY,
                state_payload("100", device_class="power", unit="W"),
                "ac_grid_port_power_scale",
            ),
        )
        for overrides, entity_id, payload, expected_option in cases:
            with self.subTest(expected_option=expected_option):
                self.new_probe(canonical_options(**overrides))
                test_payloads = canonical_payloads()
                test_payloads[entity_id] = payload
                errors = self._validation_errors(test_payloads)
                self.assertTrue(
                    any(expected_option in error for error in errors),
                    errors,
                )

    def test_backup_and_ac_grid_port_unavailable_policies_are_independent(self):
        self.new_probe(
            canonical_options(
                ha_sensor_backup_load_power=BACKUP_ENTITY,
                backup_load_power_unavailable_behavior="last_known",
                ha_sensor_ac_grid_port_power=AC_GRID_PORT_ENTITY,
                ac_grid_port_power_unavailable_behavior="zero",
            )
        )
        payloads = canonical_payloads()
        payloads[BACKUP_ENTITY] = state_payload(
            "1200",
            device_class="power",
            unit="W",
        )
        payloads[AC_GRID_PORT_ENTITY] = state_payload(
            "-800",
            device_class="power",
            unit="W",
        )
        self.assert_valid_and_initialize(payloads)

        set_cache(
            self.module,
            {
                BACKUP_ENTITY: None,
                AC_GRID_PORT_ENTITY: None,
            },
            last_known={
                BACKUP_ENTITY: 1200,
                AC_GRID_PORT_ENTITY: -800,
            },
            error_count=1,
        )
        self.module.update_live_registers()

        self.assertEqual(self.module.read_input_registers(33148, 1), [1200])
        self.assertEqual(self.module.read_input_registers(33151, 2), [0, 0])

        self.new_probe(
            canonical_options(
                ha_sensor_household_load_power=HOUSEHOLD_ENTITY,
            )
        )
        payloads = canonical_payloads()
        payloads[HOUSEHOLD_ENTITY] = state_payload(
            "1000",
            device_class="energy",
            unit="kWh",
        )
        errors = self._validation_errors(payloads)
        self.assertTrue(
            any("ha_sensor_household_load_power" in error for error in errors),
            errors,
        )


class PackageBoundaryTests(unittest.TestCase):
    def test_fresh_loads_have_independent_state_and_locks(self):
        first, _events = load_probe(canonical_options(fake_serial="FIRST-RUNTIME"))
        first.OPTIONS["mirror_writes"] = True
        with first.CACHE_LOCK:
            first.SENSOR_CACHE[PV_ENTITY] = 123.0
        with first.REG_LOCK:
            first.HOLDING_WRITE_OVERLAY[43010] = 42

        second, _events = load_probe(canonical_options(fake_serial="SECOND-RUNTIME"))

        self.assertEqual(first.OPTIONS["fake_serial"], "FIRST-RUNTIME")
        self.assertEqual(second.OPTIONS["fake_serial"], "SECOND-RUNTIME")
        self.assertFalse(second.OPTIONS["mirror_writes"])
        self.assertNotIn(PV_ENTITY, second.SENSOR_CACHE)
        self.assertNotIn(43010, second.HOLDING_WRITE_OVERLAY)
        self.assertIsNot(first.CACHE_LOCK, second.CACHE_LOCK)
        self.assertIsNot(first.REG_LOCK, second.REG_LOCK)

    def test_thin_launcher_imports_package_main(self):
        load_probe()
        spec = importlib.util.spec_from_file_location(
            "fake_solis_probe_launcher_test",
            SOURCE_PATH,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)

        self.assertEqual(launcher.main.__module__, "solis_probe.app")


if __name__ == "__main__":
    unittest.main(verbosity=2)
