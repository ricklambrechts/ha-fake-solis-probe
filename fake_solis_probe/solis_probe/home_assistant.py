"""Home Assistant Supervisor API access and local-calendar handling."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, event_log

HA_TIME_ZONE: ZoneInfo | None = None
HA_TIME_ZONE_NAME: str | None = None
EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR = "zero"


def _ha_api_json(path: str, timeout: float) -> tuple[bool, Any, str]:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return False, None, "SUPERVISOR_TOKEN is not set"
    url = f"http://supervisor/core/api/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return True, payload, ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, None, "not found (HTTP 404)"
        return False, None, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)


def ha_api_get_entity(
    entity_id: str,
    timeout: float = 10.0,
) -> tuple[bool, dict[str, Any] | None, str]:
    encoded = urllib.parse.quote(entity_id, safe="._-")
    ok, payload, message = _ha_api_json(
        f"states/{encoded}",
        timeout=timeout,
    )
    if not ok:
        return False, None, message
    if not isinstance(payload, dict):
        return False, None, "Home Assistant returned a non-object state"
    return True, payload, ""


def ha_api_get_timezone_name() -> tuple[bool, str | None, str]:
    ok, payload, message = _ha_api_json("config", timeout=10.0)
    if not ok:
        return False, None, message
    if not isinstance(payload, dict):
        return False, None, "Home Assistant returned a non-object config"
    name = payload.get("time_zone")
    if not isinstance(name, str) or not name.strip():
        return False, None, "Home Assistant config has no time_zone"
    return True, name.strip(), ""


def resolve_ha_timezone() -> None:
    """Resolve the authoritative Home Assistant IANA timezone."""
    global HA_TIME_ZONE, HA_TIME_ZONE_NAME
    global EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR

    configured_behavior = str(
        config.OPTIONS.get(
            "daily_pv_generation_unavailable_behavior",
            "zero",
        )
    )
    EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR = configured_behavior
    HA_TIME_ZONE = None
    HA_TIME_ZONE_NAME = None

    ok, name, message = ha_api_get_timezone_name()
    if ok and name is not None:
        try:
            HA_TIME_ZONE = ZoneInfo(name)
            HA_TIME_ZONE_NAME = name
            event_log.log_event("ha_timezone_resolved", time_zone=name)
            return
        except (ZoneInfoNotFoundError, ValueError):
            message = f"unknown IANA time zone '{name}'"

    if configured_behavior == "last_known":
        EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR = "zero"
    event_log.log_event(
        "ha_timezone_unresolved",
        detail=message,
        daily_behavior=EFFECTIVE_DAILY_PV_GENERATION_BEHAVIOR,
    )


def local_date() -> dt.date | None:
    if HA_TIME_ZONE is None:
        return None
    return dt.datetime.now(dt.UTC).astimezone(HA_TIME_ZONE).date()


def payload_local_date(payload: dict[str, Any]) -> dt.date | None:
    """Resolve an HA state's last update to the configured HA calendar date."""
    if HA_TIME_ZONE is None:
        return None
    timestamp = payload.get("last_updated") or payload.get("last_changed")
    if not isinstance(timestamp, str) or not timestamp.strip():
        return None
    normalized = timestamp.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(HA_TIME_ZONE).date()


def ha_api_get_state_sample(
    entity_id: str,
) -> tuple[float | None, dt.date | None]:
    ok, payload, _message = ha_api_get_entity(
        entity_id,
        timeout=config.HA_REQUEST_TIMEOUT_SECONDS,
    )
    if not ok or payload is None:
        return None, None
    state = payload.get("state")
    if state in (None, "", "unavailable", "unknown"):
        return None, None
    if isinstance(state, bool):
        return None, None
    try:
        value = float(state)
    except (TypeError, ValueError):
        return None, None
    if not math.isfinite(value):
        return None, None
    return value, payload_local_date(payload)


def ha_api_get_state(entity_id: str) -> float | None:
    """Return the current finite scalar state without its HA update date."""
    value, _sample_date = ha_api_get_state_sample(entity_id)
    return value
