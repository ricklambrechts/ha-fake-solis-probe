"""AC telemetry in the Tibber-observed FC4 33070/26 input block."""

from __future__ import annotations

import pytest
from test_support import (
    ProbeTestCase,
    canonical_options,
    canonical_payloads,
    config_errors,
    install_ha_stubs,
    process_pdu,
    read_request_pdu,
    response_words,
    set_cache,
    state_payload,
)


VOLTAGE_ENTITIES = (
    "sensor.test_inverter_ac_voltage_a",
    "sensor.test_inverter_ac_voltage_b",
    "sensor.test_inverter_ac_voltage_c",
)
CURRENT_ENTITIES = (
    "sensor.test_inverter_ac_current_a",
    "sensor.test_inverter_ac_current_b",
    "sensor.test_inverter_ac_current_c",
)
AC_POWER_ENTITY = "sensor.test_inverter_ac_power"


def ac_options(**overrides):
    options = canonical_options(
        ha_sensor_inverter_ac_voltage_a=VOLTAGE_ENTITIES[0],
        ha_sensor_inverter_ac_voltage_b=VOLTAGE_ENTITIES[1],
        ha_sensor_inverter_ac_voltage_c=VOLTAGE_ENTITIES[2],
        ha_sensor_inverter_ac_current_a=CURRENT_ENTITIES[0],
        ha_sensor_inverter_ac_current_b=CURRENT_ENTITIES[1],
        ha_sensor_inverter_ac_current_c=CURRENT_ENTITIES[2],
        ha_sensor_inverter_ac_power=AC_POWER_ENTITY,
    )
    options.update(overrides)
    return options


def ac_payloads(*, power="-35000"):
    payloads = canonical_payloads(pv="0")
    payloads.update(
        {
            entity: state_payload(value, device_class="voltage", unit="V")
            for entity, value in zip(VOLTAGE_ENTITIES, ("115", "116", "117"))
        }
    )
    payloads.update(
        {
            entity: state_payload(value, device_class="current", unit="A")
            for entity, value in zip(CURRENT_ENTITIES, ("2", "3", "4"))
        }
    )
    payloads[AC_POWER_ENTITY] = state_payload(power, device_class="power", unit="W")
    return payloads


