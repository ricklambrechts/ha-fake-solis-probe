"""Startup validation for App options and current Home Assistant states."""

from __future__ import annotations

import math
import re
from typing import Any

from . import config, event_log, home_assistant, sensor_cache


def _append_error(errors: list[str], option: str, expectation: str) -> None:
    errors.append(f"Option '{option}' {expectation}")


def _positive_finite_option(
    errors: list[str],
    option: str,
) -> float | None:
    raw = config.OPTIONS.get(option)
    if isinstance(raw, bool):
        _append_error(errors, option, "must be a positive finite number")
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _append_error(errors, option, "must be a positive finite number")
        return None
    if not math.isfinite(value) or value <= 0:
        _append_error(errors, option, "must be a positive finite number")
        return None
    return value


def _behavior_option(
    errors: list[str],
    option: str,
) -> str | None:
    value = str(config.OPTIONS.get(option, "")).strip()
    if value not in ("zero", "last_known"):
        _append_error(errors, option, "must be 'zero' or 'last_known'")
        return None
    return value


def _integer_option(
    errors: list[str],
    option: str,
    minimum: int,
    maximum: int,
    *,
    multiple_of: int = 1,
) -> int | None:
    raw = config.OPTIONS.get(option)
    if isinstance(raw, bool) or not isinstance(raw, int):
        _append_error(
            errors,
            option,
            f"must be an integer from {minimum} to {maximum}",
        )
        return None
    if not minimum <= raw <= maximum or raw % multiple_of:
        suffix = f" in multiples of {multiple_of}" if multiple_of != 1 else ""
        _append_error(
            errors,
            option,
            f"must be an integer from {minimum} to {maximum}{suffix}",
        )
        return None
    return raw


def _bounded_finite_option(
    errors: list[str],
    option: str,
    minimum: float,
    maximum: float,
) -> float | None:
    raw = config.OPTIONS.get(option)
    if isinstance(raw, bool):
        _append_error(
            errors,
            option,
            f"must be a finite number from {minimum:g} to {maximum:g}",
        )
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _append_error(
            errors,
            option,
            f"must be a finite number from {minimum:g} to {maximum:g}",
        )
        return None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        _append_error(
            errors,
            option,
            f"must be a finite number from {minimum:g} to {maximum:g}",
        )
        return None
    return value


def _entity_option(
    errors: list[str],
    option: str,
    required: bool,
) -> str | None:
    entity_id = str(config.OPTIONS.get(option, "")).strip()
    if not entity_id:
        if required:
            _append_error(
                errors,
                option,
                "must be a non-empty sensor.* entity ID",
            )
        return None
    if not entity_id.startswith("sensor."):
        _append_error(errors, option, "must be a sensor.* entity ID")
        return None
    return entity_id


def _state_number(
    errors: list[str],
    option: str,
    payload: dict[str, Any],
) -> float | None:
    state = payload.get("state")
    if isinstance(state, str) and state in config.TRANSIENT_HA_STATES:
        return None
    if isinstance(state, bool):
        _append_error(
            errors,
            option,
            "must currently be finite numeric, 'unknown', or 'unavailable'",
        )
        return None
    try:
        value = float(state)
    except (TypeError, ValueError):
        _append_error(
            errors,
            option,
            "must currently be finite numeric, 'unknown', or 'unavailable'",
        )
        return None
    if not math.isfinite(value):
        _append_error(errors, option, "must currently be a finite number")
        return None
    return value


def _is_transient_state(payload: dict[str, Any]) -> bool:
    state = payload.get("state")
    return isinstance(state, str) and state in config.TRANSIENT_HA_STATES


