"""TCP client for the C device simulator.

Handles the binary communication with the C simulator using big-endian
byte order and exact struct packing.
"""

from __future__ import annotations

import socket
import struct
from enum import IntEnum
from types import TracebackType

from .models import DeviceState

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8888
DEFAULT_TIMEOUT = 5.0

# Maximum path length supported by the C server buffer
MAX_PATH_LEN = 255


class MsgType(IntEnum):
    """Message type codes matching the C protocol."""

    GET_INFO = 0x01
    EXECUTE_STAGE = 0x02
    READ_FILE = 0x03
    RESPONSE = 0x04


class StatusCode(IntEnum):
    """Response status codes returned by the device."""

    OK = 0
    STAGE_FAILED = 1
    FILE_NOT_FOUND = 2
    ERROR = 99


class DeviceClientError(Exception):
    """Base exception for client errors."""


class DeviceConnectionError(DeviceClientError):
    """Raised when connection or socket operations fail."""


class DeviceProtocolError(DeviceClientError):
    """Raised when response framing or status is invalid."""


class DeviceClient:
    """TCP client communicating with the device simulator."""

    _HEADER_FORMAT = ">BI"
    _RESPONSE_HEADER_FORMAT = ">II"
    _DEVICE_INFO_FORMAT = ">BHH32s"
    _EXECUTE_STAGE_FORMAT = ">B"

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Connects to the device simulator."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._connect()

    def _connect(self) -> None:
        try:
            self._sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
        except OSError as exc:
            raise DeviceConnectionError(
                f"Could not connect to device simulator at {self.host}:{self.port}: {exc}"
            ) from exc

    def _require_socket(self) -> socket.socket:
        if self._sock is None:
            raise DeviceConnectionError("DeviceClient is closed")
        return self._sock

    def close(self) -> None:
        """Closes the socket connection."""
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> DeviceClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def _send_message(self, msg_type: MsgType, payload: bytes = b"") -> None:
        """Sends a message header and payload to the server."""
        sock = self._require_socket()
        header = struct.pack(self._HEADER_FORMAT, int(msg_type), len(payload))
        try:
            sock.sendall(header + payload)
        except socket.timeout as exc:
            raise DeviceConnectionError("Timed out sending message") from exc
        except OSError as exc:
            raise DeviceConnectionError(f"Socket error while sending: {exc}") from exc

    def _recv_exact(self, size: int) -> bytes:
        """Reads an exact number of bytes from the socket."""
        if size == 0:
            return b""
        sock = self._require_socket()
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = sock.recv(size - len(chunks))
            except socket.timeout as exc:
                raise DeviceConnectionError(
                    f"Timed out waiting for {size} bytes from device"
                ) from exc
            except OSError as exc:
                raise DeviceConnectionError(f"Socket error while reading: {exc}") from exc
            if not chunk:
                raise DeviceConnectionError(
                    "Connection closed by device before expected data was received"
                )
            chunks.extend(chunk)
        return bytes(chunks)

    def _recv_response_header(self) -> tuple[StatusCode, int]:
        """Reads and parses the response header."""
        raw = self._recv_exact(struct.calcsize(self._RESPONSE_HEADER_FORMAT))
        status, data_len = struct.unpack(self._RESPONSE_HEADER_FORMAT, raw)
        try:
            status_code = StatusCode(status)
        except ValueError as exc:
            raise DeviceProtocolError(
                f"Unknown status code {status} in device response"
            ) from exc
        return status_code, data_len

    def get_device_info(self) -> DeviceState:
        """Requests and retrieves device status information."""
        self._send_message(MsgType.GET_INFO)
        status, data_len = self._recv_response_header()
        if status != StatusCode.OK:
            raise DeviceProtocolError(f"Device returned {status.name} for get_device_info")

        expected_len = struct.calcsize(self._DEVICE_INFO_FORMAT)
        if data_len != expected_len:
            raise DeviceProtocolError(
                f"Expected a {expected_len}-byte device info payload, got {data_len}"
            )

        payload = self._recv_exact(data_len)
        battery_level, ios_major, ios_minor, raw_model = struct.unpack(
            self._DEVICE_INFO_FORMAT, payload
        )
        model = raw_model.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        return DeviceState(
            ios_major=ios_major,
            ios_minor=ios_minor,
            model=model,
            battery_level=battery_level,
        )

    def execute_stage(self, stage_id: int) -> bool:
        """Requests execution of a specific stage."""
        if not 0 <= stage_id <= 0xFF:
            raise ValueError(f"stage_id must be 0-255, got {stage_id}")

        payload = struct.pack(self._EXECUTE_STAGE_FORMAT, stage_id)
        self._send_message(MsgType.EXECUTE_STAGE, payload)
        status, _ = self._recv_response_header()

        if status == StatusCode.OK:
            return True
        if status == StatusCode.STAGE_FAILED:
            return False
        raise DeviceProtocolError(
            f"Unexpected status {status.name} executing stage {stage_id}"
        )

    def read_device_file(self, path: str) -> bytes:
        """Requests a file from the device path."""
        encoded_path = path.encode("utf-8")
        if len(encoded_path) > MAX_PATH_LEN:
            raise ValueError(
                f"path must encode to at most {MAX_PATH_LEN} bytes, got {len(encoded_path)}"
            )

        self._send_message(MsgType.READ_FILE, encoded_path)
        status, data_len = self._recv_response_header()
        if status != StatusCode.OK:
            raise DeviceProtocolError(
                f"Device returned {status.name} for read_device_file({path!r})"
            )
        return self._recv_exact(data_len)