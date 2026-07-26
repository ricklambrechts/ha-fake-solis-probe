"""Canonical register encoding, ownership, storage, and hot reload."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Sequence
from typing import Any

from . import config, event_log, home_assistant

REGISTER_FILE = config.DEFAULT_REGISTER_FILE

REG_LOCK = threading.Lock()
REGISTER_RELOAD_LOCK = threading.Lock()

# The layers are deliberately separate. There is no compatibility adapter
# exposing input and holding registers as one shared map.
PROFILE_INPUT_REGISTERS: dict[int, int] = {}
PROFILE_HOLDING_REGISTERS: dict[int, int] = {}
INPUT_REGISTER_BASELINE: dict[int, int] = {}
HOLDING_REGISTER_BASELINE: dict[int, int] = {}
HOLDING_WRITE_OVERLAY: dict[int, int] = {}

REGISTER_FILE_FINGERPRINT: tuple[int, int] | None = None
REGISTER_FILE_REJECTED_FINGERPRINT: tuple[int, int] | None = None

# Cumulative and daily continuity state changes in the same REG_LOCK
# transaction as its corresponding register values.
TOTAL_PV_GENERATION_LAST_KWH: float | None = None
DAILY_PV_GENERATION_LAST_KWH: float | None = None
DAILY_PV_GENERATION_DATE = None
DAILY_REQUIRES_CURRENT_DATE_SAMPLE = False
REMOTE_DISPATCH_LAST_WRITE_MONOTONIC: float | None = None


def _address_set(*items: Any) -> frozenset[int]:
    addresses: set[int] = set()
    for item in items:
        if isinstance(item, range):
            addresses.update(item)
        elif isinstance(item, (tuple, list, set, frozenset)):
            addresses.update(int(value) for value in item)
        else:
            addresses.add(int(item))
    return frozenset(addresses)


# Profile ownership always wins over registers.json. Disabled optional metrics
# remain owned and read as zero. Blocked addresses cannot be overridden.
PROFILE_INPUT_ADDRESSES = _address_set(
    range(33000, 33020),  # identity and canonical 16-word serial
    (33029, 33030, 33035),  # total and daily PV generation
    (33057, 33058),  # total DC/PV power
    33069,  # HMI sub-version
    33121,  # operating-status bitfield
    (33135, 33139),  # battery direction and SoC
    (33147, 33148),  # household and backup load
    (33149, 33150),  # battery power
    (33151, 33152),  # optional AC grid-port power
    33245,  # blocked parallel-inverter power
    (33263, 33264),  # meter total active power
    34351,  # unknown, blocked
    range(34391, 34394),  # Smart Port profile only, blocked
    range(34502, 34505),  # remote-dispatch capability/version/status
    range(34621, 34623),  # unknown, blocked
    35000,  # inverter type
)

# These are fake holding-register settings only. When smart management is
# disabled they remain profile-owned zeroes. When enabled, validated defaults
# are exposed and accepted FC6/FC16 writes may overlay them in memory.
LEGACY_SMART_MANAGEMENT_HOLDING_ADDRESSES = _address_set(
    (43010, 43011),  # maximum charge and overdischarge SoC
    43052,  # active-power limit
    (43073, 43074),  # grid feed-in switch and backflow limit
    43110,  # storage-control bitfield
    (43128, 43129, 43132, 43133, 43135, 43136),  # legacy remote control
    43140,  # meter type and location
    43282,  # legacy remote-control timeout
    43384,  # observed but unresolved; blocked zero
    range(43483, 43489),  # hybrid controls; 43484-43486 are blocked zero
)
REMOTE_DISPATCH_HOLDING_ADDRESSES = _address_set(range(44100, 44200))
REMOTE_DISPATCH_RESERVED_HOLDING_ADDRESSES = _address_set(
    range(44111, 44116),
    range(44124, 44130),
    range(44139, 44144),
    range(44153, 44158),
    range(44167, 44172),
    range(44181, 44186),
    range(44195, 44200),
)
PROFILE_HOLDING_ADDRESSES = _address_set(
    LEGACY_SMART_MANAGEMENT_HOLDING_ADDRESSES,
    REMOTE_DISPATCH_HOLDING_ADDRESSES,
)
BLOCKED_PROFILE_HOLDING_ADDRESSES = _address_set(
    43384,
    range(43484, 43487),
    REMOTE_DISPATCH_RESERVED_HOLDING_ADDRESSES,
)

METER_LOCATION_CODES = {
    "grid_side": 0x01,
    "load_side": 0x02,
    "grid_and_pv": 0x03,
}
METER_TYPE_CODES = {
    "general_1_phase": 0x01,
    "acrel_3_phase": 0x02,
    "general_3_phase": 0x03,
    "eastron_1_phase": 0x04,
    "eastron_3_phase": 0x05,
    "no_meter": 0x06,
}


def _require_int(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def to_u16_word(value: int) -> int:
    value = _require_int(value, "U16 value")
    if not 0 <= value <= config.U16_MAX:
        raise ValueError("U16 value must be in 0..65535")
    return value


def to_s16_word(value: int) -> int:
    value = _require_int(value, "S16 value")
    if not config.S16_MIN <= value <= config.S16_MAX:
        raise ValueError("S16 value must be in -32768..32767")
    return value if value >= 0 else value + (1 << 16)


def to_u32_pair(value: int) -> tuple[int, int]:
    value = _require_int(value, "U32 value")
    if not 0 <= value <= config.U32_MAX:
        raise ValueError("U32 value must be in 0..4294967295")
    return (value >> 16, value & config.U16_MAX)


def to_s32_pair(value: int) -> tuple[int, int]:
    value = _require_int(value, "S32 value")
    if not config.S32_MIN <= value <= config.S32_MAX:
        raise ValueError("S32 value must be in -2147483648..2147483647")
    encoded = value if value >= 0 else value + (1 << 32)
    return (encoded >> 16, encoded & config.U16_MAX)


def encode_serial_words(serial: str) -> list[int]:
    encoded = serial.encode("ascii")
    if len(encoded) > 32:
        raise ValueError("fake_serial must encode to at most 32 ASCII bytes")
    padded = encoded.ljust(32, b"\x00")
    return [
        int.from_bytes(padded[offset : offset + 2], byteorder="big")
        for offset in range(0, 32, 2)
    ]


def _configured_meter_type_code() -> int:
    meter_type = str(config.OPTIONS.get("smart_management_meter_type", "auto")).strip()
    if meter_type == "auto":
        inverter_type = int(config.OPTIONS.get("fake_inverter_type_code", 2030))
        if inverter_type in (2050, 2060):
            meter_type = "eastron_3_phase"
        elif inverter_type in (2030, 2040):
            meter_type = "eastron_1_phase"
        else:
            meter_type = "no_meter"
    return METER_TYPE_CODES[meter_type]


def _smart_management_holding_defaults() -> dict[int, int]:
    if not bool(config.OPTIONS.get("smart_management_enabled", False)):
        return {}

    maximum_soc = int(config.OPTIONS["smart_management_max_charge_soc"])
    minimum_soc = int(config.OPTIONS["smart_management_min_soc"])
    active_limit = round(
        float(config.OPTIONS["smart_management_active_power_limit_percent"]) * 100
    )
    backflow_limit = int(config.OPTIONS["smart_management_backflow_limit_w"]) // 100
    peak_baseline_soc = int(config.OPTIONS["smart_management_peak_baseline_soc"])
    peak_grid_power = (
        int(config.OPTIONS["smart_management_peak_max_grid_power_w"]) // 100
    )
    grid_feed_in_enabled = bool(
        config.OPTIONS["smart_management_grid_feed_in_limit_enabled"]
    )
    allow_grid_charge = bool(config.OPTIONS["smart_management_allow_grid_charge"])
    peak_shaving_enabled = bool(config.OPTIONS["smart_management_peak_shaving_enabled"])
    storage_control = 1 << (11 if peak_shaving_enabled else 0)
    if allow_grid_charge:
        storage_control |= 1 << 5
    meter_location = METER_LOCATION_CODES[
        str(config.OPTIONS["smart_management_meter_location"]).strip()
    ]
    meter_word = (meter_location << 8) | _configured_meter_type_code()
    failsafe_minutes = int(config.OPTIONS["smart_management_failsafe_minutes"])

    return {
        43010: maximum_soc,
        43011: minimum_soc,
        43052: active_limit,
        43073: (1 << 4) if grid_feed_in_enabled else 0,
        43074: backflow_limit,
        43110: storage_control,
        43128: 0,
        43129: 0,
        43132: 0,
        43133: 0,
        43135: 0,
        43136: 0,
        43140: meter_word,
        43282: failsafe_minutes,
        43483: (1 << 7) if peak_shaving_enabled else 0,
        43487: peak_baseline_soc,
        43488: peak_grid_power,
        44100: 0,
        44101: failsafe_minutes,
        44102: (1 << 1) if grid_feed_in_enabled else 0,
        44103: 0,
        44104: backflow_limit,
        44105: 1,
        44106: 0,
        44107: 0,
        44108: 0,
        44109: minimum_soc,
        44110: maximum_soc,
    }


def initialize_profile_registers() -> None:
    """Initialize every profile-owned address after successful validation."""
    global TOTAL_PV_GENERATION_LAST_KWH
    global DAILY_PV_GENERATION_LAST_KWH, DAILY_PV_GENERATION_DATE
    global DAILY_REQUIRES_CURRENT_DATE_SAMPLE
    global REMOTE_DISPATCH_LAST_WRITE_MONOTONIC

    serial_words = encode_serial_words(str(config.OPTIONS.get("fake_serial", "")))
    type_code = to_u16_word(int(config.OPTIONS["fake_inverter_type_code"]))
    hmi_sub_version = to_u16_word(int(config.OPTIONS["fake_hmi_sub_version"]))
    smart_management_enabled = bool(
        config.OPTIONS.get("smart_management_enabled", False)
    )
    holding_defaults = _smart_management_holding_defaults()

    with REG_LOCK:
        PROFILE_INPUT_REGISTERS.clear()
        PROFILE_INPUT_REGISTERS.update(
            {address: 0 for address in PROFILE_INPUT_ADDRESSES}
        )
        for offset, word in enumerate(serial_words):
            PROFILE_INPUT_REGISTERS[33004 + offset] = word
        PROFILE_INPUT_REGISTERS[33069] = hmi_sub_version
        PROFILE_INPUT_REGISTERS[33121] = 0x0001
        if smart_management_enabled:
            PROFILE_INPUT_REGISTERS[34502] = 0xAA55
            PROFILE_INPUT_REGISTERS[34503] = 0x0001
            PROFILE_INPUT_REGISTERS[34504] = 0x0000
        PROFILE_INPUT_REGISTERS[35000] = type_code
        PROFILE_HOLDING_REGISTERS.clear()
        PROFILE_HOLDING_REGISTERS.update(
            {address: 0 for address in PROFILE_HOLDING_ADDRESSES}
        )
        PROFILE_HOLDING_REGISTERS.update(holding_defaults)
        HOLDING_WRITE_OVERLAY.clear()
        TOTAL_PV_GENERATION_LAST_KWH = None
        DAILY_PV_GENERATION_LAST_KWH = None
        DAILY_PV_GENERATION_DATE = home_assistant.local_date()
        DAILY_REQUIRES_CURRENT_DATE_SAMPLE = DAILY_PV_GENERATION_DATE is not None
        REMOTE_DISPATCH_LAST_WRITE_MONOTONIC = None

    event_log.log_event(
        "profile_initialized",
        operating_status=1,
        serial_words=16,
        inverter_type_code=type_code,
        hmi_sub_version=hmi_sub_version,
        smart_management_enabled=smart_management_enabled,
        profile_holding_words=len(PROFILE_HOLDING_ADDRESSES),
    )


def validate_register_file(
    raw: Any,
) -> tuple[dict[int, int], dict[int, int]]:
    if not isinstance(raw, dict):
        raise ValueError(  # noqa: TRY004
            "registers.json must contain a JSON object"
        )
    unknown_banks = set(raw) - {"input", "holding"}
    if unknown_banks:
        names = ", ".join(sorted(str(name) for name in unknown_banks))
        raise ValueError(f"registers.json has unknown top-level bank(s): {names}")

    parsed: dict[str, dict[int, int]] = {"input": {}, "holding": {}}
    for bank_name in ("input", "holding"):
        bank = raw.get(bank_name, {})
        if not isinstance(bank, dict):
            raise ValueError(  # noqa: TRY004
                f"registers.json bank '{bank_name}' must be a JSON object"
            )
        for address_text, value in bank.items():
            if not isinstance(address_text, str) or not address_text.isdecimal():
                raise ValueError(
                    f"registers.json bank '{bank_name}' has an invalid address"
                )
            address = int(address_text)
            if not 0 <= address <= config.U16_MAX:
                raise ValueError(
                    f"registers.json address {address_text} is outside 0..65535"
                )
            owned_addresses = (
                PROFILE_INPUT_ADDRESSES
                if bank_name == "input"
                else PROFILE_HOLDING_ADDRESSES
            )
            if address in owned_addresses:
                raise ValueError(
                    f"registers.json address {bank_name}.{address} is profile-owned"
                )
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(  # noqa: TRY004
                    f"registers.json value for {bank_name}.{address} "
                    "must be an integer from 0 to 65535"
                )
            if not 0 <= value <= config.U16_MAX:
                raise ValueError(
                    f"registers.json value for {bank_name}.{address} "
                    "must be in 0..65535"
                )
            parsed[bank_name][address] = value
    return parsed["input"], parsed["holding"]


def load_register_file_if_changed(startup: bool = False) -> bool:
    """Atomically hot-reload the two unowned register baselines.

    Invalid startup content returns ``False``. Invalid hot reloads retain both
    last valid baselines and the holding write overlay.
    """
    global REGISTER_FILE_FINGERPRINT, REGISTER_FILE_REJECTED_FINGERPRINT

    with REGISTER_RELOAD_LOCK:
        try:
            stat = os.stat(REGISTER_FILE)
            fingerprint = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            had_file_state = (
                REGISTER_FILE_FINGERPRINT is not None
                or REGISTER_FILE_REJECTED_FINGERPRINT is not None
            )
            if REGISTER_FILE_FINGERPRINT is not None:
                with REG_LOCK:
                    INPUT_REGISTER_BASELINE.clear()
                    HOLDING_REGISTER_BASELINE.clear()
            REGISTER_FILE_FINGERPRINT = None
            REGISTER_FILE_REJECTED_FINGERPRINT = None
            if had_file_state:
                event_log.log_event("register_file_removed")
            return True
        except Exception as exc:  # noqa: BLE001
            event_log.log_event("register_file_stat_error", error=str(exc))
            return not startup

        if fingerprint == REGISTER_FILE_FINGERPRINT:
            return True
        if fingerprint == REGISTER_FILE_REJECTED_FINGERPRINT:
            return not startup

        try:
            with open(REGISTER_FILE, "r", encoding="utf-8") as file_handle:
                raw = json.load(file_handle)
            input_values, holding_values = validate_register_file(raw)
        except Exception as exc:  # noqa: BLE001
            REGISTER_FILE_REJECTED_FINGERPRINT = fingerprint
            event_log.log_event(
                "register_file_load_error",
                error=str(exc),
                retained_last_valid=not startup,
            )
            return not startup

        with REG_LOCK:
            INPUT_REGISTER_BASELINE.clear()
            INPUT_REGISTER_BASELINE.update(input_values)
            HOLDING_REGISTER_BASELINE.clear()
            HOLDING_REGISTER_BASELINE.update(holding_values)

        REGISTER_FILE_FINGERPRINT = fingerprint
        REGISTER_FILE_REJECTED_FINGERPRINT = None
        event_log.log_event(
            "register_file_loaded",
            input_count=len(input_values),
            holding_count=len(holding_values),
        )
        return True


def _validate_range(start: int, quantity: int) -> None:
    if quantity < 1 or start < 0 or start > config.U16_MAX:
        raise ValueError("invalid register range")
    if start + quantity - 1 > config.U16_MAX:
        raise ValueError("register range exceeds 65535")


def read_input_registers(start: int, quantity: int) -> list[int]:
    _validate_range(start, quantity)
    load_register_file_if_changed()
    expired = False
    with REG_LOCK:
        expired = _expire_remote_dispatch_locked(time.monotonic())
        values = [
            PROFILE_INPUT_REGISTERS[address]
            if address in PROFILE_INPUT_ADDRESSES
            else INPUT_REGISTER_BASELINE.get(address, 0)
            for address in range(start, start + quantity)
        ]
    if expired:
        event_log.log_event("remote_dispatch_failsafe_expired")
    return values


def read_holding_registers(start: int, quantity: int) -> list[int]:
    _validate_range(start, quantity)
    load_register_file_if_changed()
    smart_management_enabled = bool(
        config.OPTIONS.get("smart_management_enabled", False)
    )
    expired = False
    with REG_LOCK:
        expired = _expire_remote_dispatch_locked(time.monotonic())
        values = [
            (
                HOLDING_WRITE_OVERLAY.get(
                    address,
                    PROFILE_HOLDING_REGISTERS[address],
                )
                if smart_management_enabled
                and address in PROFILE_HOLDING_ADDRESSES
                and address not in BLOCKED_PROFILE_HOLDING_ADDRESSES
                else PROFILE_HOLDING_REGISTERS[address]
                if address in PROFILE_HOLDING_ADDRESSES
                else HOLDING_WRITE_OVERLAY.get(
                    address,
                    HOLDING_REGISTER_BASELINE.get(address, 0),
                )
            )
            for address in range(start, start + quantity)
        ]
    if expired:
        event_log.log_event("remote_dispatch_failsafe_expired")
    return values


def _current_holding_word_locked(address: int) -> int:
    if (
        bool(config.OPTIONS.get("smart_management_enabled", False))
        and address in PROFILE_HOLDING_ADDRESSES
        and address not in BLOCKED_PROFILE_HOLDING_ADDRESSES
    ):
        return HOLDING_WRITE_OVERLAY.get(
            address,
            PROFILE_HOLDING_REGISTERS[address],
        )
    if address in PROFILE_HOLDING_ADDRESSES:
        return PROFILE_HOLDING_REGISTERS[address]
    return HOLDING_WRITE_OVERLAY.get(
        address,
        HOLDING_REGISTER_BASELINE.get(address, 0),
    )


def _expire_remote_dispatch_locked(now: float) -> bool:
    global REMOTE_DISPATCH_LAST_WRITE_MONOTONIC

    if (
        not bool(config.OPTIONS.get("smart_management_enabled", False))
        or REMOTE_DISPATCH_LAST_WRITE_MONOTONIC is None
        or PROFILE_INPUT_REGISTERS.get(34504, 0) == 0
    ):
        return False
    timeout_minutes = _current_holding_word_locked(44101)
    if now - REMOTE_DISPATCH_LAST_WRITE_MONOTONIC < timeout_minutes * 60:
        return False
    HOLDING_WRITE_OVERLAY[44100] = 0
    PROFILE_INPUT_REGISTERS[34504] = 0
    REMOTE_DISPATCH_LAST_WRITE_MONOTONIC = None
    return True


def _normalized_profile_write_locked(address: int, value: int) -> int:
    if address in (44103, 44104) and value == config.U16_MAX:
        return PROFILE_HOLDING_REGISTERS[address]
    return value


def _valid_profile_write_locked(
    address: int,
    value: int,
    proposed: dict[int, int],
) -> bool:
    """Apply verified fake-profile limits; invalid writes retain readback."""
    if address == 43010:
        return 70 <= value <= 100
    if address == 43011:
        return 5 <= value <= 40
    if address == 43052:
        return value <= 11000
    if address == 43110:
        if value & ~0x0FFF:
            return False
        enabled = {bit for bit in range(12) if value & (1 << bit)}
        if 0 in enabled and enabled.intersection({2, 6, 11}):
            return False
        if 1 in enabled and not enabled.intersection({0, 6}):
            return False
        if 2 in enabled and enabled.intersection({0, 1, 6, 11}):
            return False
        if 4 in enabled and 11 in enabled:
            return False
        if 6 in enabled and enabled.intersection({0, 2, 11}):
            return False
        return not (11 in enabled and enabled.intersection({0, 2, 4, 6}))
    if address == 43140:
        location = value >> 8
        meter_type = value & 0xFF
        return (
            location in METER_LOCATION_CODES.values()
            and meter_type in METER_TYPE_CODES.values()
        )
    if address == 43282:
        return 1 <= value <= 30
    if address == 43483:
        return value & ~0x00FF == 0
    if address == 43487:
        return 7 <= value <= 100
    if address == 44100:
        return value in (0, 1)
    if address == 44101:
        return 1 <= value <= 1440
    if address == 44102:
        return value & ~0x0003 == 0
    if address in (44103, 44104):
        return True
    if address == 44105:
        return value in (1, 2, 3, 4)
    if address == 44108:
        return value & ~0x00FF == 0 and all(
            ((value >> shift) & 0x03) != 0x03 for shift in (0, 2, 4, 6)
        )
    if address in (44109, 44110):
        lower = proposed[44109]
        upper = proposed[44110]
        return 0 <= lower <= upper <= 100
    return True


def write_holding_registers(
    start: int,
    values: Sequence[int],
) -> tuple[int, int]:
    """Mirror a valid write and return (mirrored words, profile-blocked words)."""
    global REMOTE_DISPATCH_LAST_WRITE_MONOTONIC

    _validate_range(start, len(values))
    validated = [to_u16_word(value) for value in values]
    smart_management_enabled = bool(
        config.OPTIONS.get("smart_management_enabled", False)
    )
    mirrored_count = 0
    blocked_count = 0
    remote_addresses: list[int] = []
    status_before = 0
    status_after = 0
    with REG_LOCK:
        status_before = PROFILE_INPUT_REGISTERS.get(34504, 0)
        proposed = {
            address: _current_holding_word_locked(address)
            for address in PROFILE_HOLDING_ADDRESSES
        }
        for offset, value in enumerate(validated):
            address = start + offset
            if (
                smart_management_enabled
                and address in PROFILE_HOLDING_ADDRESSES
                and address not in BLOCKED_PROFILE_HOLDING_ADDRESSES
            ):
                proposed[address] = _normalized_profile_write_locked(
                    address,
                    value,
                )

        for offset, value in enumerate(validated):
            address = start + offset
            if address in PROFILE_HOLDING_ADDRESSES and (
                not smart_management_enabled
                or address in BLOCKED_PROFILE_HOLDING_ADDRESSES
            ):
                blocked_count += 1
                continue
            normalized = (
                proposed[address] if address in PROFILE_HOLDING_ADDRESSES else value
            )
            if address in PROFILE_HOLDING_ADDRESSES and not _valid_profile_write_locked(
                address,
                normalized,
                proposed,
            ):
                blocked_count += 1
                continue
            HOLDING_WRITE_OVERLAY[address] = normalized
            mirrored_count += 1
            if address in REMOTE_DISPATCH_HOLDING_ADDRESSES:
                remote_addresses.append(address)

        if remote_addresses:
            REMOTE_DISPATCH_LAST_WRITE_MONOTONIC = time.monotonic()
            if _current_holding_word_locked(44100) == 0:
                status_after = 0
            elif any(address >= 44116 for address in remote_addresses):
                status_after = (
                    3
                    if any(
                        address >= 44116 and proposed[address] != 0
                        for address in remote_addresses
                    )
                    else 1
                )
            elif any(address >= 44105 for address in remote_addresses):
                status_after = 2
            else:
                status_after = 1
            PROFILE_INPUT_REGISTERS[34504] = status_after
        else:
            status_after = status_before

    if status_after != status_before:
        event_log.log_event(
            "remote_dispatch_status_changed",
            previous=status_before,
            current=status_after,
        )
    return mirrored_count, blocked_count