def _validate_generation_metadata(
    errors: list[str],
    option: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    device_class = attributes.get("device_class")
    if device_class not in (None, "", "energy"):
        _append_error(
            errors,
            option,
            "must use an entity with device_class 'energy' when declared",
        )
    unit = attributes.get("unit_of_measurement")
    if (
        isinstance(unit, str)
        and unit.strip()
        and unit.strip().lower() not in config.ENERGY_UNITS
    ):
        _append_error(
            errors,
            option,
            "must use energy-compatible unit metadata",
        )
    friendly_name = attributes.get("friendly_name", "")
    semantic_text = " ".join(
        (
            entity_id.replace(".", " ").replace("_", " "),
            str(friendly_name).replace("_", " "),
        )
    ).lower()
    semantic_words = set(re.findall(r"[a-z0-9]+", semantic_text))
    if semantic_words.intersection({"import", "export", "net", "cost", "balance"}):
        _append_error(
            errors,
            option,
            "must represent PV generation, not grid flow, cost, or a balance",
        )


def _validate_power_metadata(
    errors: list[str],
    option: str,
    payload: dict[str, Any],
) -> None:
    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        return
    device_class = attributes.get("device_class")
    if device_class not in (None, "", "power"):
        _append_error(
            errors,
            option,
            "must use an entity with device_class 'power' when declared",
        )


def _validate_metric_range(
    errors: list[str],
    option: str,
    kind: str,
    value: float,
    scale: float,
) -> None:
    physical = value * scale
    if not math.isfinite(physical):
        _append_error(errors, option, "must remain finite after scaling")
        return
    valid = True
    expectation = ""
    if kind == "pv_power":
        valid = physical >= 0 and math.floor(physical) <= config.U32_MAX
        expectation = "must resolve to 0..4294967295 W after scaling"
    elif kind == "grid_power":
        convention = str(config.OPTIONS.get("grid_power_sign_convention", "negate"))
        canonical = -physical if convention == "negate" else physical
        raw = math.trunc(canonical)
        valid = config.S32_MIN <= raw <= config.S32_MAX
        expectation = "must fit signed 32-bit watts after scaling and sign conversion"
    elif kind == "total_generation":
        valid = physical >= 0 and math.floor(physical) <= config.U32_MAX
        expectation = "must resolve to nonnegative U32 kWh after scaling"
    elif kind == "daily_generation":
        valid = physical >= 0 and math.floor(physical * 10) <= config.U16_MAX
        expectation = "must resolve to nonnegative U16 tenths of kWh after scaling"
    elif kind == "battery_soc":
        valid = 0 <= physical <= 100
        expectation = "must resolve to 0..100% after scaling"
    elif kind == "battery_power":
        valid = math.floor(abs(physical)) <= config.S32_MAX
        expectation = "must resolve to magnitude 0..2147483647 W after scaling"
    elif kind == "household_load" or kind == "backup_load":
        valid = physical >= 0 and math.floor(physical) <= config.U16_MAX
        expectation = "must resolve to 0..65535 W after scaling"
    elif kind == "ac_grid_port_power":
        convention = str(
            config.OPTIONS.get("ac_grid_port_power_sign_convention", "direct")
        )
        canonical = -physical if convention == "negate" else physical
        raw = math.trunc(canonical)
        valid = config.S32_MIN <= raw <= config.S32_MAX
        expectation = "must fit signed 32-bit watts after scaling and sign conversion"
    if not valid:
        _append_error(errors, option, expectation)


def validate_config() -> bool:
    """Validate options and current HA states before opening Modbus port 502."""
    errors: list[str] = []

    if config.OPTIONS_LOAD_ERROR:
        errors.append("The app options file is invalid JSON; correct it before startup")

    for removed, replacement in config.REMOVED_OPTIONS.items():
        if removed in config.RAW_OPTIONS:
            errors.append(
                f"Option '{removed}' was removed; replace it with '{replacement}'"
            )

    for boolean_option in (
        "enable_http",
        "log_raw_hex",
        "mirror_writes",
        "smart_management_enabled",
    ):
        if not isinstance(config.OPTIONS.get(boolean_option), bool):
            _append_error(
                errors,
                boolean_option,
                "must be true or false",
            )

    log_max_bytes = config.OPTIONS.get("log_max_bytes")
    if (
        isinstance(log_max_bytes, bool)
        or not isinstance(log_max_bytes, int)
        or log_max_bytes < 0
    ):
        _append_error(
            errors,
            "log_max_bytes",
            "must be a nonnegative integer",
        )
    log_backup_count = config.OPTIONS.get("log_backup_count")
    if (
        isinstance(log_backup_count, bool)
        or not isinstance(log_backup_count, int)
        or log_backup_count > 100
    ):
        _append_error(
            errors,
            "log_backup_count",
            "must be an integer no greater than 100",
        )

    battery_attached = config.OPTIONS.get("battery_attached", False)
    if not isinstance(battery_attached, bool):
        _append_error(errors, "battery_attached", "must be true or false")
        battery_attached = False

    sign_convention = str(config.OPTIONS.get("grid_power_sign_convention", "")).strip()
    if sign_convention not in ("negate", "direct"):
        _append_error(
            errors,
            "grid_power_sign_convention",
            "must be 'negate' or 'direct'",
        )

    smart_management_enabled = config.OPTIONS.get(
        "smart_management_enabled",
        False,
    )
    if not isinstance(smart_management_enabled, bool):
        smart_management_enabled = False

    if smart_management_enabled:
        if not bool(config.OPTIONS.get("mirror_writes", False)):
            _append_error(
                errors,
                "mirror_writes",
                "must be true when smart_management_enabled is true",
            )
        for boolean_option in (
            "smart_management_grid_feed_in_limit_enabled",
            "smart_management_allow_grid_charge",
            "smart_management_peak_shaving_enabled",
        ):
            if not isinstance(config.OPTIONS.get(boolean_option), bool):
                _append_error(errors, boolean_option, "must be true or false")

        max_charge_soc = _integer_option(
            errors,
            "smart_management_max_charge_soc",
            70,
            100,
        )
        min_soc = _integer_option(
            errors,
            "smart_management_min_soc",
            5,
            40,
        )
        if (
            max_charge_soc is not None
            and min_soc is not None
            and min_soc >= max_charge_soc
        ):
            _append_error(
                errors,
                "smart_management_min_soc",
                "must be lower than smart_management_max_charge_soc",
            )
        _bounded_finite_option(
            errors,
            "smart_management_active_power_limit_percent",
            0.0,
            110.0,
        )
        _integer_option(
            errors,
            "smart_management_backflow_limit_w",
            0,
            config.U16_MAX * 100,
            multiple_of=100,
        )
        _integer_option(
            errors,
            "smart_management_peak_baseline_soc",
            7,
            100,
        )
        _integer_option(
            errors,
            "smart_management_peak_max_grid_power_w",
            0,
            config.U16_MAX * 100,
            multiple_of=100,
        )
        _integer_option(
            errors,
            "smart_management_failsafe_minutes",
            1,
            30,
        )

        meter_location = str(
            config.OPTIONS.get("smart_management_meter_location", "")
        ).strip()
        if meter_location not in ("grid_side", "load_side", "grid_and_pv"):
            _append_error(
                errors,
                "smart_management_meter_location",
                "must be 'grid_side', 'load_side', or 'grid_and_pv'",
            )
        meter_type = str(config.OPTIONS.get("smart_management_meter_type", "")).strip()
        if meter_type not in (
            "auto",
            "general_1_phase",
            "acrel_3_phase",
            "general_3_phase",
            "eastron_1_phase",
            "eastron_3_phase",
            "no_meter",
        ):
            _append_error(
                errors,
                "smart_management_meter_type",
                "must be a supported semantic meter type",
            )

    metric_specs: list[tuple[str, str, str, str, bool]] = [
        (
            "ha_sensor_pv_power",
            "pv_power_scale",
            "pv_power_unavailable_behavior",
            "pv_power",
            True,
        ),
        (
            "ha_sensor_grid_power",
            "grid_power_scale",
            "grid_power_unavailable_behavior",
            "grid_power",
            True,
        ),
        (
            "ha_sensor_total_pv_generation",
            "total_pv_generation_scale",
            "total_pv_generation_unavailable_behavior",
            "total_generation",
            True,
        ),
        (
            "ha_sensor_daily_pv_generation",
            "daily_pv_generation_scale",
            "daily_pv_generation_unavailable_behavior",
            "daily_generation",
            True,
        ),
    ]

    household_entity = str(
        config.OPTIONS.get("ha_sensor_household_load_power", "")
    ).strip()
    if household_entity:
        metric_specs.append(
            (
                "ha_sensor_household_load_power",
                "household_load_power_scale",
                "household_load_power_unavailable_behavior",
                "household_load",
                True,
            )
        )

    backup_entity = str(config.OPTIONS.get("ha_sensor_backup_load_power", "")).strip()
    if backup_entity:
        metric_specs.append(
            (
                "ha_sensor_backup_load_power",
                "backup_load_power_scale",
                "backup_load_power_unavailable_behavior",
                "backup_load",
                True,
            )
        )

    ac_grid_port_entity = str(
        config.OPTIONS.get("ha_sensor_ac_grid_port_power", "")
    ).strip()
    if ac_grid_port_entity:
        ac_grid_port_sign = str(
            config.OPTIONS.get("ac_grid_port_power_sign_convention", "")
        ).strip()
        if ac_grid_port_sign not in ("direct", "negate"):
            _append_error(
                errors,
                "ac_grid_port_power_sign_convention",
                "must be 'direct' or 'negate'",
            )
        metric_specs.append(
            (
                "ha_sensor_ac_grid_port_power",
                "ac_grid_port_power_scale",
                "ac_grid_port_power_unavailable_behavior",
                "ac_grid_port_power",
                True,
            )
        )

    if battery_attached:
        battery_sign = str(
            config.OPTIONS.get("battery_power_sign_convention", "")
        ).strip()
        if battery_sign not in ("charge_positive", "discharge_positive"):
            _append_error(
                errors,
                "battery_power_sign_convention",
                "must be 'charge_positive' or 'discharge_positive'",
            )
        metric_specs.extend(
            (
                (
                    "ha_sensor_battery_soc",
                    "battery_soc_scale",
                    "battery_soc_unavailable_behavior",
                    "battery_soc",
                    True,
                ),
                (
                    "ha_sensor_battery_power",
                    "battery_power_scale",
                    "battery_power_unavailable_behavior",
                    "battery_power",
                    True,
                ),
            )
        )

    entities_by_option: dict[str, str] = {}
    scales_by_option: dict[str, float] = {}
    for (
        entity_option,
        scale_option,
        behavior_option,
        _,
        required,
    ) in metric_specs:
        entity_id = _entity_option(errors, entity_option, required=required)
        scale = _positive_finite_option(errors, scale_option)
        _behavior_option(errors, behavior_option)
        if entity_id is not None:
            entities_by_option[entity_option] = entity_id
        if scale is not None:
            scales_by_option[entity_option] = scale

    serial = str(config.OPTIONS.get("fake_serial", ""))
    try:
        serial_bytes = serial.encode("ascii")
    except UnicodeEncodeError:
        _append_error(
            errors,
            "fake_serial",
            "must contain only ASCII characters",
        )
    else:
        if len(serial_bytes) > 32:
            _append_error(
                errors,
                "fake_serial",
                "must encode to at most 32 ASCII bytes",
            )

    type_code = config.OPTIONS.get("fake_inverter_type_code")
    if (
        isinstance(type_code, bool)
        or not isinstance(type_code, int)
        or not 0 <= type_code <= config.U16_MAX
    ):
        _append_error(
            errors,
            "fake_inverter_type_code",
            "must be an integer from 0 to 65535",
        )

    _integer_option(
        errors,
        "fake_hmi_sub_version",
        0,
        config.U16_MAX,
    )

    if errors:
        event_log.log_event("config_validation_failed", errors=errors)
        for error in errors:
            print(f"[FATAL] {error}", flush=True)
        return False

    entity_payloads: dict[str, dict[str, Any]] = {}
    for entity_id in dict.fromkeys(entities_by_option.values()):
        ok, payload, message = home_assistant.ha_api_get_entity(entity_id)
        if not ok or payload is None:
            affected = [
                option
                for option, configured in entities_by_option.items()
                if configured == entity_id
            ]
            for option in affected:
                _append_error(
                    errors,
                    option,
                    f"must reference an existing HA entity ({message})",
                )
            continue
        entity_payloads[entity_id] = payload

    numeric_seed: dict[str, float | None] = {}
    for entity_option, _, _, kind, _ in metric_specs:
        entity_id = entities_by_option.get(entity_option)
        scale = scales_by_option.get(entity_option)
        if entity_id is None or scale is None:
            continue
        payload = entity_payloads.get(entity_id)
        if payload is None:
            continue
        if kind in ("total_generation", "daily_generation"):
            _validate_generation_metadata(
                errors,
                entity_option,
                entity_id,
                payload,
            )
        elif kind in (
            "pv_power",
            "grid_power",
            "battery_power",
            "household_load",
            "backup_load",
            "ac_grid_port_power",
        ):
            _validate_power_metadata(errors, entity_option, payload)

        before = len(errors)
        value = _state_number(errors, entity_option, payload)
        if _is_transient_state(payload):
            numeric_seed.setdefault(entity_id, None)
            continue
        if value is None or len(errors) != before:
            continue
        _validate_metric_range(errors, entity_option, kind, value, scale)
        numeric_seed[entity_id] = value

    if errors:
        event_log.log_event("config_validation_failed", errors=errors)
        for error in errors:
            print(f"[FATAL] {error}", flush=True)
        return False

    home_assistant.resolve_ha_timezone()

    with sensor_cache.CACHE_LOCK:
        for entity_id in dict.fromkeys(entities_by_option.values()):
            value = numeric_seed.get(entity_id)
            sensor_cache.SENSOR_CACHE[entity_id] = value
            sensor_cache.SENSOR_SAMPLE_DATE[entity_id] = (
                home_assistant.payload_local_date(entity_payloads[entity_id])
            )
            if value is not None:
                sensor_cache.LAST_KNOWN_CACHE[entity_id] = value
            else:
                sensor_cache.LAST_KNOWN_CACHE.setdefault(entity_id, None)
            sensor_cache.SENSOR_ERROR_COUNT[entity_id] = 0

    event_log.log_event(
        "config_validation_passed",
        sensor_options=list(entities_by_option),
        grid_sign_convention=sign_convention,
        battery_attached=battery_attached,
        smart_management_enabled=smart_management_enabled,
    )
    return True