class AcTelemetryTests(ProbeTestCase):
    def test_unconfigured_ac_block_has_only_fake_a_voltage(self):
        self.assert_valid_and_initialize()

        response = process_pdu(self.module, read_request_pdu(4, 33070, 26))
        words = response_words(response, 4)

        assert len(words) == 26
        assert words == [0, 0, 0, 2300] + [0] * 22
        assert self.module.read_input_registers(33057, 2) == [1, 4464]
        assert self.module.read_input_registers(33079, 2) == [0, 0]

    def test_synthetic_voltage_channels_follow_fake_inverter_phase_count(self):
        cases = (
            (2030, [2300, 0, 0]),
            (2040, [2300, 0, 0]),
            (2050, [2300, 2300, 2300]),
            (2060, [2300, 2300, 2300]),
            (12345, [2300, 0, 0]),
        )
        for type_code, expected in cases:
            with self.subTest(type_code=type_code):
                self.new_probe(canonical_options(fake_inverter_type_code=type_code))
                self.assert_valid_and_initialize(update=False)

                assert self.module.read_input_registers(33073, 3) == expected
                self.module.update_live_registers()
                response = process_pdu(self.module, read_request_pdu(4, 33070, 26))
                assert response_words(response, 4)[3:6] == expected

    def test_three_phase_synthetic_voltage_yields_to_configured_phase(self):
        self.new_probe(
            canonical_options(
                fake_inverter_type_code=2050,
                ha_sensor_inverter_ac_voltage_b=VOLTAGE_ENTITIES[1],
            )
        )
        payloads = canonical_payloads()
        payloads[VOLTAGE_ENTITIES[1]] = state_payload(
            "225", device_class="voltage", unit="V"
        )
        self.assert_valid_and_initialize(payloads)
        assert self.module.read_input_registers(33073, 3) == [2300, 2250, 2300]

        set_cache(self.module, {VOLTAGE_ENTITIES[1]: None}, error_count=1)
        self.module.update_live_registers()
        assert self.module.read_input_registers(33073, 3) == [2300, 0, 2300]

    def test_one_phase_keeps_explicit_b_voltage_source(self):
        self.new_probe(
            canonical_options(
                fake_inverter_type_code=2030,
                ha_sensor_inverter_ac_voltage_b=VOLTAGE_ENTITIES[1],
            )
        )
        payloads = canonical_payloads()
        payloads[VOLTAGE_ENTITIES[1]] = state_payload(
            "222", device_class="voltage", unit="V"
        )
        self.assert_valid_and_initialize(payloads)
        assert self.module.read_input_registers(33073, 3) == [2300, 2220, 0]

    def test_independent_phase_sources_and_negative_ac_power_use_canonical_words(self):
        self.new_probe(
            ac_options(
                inverter_ac_voltage_scale=2.0,
                inverter_ac_current_scale=2.0,
                inverter_ac_power_scale=2.0,
                inverter_ac_power_sign_convention="direct",
            )
        )
        self.assert_valid_and_initialize(ac_payloads())

        assert set(self.module.enabled_sensor_entity_ids()) >= {
            *VOLTAGE_ENTITIES,
            *CURRENT_ENTITIES,
            AC_POWER_ENTITY,
        }
        assert self.module.read_input_registers(33073, 8) == [
            2300,
            2320,
            2340,
            40,
            60,
            80,
            0xFFFE,
            0xEE90,
        ]
        assert self.module.read_input_registers(33057, 2) == [0, 0]
        assert self.module.read_input_registers(33263, 2) == [0xFFFF, 0xFCE0]

        self.module.OPTIONS["inverter_ac_power_sign_convention"] = "negate"
        self.module.update_live_registers()
        assert self.module.read_input_registers(33079, 2) == [1, 4464]

    def test_configured_voltage_outage_uses_policy_without_fake_230v(self):
        payloads = canonical_payloads()
        payloads[VOLTAGE_ENTITIES[0]] = state_payload(
            "232", device_class="voltage", unit="V"
        )
        for behavior, expected in (("zero", 0), ("last_known", 2320)):
            with self.subTest(behavior=behavior):
                self.new_probe(
                    canonical_options(
                        ha_sensor_inverter_ac_voltage_a=VOLTAGE_ENTITIES[0],
                        inverter_ac_voltage_unavailable_behavior=behavior,
                    )
                )
                self.assert_valid_and_initialize(payloads)
                assert self.module.read_input_registers(33073, 1) == [2320]

                set_cache(
                    self.module,
                    {VOLTAGE_ENTITIES[0]: None},
                    last_known={VOLTAGE_ENTITIES[0]: 232.0},
                    error_count=1,
                )
                self.module.update_live_registers()
                assert self.module.read_input_registers(33073, 1) == [expected]

    def test_current_and_ac_power_outages_use_their_own_policies(self):
        payloads = canonical_payloads(pv="0")
        payloads[CURRENT_ENTITIES[1]] = state_payload(
            "4", device_class="current", unit="A"
        )
        payloads[AC_POWER_ENTITY] = state_payload(
            "70000", device_class="power", unit="W"
        )
        for behavior, expected in (
            ("zero", [0, 0]),
            ("last_known", [1, 4464]),
        ):
            with self.subTest(power_behavior=behavior):
                self.new_probe(
                    canonical_options(
                        ha_sensor_inverter_ac_current_b=CURRENT_ENTITIES[1],
                        inverter_ac_current_unavailable_behavior="last_known",
                        ha_sensor_inverter_ac_power=AC_POWER_ENTITY,
                        inverter_ac_power_unavailable_behavior=behavior,
                    )
                )
                self.assert_valid_and_initialize(payloads)

                set_cache(
                    self.module,
                    {CURRENT_ENTITIES[1]: None, AC_POWER_ENTITY: None},
                    last_known={CURRENT_ENTITIES[1]: 4.0, AC_POWER_ENTITY: 70000.0},
                    error_count=1,
                )
                self.module.update_live_registers()
                assert self.module.read_input_registers(33077, 1) == [40]
                assert self.module.read_input_registers(33079, 2) == expected

    def test_ac_inputs_are_profile_owned_and_reject_file_baselines(self):
        self.assert_valid_and_initialize()
        for address in range(33073, 33081):
            with self.subTest(address=address):
                with pytest.raises(ValueError):
                    self.module._validate_register_file(
                        {"input": {str(address): 0xBEEF}}
                    )

                with self.module.REG_LOCK:
                    self.module.INPUT_REGISTER_BASELINE[address] = 0xBEEF
                expected = 2300 if address == 33073 else 0
                assert self.module.read_input_registers(address, 1) == [expected]

    def test_invalid_ac_options_are_rejected(self):
        cases = (
            ({"inverter_ac_voltage_scale": 0}, "inverter_ac_voltage_scale"),
            ({"inverter_ac_current_scale": -1}, "inverter_ac_current_scale"),
            ({"inverter_ac_power_scale": 0}, "inverter_ac_power_scale"),
            (
                {"inverter_ac_voltage_unavailable_behavior": "stale"},
                "inverter_ac_voltage_unavailable_behavior",
            ),
            (
                {"inverter_ac_current_unavailable_behavior": "stale"},
                "inverter_ac_current_unavailable_behavior",
            ),
            (
                {"inverter_ac_power_unavailable_behavior": "stale"},
                "inverter_ac_power_unavailable_behavior",
            ),
            (
                {"inverter_ac_power_sign_convention": "guess"},
                "inverter_ac_power_sign_convention",
            ),
        )
        for overrides, invalid_option in cases:
            with self.subTest(option=invalid_option):
                self.new_probe(canonical_options(**overrides))
                install_ha_stubs(self.module, canonical_payloads())
                assert not self.module.validate_config()
                assert any(
                    invalid_option in error for error in config_errors(self.events)
                )

    def test_configured_ac_states_are_range_and_metadata_checked(self):
        self.new_probe(ac_options())
        payloads = ac_payloads()
        payloads[VOLTAGE_ENTITIES[0]] = state_payload(
            "10", device_class="power", unit="W"
        )
        payloads[CURRENT_ENTITIES[1]] = state_payload(
            "6553.6", device_class="current", unit="A"
        )
        payloads[AC_POWER_ENTITY] = state_payload(
            "2147483648", device_class="power", unit="W"
        )
        install_ha_stubs(self.module, payloads)
        assert not self.module.validate_config()
        errors = config_errors(self.events)
        for option in (
            "ha_sensor_inverter_ac_voltage_a",
            "ha_sensor_inverter_ac_current_b",
            "ha_sensor_inverter_ac_power",
        ):
            assert any(option in error for error in errors)

    def test_extreme_finite_ac_measurements_are_rejected_without_crashing(self):
        for measurement, entity, device_class, address in (
            ("voltage", VOLTAGE_ENTITIES[0], "voltage", 33073),
            ("current", CURRENT_ENTITIES[0], "current", 33076),
        ):
            with self.subTest(measurement=measurement):
                option = f"ha_sensor_inverter_ac_{measurement}_a"
                self.new_probe(canonical_options(**{option: entity}))
                payloads = canonical_payloads()
                payloads[entity] = state_payload("1e308", device_class=device_class)
                install_ha_stubs(self.module, payloads)
                assert not self.module.validate_config()
                assert any(option in error for error in config_errors(self.events))

                payloads[entity] = state_payload("230", device_class=device_class)
                self.assert_valid_and_initialize(payloads)
                set_cache(self.module, {entity: 1e308})
                self.module.update_live_registers()
                assert self.module.read_input_registers(address, 1) == [0]
