"""Shared dependency-free helpers for Fake Solis Probe regression tests."""

from __future__ import annotations

import builtins
import datetime as dt
import importlib
import io
import json
import os
import struct
import sys
import tempfile
import types
import unittest
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

TEST_DIR = Path(__file__).resolve().parent
APP_DIR = TEST_DIR.parent
SOURCE_PATH = APP_DIR / "fake_solis_probe.py"
PACKAGE_NAME = "solis_probe"
OWNER_MODULE_NAMES = (
    "config",
    "sensor_cache",
    "event_log",
    "home_assistant",
    "validation",
    "registers",
    "telemetry",
    "polling",
    "modbus",
    "http_probe",
    "app",
)

# The production split intentionally gives internal helpers public,
# module-local names. Keep the regression tests focused on behavior by routing
# their historical monolith spellings to the new owners.
FACADE_ALIASES = {
    "_safe_option_summary": ("config", "safe_option_summary"),
    "_rotate_log_if_needed": ("event_log", "rotate_log_if_needed"),
    "_private_ref": ("event_log", "private_ref"),
    "_resolve_ha_timezone": ("home_assistant", "resolve_ha_timezone"),
    "_local_date": ("home_assistant", "local_date"),
    "_payload_local_date": ("home_assistant", "payload_local_date"),
    "_require_int": ("registers", "_require_int"),
    "_to_u16_word": ("registers", "to_u16_word"),
    "_to_s16_word": ("registers", "to_s16_word"),
    "_to_u32_pair": ("registers", "to_u32_pair"),
    "_to_s32_pair": ("registers", "to_s32_pair"),
    "_encode_serial_words": ("registers", "encode_serial_words"),
    "_validate_register_file": ("registers", "validate_register_file"),
    "_validate_range": ("registers", "_validate_range"),
}

# Assignment routing cannot rely on a broad attribute scan for names such as
# ``os`` that appear in several modules. These are the stateful seams patched
# directly by the standalone tests.
FACADE_OWNERS = {
    "OPTIONS": "config",
    "RAW_OPTIONS": "config",
    "OPTIONS_LOAD_ERROR": "config",
    "SENSOR_CACHE": "sensor_cache",
    "LAST_KNOWN_CACHE": "sensor_cache",
    "SENSOR_SAMPLE_DATE": "sensor_cache",
    "SENSOR_ERROR_COUNT": "sensor_cache",
    "CACHE_LOCK": "sensor_cache",
    "EVENT_DIR": "event_log",
    "EVENT_LOG": "event_log",
    "LOG_LOCK": "event_log",
    "log_event": "event_log",
    "HA_TIME_ZONE": "home_assistant",
    "HA_TIME_ZONE_NAME": "home_assistant",
    "EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR": "home_assistant",
    "_ha_api_json": "home_assistant",
    "ha_api_get_entity": "home_assistant",
    "ha_api_get_timezone_name": "home_assistant",
    "ha_api_get_state_sample": "home_assistant",
    "ha_api_get_state": "home_assistant",
    "validate_config": "validation",
    "REGISTER_FILE": "registers",
    "REG_LOCK": "registers",
    "REGISTER_RELOAD_LOCK": "registers",
    "PROFILE_INPUT_REGISTERS": "registers",
    "PROFILE_HOLDING_REGISTERS": "registers",
    "INPUT_REGISTER_BASELINE": "registers",
    "HOLDING_REGISTER_BASELINE": "registers",
    "HOLDING_WRITE_OVERLAY": "registers",
    "REGISTER_FILE_FINGERPRINT": "registers",
    "REGISTER_FILE_REJECTED_FINGERPRINT": "registers",
    "TOTAL_PV_GENERATION_LAST_KWH": "registers",
    "DAILY_PV_GENERATION_LAST_KWH": "registers",
    "DAILY_PV_GENERATION_DATE": "registers",
    "DAILY_REQUIRES_CURRENT_DATE_SAMPLE": "registers",
    "REMOTE_DISPATCH_LAST_WRITE_MONOTONIC": "registers",
    "initialize_profile_registers": "registers",
    "load_register_file_if_changed": "registers",
    "read_input_registers": "registers",
    "read_holding_registers": "registers",
    "write_holding_registers": "registers",
    "FALLBACK_LOG_COUNT": "telemetry",
    "VALIDATION_LOG_COUNT": "telemetry",
    "update_live_registers": "telemetry",
    "enabled_sensor_keys": "telemetry",
    "enabled_sensor_entity_ids": "telemetry",
    "poll_sensor_entities_once": "polling",
    "sensor_poll_loop": "polling",
    "POLL_LOOP_ERROR_COUNT": "polling",
    "ModbusHandler": "modbus",
    "ThreadedTCPServer": "app",
    "exception_pdu": "modbus",
    "device_id_objects": "modbus",
    "ProbeHTTPHandler": "http_probe",
    "serve_http": "app",
    "serve_modbus": "app",
    "main": "app",
    "os": "app",
}

