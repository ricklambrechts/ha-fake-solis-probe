"""Thread-safe ownership of Home Assistant sensor caches."""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Iterable

# A failed poll clears the current reading while retaining the last successful
# finite value. All four maps are read or mutated while CACHE_LOCK is held.
SENSOR_CACHE: dict[str, float | None] = {}
LAST_KNOWN_CACHE: dict[str, float | None] = {}
SENSOR_SAMPLE_DATE: dict[str, dt.date | None] = {}
SENSOR_ERROR_COUNT: dict[str, int] = {}
CACHE_LOCK = threading.Lock()


def snapshot(
    entity_ids: Iterable[str],
) -> dict[
    str,
    tuple[float | None, float | None, int, dt.date | None],
]:
    """Return one atomic snapshot of the requested sensor cache entries."""
    with CACHE_LOCK:
        return {
            entity_id: (
                SENSOR_CACHE.get(entity_id),
                LAST_KNOWN_CACHE.get(entity_id),
                SENSOR_ERROR_COUNT.get(entity_id, 0),
                SENSOR_SAMPLE_DATE.get(entity_id),
            )
            for entity_id in entity_ids
        }
