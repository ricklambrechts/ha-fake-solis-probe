"""Optional HTTP identity probe used during discovery experiments."""

from __future__ import annotations

import http.server
import json
from typing import Any

from . import config, event_log


class ProbeHTTPHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SolisDataLogger/1.0"
    sys_version = ""

    def do_GET(self) -> None:
        self._handle(True)

    def do_POST(self) -> None:
        self._handle(True)

    def do_HEAD(self) -> None:
        self._handle(False)

    def log_message(self, *_args: Any) -> None:
        pass

    def _handle(self, send_body: bool) -> None:
        event_log.log_event(
            "http_request",
            peer=event_log.private_ref(
                str(self.client_address[0]),
                "peer",
            ),
            method=self.command,
            target=event_log.private_ref(self.path, "http-target"),
        )
        payload = json.dumps(
            {
                "vendor": str(config.OPTIONS.get("fake_vendor", "Ginlong")),
                "model": str(
                    config.OPTIONS.get(
                        "fake_inverter_model",
                        "Solis S6-EH1P",
                    )
                ),
                "status": "online",
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if send_body:
            self.wfile.write(payload)