PV_ENTITY = "sensor.test_pv_power"
GRID_ENTITY = "sensor.test_grid_power"
TOTAL_ENTITY = "sensor.test_total_pv_generation"
DAILY_ENTITY = "sensor.test_daily_pv_generation"
BATTERY_SOC_ENTITY = "sensor.test_battery_soc"
BATTERY_POWER_ENTITY = "sensor.test_battery_power"
HOUSEHOLD_ENTITY = "sensor.test_household_load_power"
BACKUP_ENTITY = "sensor.test_backup_load_power"
AC_GRID_PORT_ENTITY = "sensor.test_ac_grid_port_power"


class ProbeModuleFacade(types.ModuleType):
    """Route the former monolith namespace to freshly imported owner modules."""

    def __init__(self, owners: Mapping[str, types.ModuleType]) -> None:
        super().__init__("fake_solis_probe_test_facade")
        super().__setattr__("_owners", dict(owners))
        super().__setattr__("__file__", str(SOURCE_PATH))

    def _target(self, name: str) -> tuple[types.ModuleType, str] | None:
        alias = FACADE_ALIASES.get(name)
        if alias is not None:
            owner_name, attribute = alias
            owner = self._owners[owner_name]
            if hasattr(owner, attribute):
                return owner, attribute

        owner_name = FACADE_OWNERS.get(name)
        if owner_name is not None:
            owner = self._owners[owner_name]
            if hasattr(owner, name):
                return owner, name

        candidates = [owner for owner in self._owners.values() if hasattr(owner, name)]
        if len(candidates) == 1:
            return candidates[0], name
        if len(candidates) > 1 and owner_name is not None:
            return self._owners[owner_name], name
        return None

    def __getattr__(self, name: str) -> Any:
        target = self._target(name)
        if target is None:
            raise AttributeError(
                f"{type(self).__name__!s} has no routed attribute {name!r}"
            )
        owner, attribute = target
        return getattr(owner, attribute)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("__") or name in {"_owners", "_test_events"}:
            super().__setattr__(name, value)
            return
        target = self._target(name)
        if target is None:
            super().__setattr__(name, value)
            return
        owner, attribute = target
        setattr(owner, attribute, value)

    def __dir__(self) -> list[str]:
        routed = set(super().__dir__())
        routed.update(FACADE_ALIASES)
        routed.update(FACADE_OWNERS)
        for owner in self._owners.values():
            routed.update(vars(owner))
        return sorted(routed)


def _fresh_owner_modules() -> dict[str, types.ModuleType]:
    """Import one isolated copy of every production owner module."""
    app_path = str(APP_DIR)
    if app_path not in sys.path:
        sys.path.insert(0, app_path)

    for module_name in tuple(sys.modules):
        if module_name == PACKAGE_NAME or module_name.startswith(f"{PACKAGE_NAME}."):
            del sys.modules[module_name]
    importlib.invalidate_caches()

    return {
        owner_name: importlib.import_module(f"{PACKAGE_NAME}.{owner_name}")
        for owner_name in OWNER_MODULE_NAMES
    }


