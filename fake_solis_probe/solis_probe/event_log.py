"""Structured event logging with bounded on-disk rotation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
from typing import Any

from . import config

EVENT_DIR = config.DEFAULT_EVENT_DIR
EVENT_LOG = config.DEFAULT_EVENT_LOG
LOG_LOCK = threading.Lock()


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")


def private_ref(value: str, prefix: str) -> str:
    """Return a stable diagnostic reference without logging personal data."""
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def rotate_log_if_needed() -> None:
    """Rotate events.jsonl when configured size and retention limits require it.

    This function must be called while ``LOG_LOCK`` is held.
    """
    raw_max_bytes = config.OPTIONS.get("log_max_bytes", 5 * 1024 * 1024)
    if isinstance(raw_max_bytes, bool) or not isinstance(raw_max_bytes, int):
        max_bytes = 5 * 1024 * 1024
    else:
        max_bytes = raw_max_bytes
    raw_backup_count = config.OPTIONS.get("log_backup_count", 3)
    if isinstance(raw_backup_count, bool) or not isinstance(raw_backup_count, int):
        backup_count = 3
    else:
        backup_count = min(raw_backup_count, 100)
    if max_bytes <= 0:
        return
    try:
        size = os.path.getsize(EVENT_LOG)
    except FileNotFoundError:
        return
    except Exception:  # noqa: BLE001
        return
    if size < max_bytes:
        return
    if backup_count <= 0:
        try:
            with open(EVENT_LOG, "w", encoding="utf-8"):
                pass
            print(
                f"[Fake Solis Probe] log truncated: {EVENT_LOG}"
                f" ({size // 1024} KiB cleared, no backups kept)",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"[Fake Solis Probe] log truncation failed: {exc}",
                flush=True,
            )
        return
    for number in range(backup_count - 1, 0, -1):
        source = f"{EVENT_LOG}.{number}"
        destination = f"{EVENT_LOG}.{number + 1}"
        try:
            if os.path.exists(source):
                os.replace(source, destination)
        except Exception as exc:  # noqa: BLE001
            print(
                "[Fake Solis Probe] log rotation rename "
                f"{source} -> {destination}: {exc}",
                flush=True,
            )
    try:
        os.replace(EVENT_LOG, f"{EVENT_LOG}.1")
        print(
            f"[Fake Solis Probe] log rotated: {EVENT_LOG}"
            f" ({size // 1024} KiB) -> .1"
            f" (backup_count={backup_count})",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[Fake Solis Probe] log rotation rename to .1 failed: {exc}",
            flush=True,
        )


def log_event(kind: str, **data: Any) -> None:
    """Write one redaction-safe JSON event to stdout and the shared log."""
    record = {"ts": now_iso(), "kind": kind, **data}
    line = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    with LOG_LOCK:
        print(line, flush=True)
        try:
            os.makedirs(EVENT_DIR, exist_ok=True)
            rotate_log_if_needed()
            with open(EVENT_LOG, "a", encoding="utf-8") as file_handle:
                file_handle.write(line + "\n")
        except Exception as exc:  # noqa: BLE001
            print(
                f"[Fake Solis Probe] Could not write {EVENT_LOG}: {exc}",
                flush=True,
            )


def hex_bytes(data: bytes) -> str:
    return data.hex(" ")
