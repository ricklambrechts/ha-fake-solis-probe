"""Static settings and Home Assistant App option loading."""

from __future__ import annotations

import json
import os
from typing import Any

CONFIG_PATH = "/data/options.json"
DEFAULT_EVENT_DIR = "/share/fake_solis_probe"
DEFAULT_EVENT_LOG = os.path.join(DEFAULT_EVENT_DIR, "events.jsonl")
DEFAULT_REGISTER_FILE = os.path.join(DEFAULT_EVENT_DIR, "registers.json")

VERSION = "0.9.0"
POLL_INTERVAL_SECONDS = 5.0
HA_REQUEST_TIMEOUT_SECONDS = 5.0
MAX_PARALLEL_HA_REQUESTS = 8
MAX_MODBUS_PDU_LENGTH = 253
MAX_MBAP_LENGTH = MAX_MODBUS_PDU_LENGTH + 1
ERROR_LOG_INTERVAL = 12

U16_MAX = 0xFFFF
S16_MIN = -(1 << 15)
S16_MAX = (1 << 15) - 1
U32_MAX = 0xFFFFFFFF
S32_MIN = -(1 << 31)
S32_MAX = (1 << 31) - 1

DEFAULT_OPTIONS: dict[str, Any] = {
    "enable_http": False,
    "log_raw_hex": False,
    "mirror_writes": False,
    "ha_sensor_pv_power": "",
    "ha_sensor_grid_power": "",
    "ha_sensor_total_pv_generation": "",
    "ha_sensor_daily_pv_generation": "",
    "grid_power_sign_convention": "negate",
    "pv_power_scale": 1.0,
    "grid_power_scale": 1.0,
    "total_pv_generation_scale": 1.0,
    "daily_pv_generation_scale": 1.0,
    "pv_power_unavailable_behavior": "zero",
    "grid_power_unavailable_behavior": "zero",
    "total_pv_generation_unavailable_behavior": "last_known",
    "daily_pv_generation_unavailable_behavior": "zero",
    "battery_attached": False,
    "ha_sensor_battery_soc": "",
    "ha_sensor_battery_power": "",
    "battery_soc_scale": 1.0,
    "battery_power_scale": 1.0,
    "battery_power_sign_convention": "discharge_positive",
    "battery_power_unavailable_behavior": "zero",
    "battery_soc_unavailable_behavior": "last_known",
    "ha_sensor_household_load_power": "",
    "household_load_power_scale": 1.0,
    "household_load_power_unavailable_behavior": "zero",
    "ha_sensor_backup_load_power": "",
    "backup_load_power_scale": 1.0,
    "backup_load_power_unavailable_behavior": "zero",
    "ha_sensor_ac_grid_port_power": "",
    "ac_grid_port_power_scale": 1.0,
    "ac_grid_port_power_sign_convention": "direct",
    "ac_grid_port_power_unavailable_behavior": "zero",
    "smart_management_enabled": False,
    "smart_management_max_charge_soc": 95,
    "smart_management_min_soc": 20,
    "smart_management_active_power_limit_percent": 100.0,
    "smart_management_grid_feed_in_limit_enabled": False,
    "smart_management_backflow_limit_w": 0,
    "smart_management_allow_grid_charge": True,
    "smart_management_meter_location": "grid_side",
    "smart_management_meter_type": "auto",
    "smart_management_peak_shaving_enabled": False,
    "smart_management_peak_baseline_soc": 20,
    "smart_management_peak_max_grid_power_w": 0,
    "smart_management_failsafe_minutes": 5,
    "fake_vendor": "Ginlong",
    "fake_inverter_model": "Solis S6-EH1P",
    "fake_logger_model": "S2-WL-ST",
    "fake_serial": "S2WLSTFAKE001",
    "fake_hmi_sub_version": 0,
    "fake_inverter_type_code": 2030,
    "log_max_bytes": 5 * 1024 * 1024,
    "log_backup_count": 3,
}