def canonical_options(**overrides: Any) -> dict[str, Any]:
    """Return raw app options containing only current, canonical option keys."""
    options: dict[str, Any] = {
        "ha_sensor_pv_power": PV_ENTITY,
        "ha_sensor_grid_power": GRID_ENTITY,
        "ha_sensor_total_pv_generation": TOTAL_ENTITY,
        "ha_sensor_daily_pv_generation": DAILY_ENTITY,
        "fake_serial": "TEST-SERIAL-0001",
        "fake_inverter_type_code": 2030,
    }
    options.update(overrides)
    return options


def state_payload(
    state: Any,
    *,
    device_class: str | None = None,
    unit: str | None = None,
    friendly_name: str | None = None,
    last_updated: str | None = "current",
) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    if device_class is not None:
        attributes["device_class"] = device_class
    if unit is not None:
        attributes["unit_of_measurement"] = unit
    if friendly_name is not None:
        attributes["friendly_name"] = friendly_name
    payload: dict[str, Any] = {"state": state, "attributes": attributes}
    if last_updated == "current":
        payload["last_updated"] = dt.datetime.now(dt.UTC).isoformat()
    elif last_updated is not None:
        payload["last_updated"] = last_updated
    return payload


def canonical_payloads(
    *,
    pv: Any = "70000",
    grid: Any = "800",
    total: Any = "70000.9",
    daily: Any = "12.39",
) -> dict[str, dict[str, Any]]:
    return {
        PV_ENTITY: state_payload(
            pv,
            device_class="power",
            unit="W",
            friendly_name="Test PV power",
        ),
        GRID_ENTITY: state_payload(
            grid,
            device_class="power",
            unit="W",
            friendly_name="Test grid power",
        ),
        TOTAL_ENTITY: state_payload(
            total,
            device_class="energy",
            unit="kWh",
            friendly_name="Test total PV generation",
        ),
        DAILY_ENTITY: state_payload(
            daily,
            device_class="energy",
            unit="kWh",
            friendly_name="Test daily PV generation",
        ),
    }


def load_probe(
    options: Mapping[str, Any] | None = None,
    *,
    options_text: str | None = None,
) -> tuple[types.ModuleType, list[dict[str, Any]]]:
    """Import the package afresh with deterministic raw App options."""
    if options_text is None:
        raw_options = canonical_options() if options is None else dict(options)
        options_text = json.dumps(raw_options)

    real_open = builtins.open

    def patched_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if os.fspath(file) == "/data/options.json":
            return io.StringIO(options_text)
        return real_open(file, *args, **kwargs)

    events: list[dict[str, Any]] = []

    with mock.patch("builtins.open", patched_open):
        module = ProbeModuleFacade(_fresh_owner_modules())

    def capture_event(kind: str, **data: Any) -> None:
        events.append({"kind": kind, **data})

    module.log_event = capture_event
    module._test_events = events
    return module, events


def install_ha_stubs(
    module: types.ModuleType,
    payloads: Mapping[str, dict[str, Any]],
    *,
    timezone_name: str | None = "Europe/Amsterdam",
    timezone_error: str = "timezone unavailable",
) -> None:
    payload_map = dict(payloads)

    def get_entity(
        entity_id: str,
        timeout: float = 10.0,
    ) -> tuple[bool, dict[str, Any] | None, str]:
        del timeout
        payload = payload_map.get(entity_id)
        if payload is None:
            return False, None, "not found (HTTP 404)"
        return True, dict(payload), ""

    module.ha_api_get_entity = get_entity
    if timezone_name is None:
        module.ha_api_get_timezone_name = lambda: (False, None, timezone_error)
    else:
        module.ha_api_get_timezone_name = lambda: (True, timezone_name, "")


