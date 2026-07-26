"""Application composition and server lifecycle."""

from __future__ import annotations

import os
import socketserver
import threading

from . import (
    config,
    event_log,
    http_probe,
    modbus,
    polling,
    registers,
    telemetry,
    validation,
)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve_http() -> None:
    try:
        event_log.log_event("http_server_starting", port=80)
        with ThreadedTCPServer(
            ("0.0.0.0", 80),
            http_probe.ProbeHTTPHandler,
        ) as server:
            event_log.log_event("http_server_started", port=80)
            server.serve_forever()
    except Exception as exc:  # noqa: BLE001
        event_log.log_event("http_server_failed", error=str(exc))


def serve_modbus() -> None:
    event_log.log_event("modbus_server_starting", port=502)
    with ThreadedTCPServer(
        ("0.0.0.0", 502),
        modbus.ModbusHandler,
    ) as server:
        event_log.log_event("modbus_server_started", port=502)
        server.serve_forever()


def main() -> int:
    """Validate, initialize, and run the fake inverter service."""
    os.makedirs(event_log.EVENT_DIR, exist_ok=True)
    event_log.log_event(
        "probe_start",
        version=config.VERSION,
        options=config.safe_option_summary(),
    )

    if not validation.validate_config():
        event_log.log_event(
            "probe_exit",
            reason="config_validation_failed",
        )
        return 1

    registers.initialize_profile_registers()
    if not registers.load_register_file_if_changed(startup=True):
        event_log.log_event(
            "probe_exit",
            reason="invalid_startup_register_file",
        )
        return 1

    # Validation seeds current finite HA states, so canonical registers are
    # populated before clients can connect. Transient states retain zero.
    telemetry.update_live_registers()

    threading.Thread(
        target=polling.sensor_poll_loop,
        name="sensor-poll",
        daemon=True,
    ).start()

    if bool(config.OPTIONS.get("enable_http", False)):
        threading.Thread(
            target=serve_http,
            name="http",
            daemon=True,
        ).start()
    else:
        event_log.log_event("http_server_disabled")

    try:
        serve_modbus()
    except Exception as exc:  # noqa: BLE001
        event_log.log_event("modbus_server_failed", error=str(exc))
        return 1
    return 0
