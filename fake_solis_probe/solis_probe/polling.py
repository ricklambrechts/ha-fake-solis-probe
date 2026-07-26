"""Bounded concurrent polling of configured Home Assistant entities."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import time
from collections.abc import Sequence

from . import (
    config,
    event_log,
    home_assistant,
    sensor_cache,
    telemetry,
)

POLL_LOOP_ERROR_COUNT = 0


def poll_sensor_entities_once(
    entity_ids: Sequence[str] | None = None,
) -> float:
    """Poll each distinct entity once and atomically update both caches."""
    if entity_ids is None:
        entity_ids = telemetry.enabled_sensor_entity_ids()
    unique_entities = list(dict.fromkeys(entity_ids))
    started = time.monotonic()
    if not unique_entities:
        telemetry.update_live_registers()
        return time.monotonic() - started

    worker_count = min(config.MAX_PARALLEL_HA_REQUESTS, len(unique_entities))
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="ha-poll",
    ) as executor:
        future_by_entity = {
            executor.submit(
                home_assistant.ha_api_get_state_sample,
                entity_id,
            ): entity_id
            for entity_id in unique_entities
        }
        results: dict[
            str,
            tuple[float | None, dt.date | None],
        ] = {}
        for future, entity_id in future_by_entity.items():
            try:
                results[entity_id] = future.result()
            except Exception:  # noqa: BLE001
                results[entity_id] = (None, None)

    unavailable_events: list[tuple[str, int, bool]] = []
    with sensor_cache.CACHE_LOCK:
        for entity_id in unique_entities:
            value, sample_date = results.get(entity_id, (None, None))
            if value is not None:
                sensor_cache.SENSOR_CACHE[entity_id] = value
                sensor_cache.SENSOR_SAMPLE_DATE[entity_id] = sample_date
                sensor_cache.LAST_KNOWN_CACHE[entity_id] = value
                sensor_cache.SENSOR_ERROR_COUNT[entity_id] = 0
            else:
                count = sensor_cache.SENSOR_ERROR_COUNT.get(entity_id, 0) + 1
                sensor_cache.SENSOR_ERROR_COUNT[entity_id] = count
                sensor_cache.SENSOR_CACHE[entity_id] = None
                sensor_cache.SENSOR_SAMPLE_DATE[entity_id] = None
                unavailable_events.append(
                    (
                        entity_id,
                        count,
                        sensor_cache.LAST_KNOWN_CACHE.get(entity_id) is not None,
                    )
                )

    for entity_id, count, has_last_known in unavailable_events:
        if count == 1 or count % config.ERROR_LOG_INTERVAL == 0:
            event_log.log_event(
                "sensor_unavailable",
                source=event_log.private_ref(entity_id, "entity"),
                consecutive_errors=count,
                has_last_known=has_last_known,
            )

    telemetry.update_live_registers()
    return time.monotonic() - started


def sensor_poll_loop() -> None:
    global POLL_LOOP_ERROR_COUNT

    entity_ids = telemetry.enabled_sensor_entity_ids()
    with sensor_cache.CACHE_LOCK:
        for entity_id in entity_ids:
            sensor_cache.SENSOR_CACHE.setdefault(entity_id, None)
            sensor_cache.LAST_KNOWN_CACHE.setdefault(entity_id, None)
            sensor_cache.SENSOR_SAMPLE_DATE.setdefault(entity_id, None)
            sensor_cache.SENSOR_ERROR_COUNT.setdefault(entity_id, 0)

    event_log.log_event(
        "sensor_poll_started",
        sensor_count=len(entity_ids),
        interval_seconds=config.POLL_INTERVAL_SECONDS,
        request_timeout_seconds=config.HA_REQUEST_TIMEOUT_SECONDS,
        max_parallel_requests=config.MAX_PARALLEL_HA_REQUESTS,
    )
    cycle = 0
    while True:
        cycle_started = time.monotonic()
        try:
            duration = poll_sensor_entities_once(entity_ids)
            POLL_LOOP_ERROR_COUNT = 0
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - cycle_started
            POLL_LOOP_ERROR_COUNT += 1
            with sensor_cache.CACHE_LOCK:
                for entity_id in entity_ids:
                    sensor_cache.SENSOR_CACHE[entity_id] = None
                    sensor_cache.SENSOR_SAMPLE_DATE[entity_id] = None
                    sensor_cache.SENSOR_ERROR_COUNT[entity_id] = (
                        sensor_cache.SENSOR_ERROR_COUNT.get(entity_id, 0) + 1
                    )
            if (
                POLL_LOOP_ERROR_COUNT == 1
                or POLL_LOOP_ERROR_COUNT % config.ERROR_LOG_INTERVAL == 0
            ):
                event_log.log_event(
                    "sensor_poll_cycle_failed",
                    error=str(exc),
                    consecutive_errors=POLL_LOOP_ERROR_COUNT,
                )
            try:
                telemetry.update_live_registers()
            except Exception as fallback_exc:  # noqa: BLE001
                if (
                    POLL_LOOP_ERROR_COUNT == 1
                    or POLL_LOOP_ERROR_COUNT % config.ERROR_LOG_INTERVAL == 0
                ):
                    event_log.log_event(
                        "sensor_poll_fallback_failed",
                        error=str(fallback_exc),
                        consecutive_errors=POLL_LOOP_ERROR_COUNT,
                    )
        cycle += 1
        if cycle == 1 or cycle % config.ERROR_LOG_INTERVAL == 0:
            with sensor_cache.CACHE_LOCK:
                available = sum(
                    sensor_cache.SENSOR_CACHE.get(entity_id) is not None
                    for entity_id in entity_ids
                )
            event_log.log_event(
                "sensor_poll_cycle",
                sensor_count=len(entity_ids),
                available_count=available,
                duration_ms=round(duration * 1000),
                overrun=duration > config.POLL_INTERVAL_SECONDS,
            )
        remaining = config.POLL_INTERVAL_SECONDS - duration
        if remaining > 0:
            time.sleep(remaining)