def validate_and_initialize(
    module: types.ModuleType,
    payloads: Mapping[str, dict[str, Any]],
    *,
    timezone_name: str | None = "Europe/Amsterdam",
    update: bool = True,
) -> None:
    install_ha_stubs(
        module,
        payloads,
        timezone_name=timezone_name,
    )
    if not module.validate_config():
        errors = [
            event.get("errors")
            for event in module._test_events
            if event.get("kind") == "config_validation_failed"
        ]
        raise AssertionError(f"expected valid configuration, got {errors!r}")
    module.initialize_profile_registers()
    if update:
        module.update_live_registers()


def set_cache(
    module: types.ModuleType,
    current: Mapping[str, float | None],
    *,
    last_known: Mapping[str, float | None] | None = None,
    sample_dates: Mapping[str, dt.date | None] | None = None,
    error_count: int = 0,
) -> None:
    last_values = current if last_known is None else last_known
    default_sample_date = module._local_date()
    with module.CACHE_LOCK:
        for entity_id, value in current.items():
            module.SENSOR_CACHE[entity_id] = value
            module.SENSOR_SAMPLE_DATE[entity_id] = (
                sample_dates.get(entity_id)
                if sample_dates is not None
                else default_sample_date
                if value is not None
                else None
            )
            module.SENSOR_ERROR_COUNT[entity_id] = error_count
        for entity_id, value in last_values.items():
            module.LAST_KNOWN_CACHE[entity_id] = value


def handler_for(module: types.ModuleType) -> Any:
    return object.__new__(module.ModbusHandler)


def read_request_pdu(function_code: int, start: int, quantity: int) -> bytes:
    return bytes([function_code]) + struct.pack(">HH", start, quantity)


def write_single_pdu(address: int, value: int) -> bytes:
    return bytes([6]) + struct.pack(">HH", address, value)


def write_multiple_pdu(address: int, values: Sequence[int]) -> bytes:
    payload = b"".join(struct.pack(">H", value) for value in values)
    return (
        bytes([16]) + struct.pack(">HHB", address, len(values), len(payload)) + payload
    )


def process_pdu(
    module: types.ModuleType,
    pdu: bytes,
    *,
    unit_id: int = 1,
) -> bytes:
    return handler_for(module).process_pdu(
        "peer:test",
        unit_id,
        pdu[0],
        pdu,
    )


def response_words(response_pdu: bytes, function_code: int) -> list[int]:
    if len(response_pdu) < 2:
        raise AssertionError("response PDU is too short")
    if response_pdu[0] != function_code:
        raise AssertionError(f"expected FC{function_code}, got 0x{response_pdu[0]:02x}")
    byte_count = response_pdu[1]
    data = response_pdu[2:]
    if byte_count != len(data) or byte_count % 2:
        raise AssertionError("response byte count is inconsistent")
    return [
        struct.unpack(">H", data[offset : offset + 2])[0]
        for offset in range(0, len(data), 2)
    ]


def config_errors(events: Iterable[Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    for event in events:
        if event.get("kind") == "config_validation_failed":
            errors.extend(str(error) for error in event.get("errors", []))
    return errors


class ProbeTestCase(unittest.TestCase):
    """Fresh isolated runtime and temporary shared directory for every test."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="fake_solis_probe_test_"
        )
        self.addCleanup(self._temporary_directory.cleanup)
        self.temp_path = Path(self._temporary_directory.name)
        self.new_probe()

    def new_probe(
        self,
        options: Mapping[str, Any] | None = None,
        *,
        options_text: str | None = None,
    ) -> types.ModuleType:
        self.module, self.events = load_probe(
            options,
            options_text=options_text,
        )
        self.module.EVENT_DIR = str(self.temp_path)
        self.module.EVENT_LOG = str(self.temp_path / "events.jsonl")
        self.module.REGISTER_FILE = str(self.temp_path / "registers.json")
        return self.module

    def assert_valid_and_initialize(
        self,
        payloads: Mapping[str, dict[str, Any]] | None = None,
        *,
        timezone_name: str | None = "Europe/Amsterdam",
        update: bool = True,
    ) -> None:
        validate_and_initialize(
            self.module,
            canonical_payloads() if payloads is None else payloads,
            timezone_name=timezone_name,
            update=update,
        )