REMOVED_OPTIONS: dict[str, str] = {
    "ha_sensor_total_energy": "ha_sensor_total_pv_generation",
    "ha_sensor_daily_energy": "ha_sensor_daily_pv_generation",
    "total_energy_scale": "total_pv_generation_scale",
    "daily_energy_scale": "daily_pv_generation_scale",
    "total_energy_unavailable_behavior": ("total_pv_generation_unavailable_behavior"),
    "daily_energy_unavailable_behavior": ("daily_pv_generation_unavailable_behavior"),
}

CORE_SENSOR_KEYS = (
    "ha_sensor_pv_power",
    "ha_sensor_grid_power",
    "ha_sensor_total_pv_generation",
    "ha_sensor_daily_pv_generation",
)

TRANSIENT_HA_STATES = frozenset({"unknown", "unavailable"})
ENERGY_UNITS = frozenset({"wh", "kwh", "mwh", "gwh", "j", "kj", "mj", "gj"})

RAW_OPTIONS: dict[str, Any] = {}
OPTIONS_LOAD_ERROR: str | None = None


def load_options() -> dict[str, Any]:
    """Load App options while retaining the raw key set for migration checks."""
    global RAW_OPTIONS, OPTIONS_LOAD_ERROR

    options = dict(DEFAULT_OPTIONS)
    RAW_OPTIONS = {}
    OPTIONS_LOAD_ERROR = None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file_handle:
            loaded = json.load(file_handle)
        if not isinstance(loaded, dict):
            raise ValueError(  # noqa: TRY004
                "options.json must contain a JSON object"
            )
        RAW_OPTIONS = dict(loaded)
        options.update(loaded)
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        OPTIONS_LOAD_ERROR = str(exc)
        print(
            f"[Fake Solis Probe] Failed to read {CONFIG_PATH}: {exc}",
            flush=True,
        )
    return options


def safe_option_summary() -> dict[str, Any]:
    """Return non-sensitive options suitable for structured startup logging."""
    return {
        "enable_http": bool(OPTIONS.get("enable_http", False)),
        "mirror_writes": bool(OPTIONS.get("mirror_writes", False)),
        "battery_attached": bool(OPTIONS.get("battery_attached", False)),
        "household_load_configured": bool(
            str(OPTIONS.get("ha_sensor_household_load_power", "")).strip()
        ),
        "backup_load_configured": bool(
            str(OPTIONS.get("ha_sensor_backup_load_power", "")).strip()
        ),
        "ac_grid_port_power_configured": bool(
            str(OPTIONS.get("ha_sensor_ac_grid_port_power", "")).strip()
        ),
        "smart_management_enabled": bool(
            OPTIONS.get("smart_management_enabled", False)
        ),
        "fake_inverter_type_code": OPTIONS.get("fake_inverter_type_code", 2030),
    }


def enabled_sensor_keys() -> list[str]:
    """Return enabled semantic sensor option keys in polling order."""
    keys = list(CORE_SENSOR_KEYS)
    if str(OPTIONS.get("ha_sensor_household_load_power", "")).strip():
        keys.append("ha_sensor_household_load_power")
    if str(OPTIONS.get("ha_sensor_backup_load_power", "")).strip():
        keys.append("ha_sensor_backup_load_power")
    if str(OPTIONS.get("ha_sensor_ac_grid_port_power", "")).strip():
        keys.append("ha_sensor_ac_grid_port_power")
    if bool(OPTIONS.get("battery_attached", False)):
        keys.extend(("ha_sensor_battery_soc", "ha_sensor_battery_power"))
    return keys


def enabled_sensor_entity_ids() -> list[str]:
    """Return de-duplicated configured Home Assistant entity IDs."""
    return list(
        dict.fromkeys(
            entity_id
            for key in enabled_sensor_keys()
            if (entity_id := str(OPTIONS.get(key, "")).strip())
        )
    )


OPTIONS = load_options()
