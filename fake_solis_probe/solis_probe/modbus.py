"""Modbus TCP protocol handling for the fake inverter."""

from __future__ import annotations

import socketserver
import struct

from . import config, event_log, registers


def exception_pdu(function_code: int, code: int) -> bytes:
    return bytes([function_code | 0x80, code])


def device_id_objects() -> list[tuple[int, bytes]]:
    vendor = str(config.OPTIONS.get("fake_vendor", "Ginlong"))
    model = str(config.OPTIONS.get("fake_inverter_model", "Solis S6-EH1P"))
    serial = str(config.OPTIONS.get("fake_serial", "S2WLSTFAKE001"))
    logger_model = str(config.OPTIONS.get("fake_logger_model", "S2-WL-ST"))
    return [
        (0x00, vendor.encode("ascii", "ignore")),
        (0x01, model.encode("ascii", "ignore")),
        (0x02, b"1.00"),
        (0x03, serial.encode("ascii", "ignore")),
        (0x04, logger_model.encode("ascii", "ignore")),
    ]


class ModbusHandler(socketserver.BaseRequestHandler):
    """Serve one Modbus TCP client connection."""

    def handle(self) -> None:
        peer_ip, _peer_port = self.client_address[:2]
        peer_ref = event_log.private_ref(str(peer_ip), "peer")
        event_log.log_event("modbus_connection_open", peer=peer_ref)
        try:
            while True:
                header = self._recv_exact(7)
                if header is None:
                    return
                transaction_id, protocol, length, unit_id = struct.unpack(
                    ">HHHB", header
                )
                if protocol != 0 or length < 2 or length > config.MAX_MBAP_LENGTH:
                    event_log.log_event(
                        "modbus_bad_mbap_header",
                        peer=peer_ref,
                        transaction_id=transaction_id,
                        protocol_id=protocol,
                        length=length,
                    )
                    return
                pdu = self._recv_exact(length - 1)
                if pdu is None:
                    return
                function_code = pdu[0]
                if config.OPTIONS.get("log_raw_hex", False):
                    event_log.log_event(
                        "modbus_request_raw",
                        peer=peer_ref,
                        transaction_id=transaction_id,
                        unit_id=unit_id,
                        length=length,
                        pdu_hex=event_log.hex_bytes(pdu),
                    )
                try:
                    response_pdu = self.process_pdu(
                        peer_ref,
                        unit_id,
                        function_code,
                        pdu,
                    )
                except Exception as exc:  # noqa: BLE001
                    event_log.log_event(
                        "modbus_process_error",
                        peer=peer_ref,
                        unit_id=unit_id,
                        fc=function_code,
                        error=str(exc),
                    )
                    response_pdu = exception_pdu(function_code, 4)
                response_header = struct.pack(
                    ">HHHB",
                    transaction_id,
                    0,
                    len(response_pdu) + 1,
                    unit_id,
                )
                self.request.sendall(response_header + response_pdu)
                if config.OPTIONS.get("log_raw_hex", False):
                    event_log.log_event(
                        "modbus_response_raw",
                        peer=peer_ref,
                        transaction_id=transaction_id,
                        unit_id=unit_id,
                        pdu_hex=event_log.hex_bytes(response_pdu),
                    )
        except ConnectionResetError:
            event_log.log_event(
                "modbus_connection_reset",
                peer=peer_ref,
            )
        except Exception as exc:  # noqa: BLE001
            event_log.log_event(
                "modbus_connection_error",
                peer=peer_ref,
                error=str(exc),
            )
        finally:
            event_log.log_event(
                "modbus_connection_close",
                peer=peer_ref,
            )

    def _recv_exact(self, length: int) -> bytes | None:
        buffer = b""
        while len(buffer) < length:
            chunk = self.request.recv(length - len(buffer))
            if not chunk:
                return None
            buffer += chunk
        return buffer

    def process_pdu(
        self,
        peer_ref: str,
        unit_id: int,
        function_code: int,
        pdu: bytes,
    ) -> bytes:
        if function_code in (1, 2):
            return self._read_bits(
                peer_ref,
                unit_id,
                function_code,
                pdu,
            )
        if function_code in (3, 4):
            return self._read_registers(
                peer_ref,
                unit_id,
                function_code,
                pdu,
            )
        if function_code == 5:
            return self._write_single_coil(peer_ref, unit_id, pdu)
        if function_code == 6:
            return self._write_single_register(peer_ref, unit_id, pdu)
        if function_code == 8:
            if len(pdu) < 5:
                return exception_pdu(8, 3)
            return pdu
        if function_code == 15:
            return self._write_multiple_coils(peer_ref, unit_id, pdu)
        if function_code == 16:
            return self._write_multiple_registers(peer_ref, unit_id, pdu)
        if function_code == 17:
            return self._report_server_id(peer_ref, unit_id)
        if function_code == 43:
            return self._read_device_id(peer_ref, unit_id, pdu)
        event_log.log_event(
            "modbus_unsupported_function",
            peer=peer_ref,
            fc=function_code,
        )
        return exception_pdu(function_code, 1)

    def _read_bits(
        self,
        peer_ref: str,
        unit_id: int,
        function_code: int,
        pdu: bytes,
    ) -> bytes:
        if len(pdu) != 5:
            return exception_pdu(function_code, 3)
        start, quantity = struct.unpack(">HH", pdu[1:5])
        event_log.log_event(
            "modbus_read_bits",
            peer=peer_ref,
            fc=function_code,
            unit_id=unit_id,
            start=start,
            qty=quantity,
        )
        if quantity < 1 or quantity > 2000:
            return exception_pdu(function_code, 3)
        if start + quantity - 1 > config.U16_MAX:
            return exception_pdu(function_code, 2)
        byte_count = (quantity + 7) // 8
        return bytes([function_code, byte_count]) + bytes(byte_count)

    def _read_registers(
        self,
        peer_ref: str,
        unit_id: int,
        function_code: int,
        pdu: bytes,
    ) -> bytes:
        if len(pdu) != 5:
            return exception_pdu(function_code, 3)
        start, quantity = struct.unpack(">HH", pdu[1:5])
        event_log.log_event(
            "modbus_read_registers",
            peer=peer_ref,
            fc=function_code,
            unit_id=unit_id,
            start=start,
            qty=quantity,
            end=start + quantity - 1,
        )
        if quantity < 1 or quantity > 125:
            return exception_pdu(function_code, 3)
        if start + quantity - 1 > config.U16_MAX:
            return exception_pdu(function_code, 2)
        if function_code == 4:
            values = registers.read_input_registers(start, quantity)
        else:
            values = registers.read_holding_registers(start, quantity)
        data = b"".join(struct.pack(">H", value) for value in values)
        return bytes([function_code, len(data)]) + data

    def _write_single_coil(
        self,
        peer_ref: str,
        unit_id: int,
        pdu: bytes,
    ) -> bytes:
        if len(pdu) != 5:
            return exception_pdu(5, 3)
        address, value = struct.unpack(">HH", pdu[1:5])
        if value not in (0x0000, 0xFF00):
            return exception_pdu(5, 3)
        event_log.log_event(
            "modbus_write_single_coil",
            peer=peer_ref,
            unit_id=unit_id,
            addr=address,
            value=value,
        )
        return pdu

    def _write_single_register(
        self,
        peer_ref: str,
        unit_id: int,
        pdu: bytes,
    ) -> bytes:
        if len(pdu) != 5:
            return exception_pdu(6, 3)
        address, value = struct.unpack(">HH", pdu[1:5])
        mirror_enabled = bool(config.OPTIONS.get("mirror_writes", False))
        mirrored_count = 0
        profile_blocked_count = 0
        if mirror_enabled:
            mirrored_count, profile_blocked_count = registers.write_holding_registers(
                address, [value]
            )
        event_log.log_event(
            "modbus_write_single_register",
            peer=peer_ref,
            unit_id=unit_id,
            addr=address,
            value=value,
            mirror_enabled=mirror_enabled,
            mirrored=mirrored_count == 1,
            profile_blocked=profile_blocked_count == 1,
        )
        return pdu

    def _write_multiple_coils(
        self,
        peer_ref: str,
        unit_id: int,
        pdu: bytes,
    ) -> bytes:
        if len(pdu) < 6:
            return exception_pdu(15, 3)
        address, quantity, byte_count = struct.unpack(">HHB", pdu[1:6])
        expected_bytes = (quantity + 7) // 8
        if (
            quantity < 1
            or quantity > 1968
            or byte_count != expected_bytes
            or len(pdu) != 6 + byte_count
        ):
            return exception_pdu(15, 3)
        if address + quantity - 1 > config.U16_MAX:
            return exception_pdu(15, 2)
        event_log.log_event(
            "modbus_write_multiple_coils",
            peer=peer_ref,
            unit_id=unit_id,
            addr=address,
            qty=quantity,
        )
        return bytes([15]) + struct.pack(">HH", address, quantity)

    def _write_multiple_registers(
        self,
        peer_ref: str,
        unit_id: int,
        pdu: bytes,
    ) -> bytes:
        if len(pdu) < 6:
            return exception_pdu(16, 3)
        address, quantity, byte_count = struct.unpack(">HHB", pdu[1:6])
        if (
            quantity < 1
            or quantity > 123
            or byte_count != quantity * 2
            or len(pdu) != 6 + byte_count
        ):
            return exception_pdu(16, 3)
        if address + quantity - 1 > config.U16_MAX:
            return exception_pdu(16, 2)
        values = [
            struct.unpack(">H", pdu[offset : offset + 2])[0]
            for offset in range(6, 6 + byte_count, 2)
        ]
        mirror_enabled = bool(config.OPTIONS.get("mirror_writes", False))
        mirrored_count = 0
        profile_blocked_count = 0
        if mirror_enabled:
            mirrored_count, profile_blocked_count = registers.write_holding_registers(
                address, values
            )
        event_log.log_event(
            "modbus_write_multiple_registers",
            peer=peer_ref,
            unit_id=unit_id,
            addr=address,
            qty=quantity,
            mirror_enabled=mirror_enabled,
            mirrored_count=mirrored_count,
            profile_blocked_count=profile_blocked_count,
        )
        return bytes([16]) + struct.pack(">HH", address, quantity)

    def _report_server_id(self, peer_ref: str, unit_id: int) -> bytes:
        vendor = str(config.OPTIONS.get("fake_vendor", "Ginlong"))
        model = str(config.OPTIONS.get("fake_inverter_model", "Solis S6-EH1P"))
        text = f"{vendor} Solis {model}".encode("ascii", "ignore")[:240]
        payload = b"\x01\xff" + text
        event_log.log_event(
            "modbus_report_server_id",
            peer=peer_ref,
            unit_id=unit_id,
        )
        return bytes([17, len(payload)]) + payload

    def _read_device_id(
        self,
        peer_ref: str,
        unit_id: int,
        pdu: bytes,
    ) -> bytes:
        if len(pdu) != 4 or pdu[1] != 0x0E:
            return exception_pdu(43, 1)
        code = pdu[2]
        object_id = pdu[3]
        if code not in (1, 2, 3, 4):
            return exception_pdu(43, 3)
        objects = device_id_objects()
        if code == 4:
            candidates = [
                (candidate_id, value)
                for candidate_id, value in objects
                if candidate_id == object_id
            ]
        else:
            candidates = [
                (candidate_id, value)
                for candidate_id, value in objects
                if candidate_id >= object_id
            ]

        # The response header is seven bytes. Add complete objects until the
        # PDU limit is reached, then advertise the next object for pagination.
        body = bytearray([0x2B, 0x0E, code, 0x03, 0x00, 0x00, 0x00])
        selected: list[tuple[int, bytes]] = []
        more_follows = 0x00
        next_object_id = 0x00
        for candidate_id, value in candidates:
            value = value[:240]
            if len(body) + 2 + len(value) > config.MAX_MODBUS_PDU_LENGTH:
                more_follows = 0xFF
                next_object_id = candidate_id
                break
            body.extend([candidate_id, len(value)])
            body.extend(value)
            selected.append((candidate_id, value))
        body[4] = more_follows
        body[5] = next_object_id
        body[6] = len(selected)
        event_log.log_event(
            "modbus_read_device_id",
            peer=peer_ref,
            unit_id=unit_id,
            objects=[candidate_id for candidate_id, _ in selected],
        )
        return bytes(body)
