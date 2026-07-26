"""Convert cached Home Assistant states to canonical profile registers."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable
from typing import Any

from . import config, event_log, home_assistant, registers, sensor_cache

FALLBACK_LOG_COUNT: dict[str, int] = {}
VALIDATION_LOG_COUNT: dict[str, int] = {}


def _reset_fallback_count(
    entity_id: str,
    behavior: str,
    metric_key: str,
) -> None:
    FALLBACK_LOG_COUNT.pop(f"{metric_key}:{entity_id}:{behavior}", None)


def _apply_behavior(
    entity_id: str,
    raw: float | None,
    behavior: str,
    scale: float,
    error_count: int,
    last_known_val: float | None = None,
    metric_key: str = "sensor",
) -> float | None:
    """Scale a current reading or apply its deterministic unavailable policy."""
    if raw is not None:
        return raw * scale
    if behavior == "zero":
        written_value: float | None = 0.0
    elif behavior == "last_known":
        written_value = None
    else:
        raise ValueError(f"unsupported unavailable behavior: {behavior}")

    key = f"{metric_key}:{entity_id}:{behavior}"
    count = FALLBACK_LOG_COUNT.get(key, 0) + 1
    FALLBACK_LOG_COUNT[key] = count
    if count == 1 or count % config.ERROR_LOG_INTERVAL == 0:
        event_log.log_event(
            "register_fallback",
            source=event_log.private_ref(entity_id, "entity"),
            metric=metric_key,
            behavior=behavior,
            written_value=written_value,
            has_last_known=last_known_val is not None,
            consecutive_errors=error_count,
        )
    return written_value


def _log_metric_invalid(metric_key: str, reason: str) -> None:
    count = VALIDATION_LOG_COUNT.get(metric_key, 0) + 1
    VALIDATION_LOG_COUNT[metric_key] = count
    if count == 1 or count % config.ERROR_LOG_INTERVAL == 0:
        event_log.log_event(
            "metric_sample_invalid",
            metric=metric_key,
            reason=reason,
            consecutive_invalid=count,
        )


def _reset_metric_invalid(metric_key: str) -> None:
    VALIDATION_LOG_COUNT.pop(metric_key, None)


def _cache_values(
    entity_ids: Iterable[str],
) -> dict[
    str,
    tuple[float | None, float | None, int, dt.date | None],
]:
    return sensor_cache.snapshot(entity_ids)


def _resolve_metric(
    metric_key: str,
    entity_id: str,
    raw: float | None,
    last_known: float | None,
    error_count: int,
    behavior: str,
    scale: float,
    validator: Any,
    retain_invalid: bool = False,
    defer_valid_reset: bool = False,
) -> tuple[float | None, bool]:
    """Return a physical value and whether it is a current valid sample."""
    if raw is None:
        value = _apply_behavior(
            entity_id,
            None,
            behavior,
            scale,
            error_count,
            last_known,
            metric_key,
        )
        return value, False

    value = raw * scale
    if not math.isfinite(value):
        reason = "sample is non-finite after scaling"
    else:
        reason = validator(value)
    if reason:
        _log_metric_invalid(metric_key, reason)
        if retain_invalid:
            return None, False
        value = _apply_behavior(
            entity_id,
            None,
            behavior,
            scale,
            error_count,
            last_known,
            metric_key,
        )
        return value, False

    if not defer_valid_reset:
        _reset_metric_invalid(metric_key)
    _reset_fallback_count(entity_id, behavior, metric_key)
    return value, True


def _range_reason(
    value: float,
    minimum: float,
    maximum_raw: int,
    multiplier: float = 1.0,
    absolute: bool = False,
) -> str:
    checked = abs(value) if absolute else value
    if checked < minimum or math.floor(checked * multiplier) > maximum_raw:
        return "sample is outside the canonical register range"
    return ""


def update_live_registers() -> None:
    """Update all supported telemetry in one atomic profile transaction."""
    pv_entity = str(config.OPTIONS.get("ha_sensor_pv_power", "")).strip()
    grid_entity = str(config.OPTIONS.get("ha_sensor_grid_power", "")).strip()
    total_entity = str(config.OPTIONS.get("ha_sensor_total_pv_generation", "")).strip()
    daily_entity = str(config.OPTIONS.get("ha_sensor_daily_pv_generation", "")).strip()
    household_entity = str(
        config.OPTIONS.get("ha_sensor_household_load_power", "")
    ).strip()
    backup_entity = str(config.OPTIONS.get("ha_sensor_backup_load_power", "")).strip()
    ac_grid_port_entity = str(
        config.OPTIONS.get("ha_sensor_ac_grid_port_power", "")
    ).strip()
    battery_soc_entity = str(config.OPTIONS.get("ha_sensor_battery_soc", "")).strip()
    battery_power_entity = str(
        config.OPTIONS.get("ha_sensor_battery_power", "")
    ).strip()
    battery_attached = bool(config.OPTIONS.get("battery_attached", False))

    active_entities = [
        entity
        for entity in (
            pv_entity,
            grid_entity,
            total_entity,
            daily_entity,
            household_entity,
            backup_entity,
            ac_grid_port_entity,
            battery_soc_entity if battery_attached else "",
            battery_power_entity if battery_attached else "",
        )
        if entity
    ]
    cache = _cache_values(dict.fromkeys(active_entities))

    def cached(entity_id: str) -> tuple[float | None, float | None, int]:
        return cache.get(entity_id, (None, None, 0, None))[:3]

    daily_sample_date = cache.get(
        daily_entity,
        (None, None, 0, None),
    )[3]

    pv_value, _ = _resolve_metric(
        "pv_power",
        pv_entity,
        *cached(pv_entity),
        str(config.OPTIONS.get("pv_power_unavailable_behavior", "zero")),
        float(config.OPTIONS.get("pv_power_scale", 1.0)),
        lambda value: _range_reason(value, 0, config.U32_MAX),
    )

    grid_value, _ = _resolve_metric(
        "grid_power",
        grid_entity,
        *cached(grid_entity),
        str(config.OPTIONS.get("grid_power_unavailable_behavior", "zero")),
        float(config.OPTIONS.get("grid_power_scale", 1.0)),
        lambda value: (
            ""
            if config.S32_MIN
            <= math.trunc(
                -value
                if config.OPTIONS.get("grid_power_sign_convention", "negate")
                == "negate"
                else value
            )
            <= config.S32_MAX
            else "sample is outside the canonical signed 32-bit range"
        ),
    )

    total_value, total_is_sample = _resolve_metric(
        "total_pv_generation",
        total_entity,
        *cached(total_entity),
        str(
            config.OPTIONS.get(
                "total_pv_generation_unavailable_behavior",
                "last_known",
            )
        ),
        float(config.OPTIONS.get("total_pv_generation_scale", 1.0)),
        lambda value: _range_reason(value, 0, config.U32_MAX),
        retain_invalid=True,
        defer_valid_reset=True,
    )

    daily_value, daily_is_sample = _resolve_metric(
        "daily_pv_generation",
        daily_entity,
        *cached(daily_entity),
        home_assistant.EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR,
        float(config.OPTIONS.get("daily_pv_generation_scale", 1.0)),
        lambda value: _range_reason(
            value,
            0,
            config.U16_MAX,
            multiplier=10.0,
        ),
        retain_invalid=True,
        defer_valid_reset=True,
    )
    daily_timezone_blocked = False
    if home_assistant.HA_TIME_ZONE is None:
        daily_timezone_blocked = daily_is_sample
        daily_value = 0.0
        daily_is_sample = False

    household_value: float | None = 0.0
    if household_entity:
        household_value, _ = _resolve_metric(
            "household_load_power",
            household_entity,
            *cached(household_entity),
            str(
                config.OPTIONS.get(
                    "household_load_power_unavailable_behavior",
                    "zero",
                )
            ),
            float(config.OPTIONS.get("household_load_power_scale", 1.0)),
            lambda value: _range_reason(value, 0, config.U16_MAX),
        )

    backup_value: float | None = 0.0
    if backup_entity:
        backup_value, _ = _resolve_metric(
            "backup_load_power",
            backup_entity,
            *cached(backup_entity),
            str(
                config.OPTIONS.get(
                    "backup_load_power_unavailable_behavior",
                    "zero",
                )
            ),
            float(config.OPTIONS.get("backup_load_power_scale", 1.0)),
            lambda value: _range_reason(value, 0, config.U16_MAX),
        )

    ac_grid_port_value: float | None = 0.0
    if ac_grid_port_entity:
        ac_grid_port_value, _ = _resolve_metric(
            "ac_grid_port_power",
            ac_grid_port_entity,
            *cached(ac_grid_port_entity),
            str(
                config.OPTIONS.get(
                    "ac_grid_port_power_unavailable_behavior",
                    "zero",
                )
            ),
            float(config.OPTIONS.get("ac_grid_port_power_scale", 1.0)),
            lambda value: (
                ""
                if config.S32_MIN
                <= math.trunc(
                    -value
                    if config.OPTIONS.get(
                        "ac_grid_port_power_sign_convention",
                        "direct",
                    )
                    == "negate"
                    else value
                )
                <= config.S32_MAX
                else "sample is outside the canonical signed 32-bit range"
            ),
        )

    battery_soc_value: float | None = 0.0
    battery_power_value: float | None = 0.0
    if battery_attached:
        battery_soc_value, _ = _resolve_metric(
            "battery_soc",
            battery_soc_entity,
            *cached(battery_soc_entity),
            str(
                config.OPTIONS.get(
                    "battery_soc_unavailable_behavior",
                    "last_known",
                )
            ),
            float(config.OPTIONS.get("battery_soc_scale", 1.0)),
            lambda value: (
                "" if 0 <= value <= 100 else "sample is outside 0..100 percent"
            ),
        )
        battery_power_value, _ = _resolve_metric(
            "battery_power",
            battery_power_entity,
            *cached(battery_power_entity),
            str(
                config.OPTIONS.get(
                    "battery_power_unavailable_behavior",
                    "zero",
                )
            ),
            float(config.OPTIONS.get("battery_power_scale", 1.0)),
            lambda value: _range_reason(
                value,
                0,
                config.S32_MAX,
                absolute=True,
            ),
        )

    pv_pair = (
        registers.to_u32_pair(math.floor(pv_value)) if pv_value is not None else None
    )
    if grid_value is not None:
        grid_w = math.trunc(grid_value)
        if config.OPTIONS.get("grid_power_sign_convention", "negate") == "negate":
            grid_w = -grid_w
        grid_pair = registers.to_s32_pair(grid_w)
    else:
        grid_pair = None

    household_word = (
        registers.to_u16_word(math.floor(household_value))
        if household_value is not None
        else None
    )
    backup_word = (
        registers.to_u16_word(math.floor(backup_value))
        if backup_value is not None
        else None
    )
    if ac_grid_port_value is not None:
        ac_grid_port_w = math.trunc(ac_grid_port_value)
        if (
            config.OPTIONS.get(
                "ac_grid_port_power_sign_convention",
                "direct",
            )
            == "negate"
        ):
            ac_grid_port_w = -ac_grid_port_w
        ac_grid_port_pair = registers.to_s32_pair(ac_grid_port_w)
    else:
        ac_grid_port_pair = None
    battery_soc_word = (
        registers.to_u16_word(math.floor(battery_soc_value))
        if battery_soc_value is not None
        else None
    )

    battery_direction: int | None
    battery_pair: tuple[int, int] | None
    if battery_power_value is None:
        battery_direction = None
        battery_pair = None
    else:
        battery_magnitude = math.floor(abs(battery_power_value))
        if battery_magnitude == 0:
            battery_direction = 0
        else:
            positive_is_discharge = (
                config.OPTIONS.get(
                    "battery_power_sign_convention",
                    "discharge_positive",
                )
                == "discharge_positive"
            )
            is_discharge = (
                battery_power_value > 0
                if positive_is_discharge
                else battery_power_value < 0
            )
            battery_direction = 1 if is_discharge else 0
        battery_pair = registers.to_s32_pair(battery_magnitude)

    today = home_assistant.local_date()
    total_decreased = False
    daily_decreased = False
    daily_date_changed = False
    daily_stale_sample = False
    total_accepted = False
    daily_accepted = False

    with registers.REG_LOCK:
        if today is not None:
            if registers.DAILY_PV_GENERATION_DATE is None:
                registers.DAILY_PV_GENERATION_DATE = today
            elif registers.DAILY_PV_GENERATION_DATE != today:
                registers.DAILY_PV_GENERATION_DATE = today
                registers.DAILY_PV_GENERATION_LAST_KWH = None
                registers.DAILY_REQUIRES_CURRENT_DATE_SAMPLE = True
                registers.PROFILE_INPUT_REGISTERS[33035] = 0
                daily_date_changed = True

        if daily_is_sample and today is not None:
            if daily_sample_date != today:
                daily_stale_sample = True
                daily_value = None
                daily_is_sample = False
            elif daily_sample_date == today:
                registers.DAILY_REQUIRES_CURRENT_DATE_SAMPLE = False

        if pv_pair is not None:
            registers.PROFILE_INPUT_REGISTERS[33057] = pv_pair[0]
            registers.PROFILE_INPUT_REGISTERS[33058] = pv_pair[1]

        if grid_pair is not None:
            registers.PROFILE_INPUT_REGISTERS[33263] = grid_pair[0]
            registers.PROFILE_INPUT_REGISTERS[33264] = grid_pair[1]

        if total_value is not None:
            if (
                total_is_sample
                and registers.TOTAL_PV_GENERATION_LAST_KWH is not None
                and total_value < registers.TOTAL_PV_GENERATION_LAST_KWH
            ):
                retained_pair = registers.to_u32_pair(
                    math.floor(registers.TOTAL_PV_GENERATION_LAST_KWH)
                )
                registers.PROFILE_INPUT_REGISTERS[33029] = retained_pair[0]
                registers.PROFILE_INPUT_REGISTERS[33030] = retained_pair[1]
                total_decreased = True
            else:
                total_pair = registers.to_u32_pair(math.floor(total_value))
                registers.PROFILE_INPUT_REGISTERS[33029] = total_pair[0]
                registers.PROFILE_INPUT_REGISTERS[33030] = total_pair[1]
                if total_is_sample:
                    registers.TOTAL_PV_GENERATION_LAST_KWH = total_value
                    total_accepted = True

        if daily_value is not None:
            if (
                daily_is_sample
                and registers.DAILY_PV_GENERATION_LAST_KWH is not None
                and daily_value < registers.DAILY_PV_GENERATION_LAST_KWH
            ):
                daily_decreased = True
            else:
                registers.PROFILE_INPUT_REGISTERS[33035] = registers.to_u16_word(
                    math.floor(daily_value * 10)
                )
                if daily_is_sample:
                    registers.DAILY_PV_GENERATION_LAST_KWH = daily_value
                    daily_accepted = True

        if household_word is not None:
            registers.PROFILE_INPUT_REGISTERS[33147] = household_word

        if backup_word is not None:
            registers.PROFILE_INPUT_REGISTERS[33148] = backup_word

        if ac_grid_port_pair is not None:
            registers.PROFILE_INPUT_REGISTERS[33151] = ac_grid_port_pair[0]
            registers.PROFILE_INPUT_REGISTERS[33152] = ac_grid_port_pair[1]

        if battery_soc_word is not None:
            registers.PROFILE_INPUT_REGISTERS[33139] = battery_soc_word

        if battery_direction is not None and battery_pair is not None:
            registers.PROFILE_INPUT_REGISTERS[33135] = battery_direction
            registers.PROFILE_INPUT_REGISTERS[33149] = battery_pair[0]
            registers.PROFILE_INPUT_REGISTERS[33150] = battery_pair[1]

    if daily_date_changed:
        event_log.log_event(
            "daily_generation_date_changed",
            behavior=(home_assistant.EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR),
        )
    if daily_stale_sample:
        _log_metric_invalid(
            "daily_pv_generation",
            "sample was last updated before the current HA local date",
        )
    elif daily_timezone_blocked:
        _log_metric_invalid(
            "daily_pv_generation",
            "sample suppressed because the HA time zone is unresolved",
        )
    if total_decreased:
        _log_metric_invalid(
            "total_pv_generation",
            "sample decreased; retained previous cumulative value",
        )
    elif total_accepted:
        _reset_metric_invalid("total_pv_generation")
    if daily_decreased:
        _log_metric_invalid(
            "daily_pv_generation",
            "sample decreased within the HA local date",
        )
    elif daily_accepted:
        _reset_metric_invalid("daily_pv_generation")


def enabled_sensor_keys() -> list[str]:
    return config.enabled_sensor_keys()


def enabled_sensor_entity_ids() -> list[str]:
    return config.enabled_sensor_entity_ids()
