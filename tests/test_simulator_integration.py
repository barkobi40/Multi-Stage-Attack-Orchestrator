"""Integration tests against the real, compiled C device simulator."""

from __future__ import annotations

import socket
import struct

import pytest

from python_framework.client import DeviceClient, DeviceConnectionError, MsgType, StatusCode
from python_framework.extractor import DataExtractor
from python_framework.models import Attack, AttackStage
from python_framework.orchestrator import AttackOrchestrator, StageStatus


def _stage(stage_id: int) -> AttackStage:
    return AttackStage(stage_id=stage_id, stage_name=f"stage-{stage_id}")


class TestDeviceInfoAndFileRead:
    """Basic request/response round trips against a plain simulator."""

    def test_get_device_info_matches_simulator_defaults(self, simulator):
        with DeviceClient(port=simulator.port) as client:
            device = client.get_device_info()

        assert device.ios_major == 16
        assert device.ios_minor == 5
        assert device.model == "iPhone14,2"
        assert device.battery_level == 85

    def test_read_device_file_returns_dummy_payload(self, simulator):
        with DeviceClient(port=simulator.port) as client:
            data = client.read_device_file("/var/mobile/whatever.db")

        assert data == b"EXTRACTED_DEVICE_DATA_PAYLOAD"


class TestSuccessfulAttackRun:
    """End-to-end multi-stage attack execution and data extraction."""

    def test_multi_stage_attack_all_succeed(self, simulator):
        plan = Attack(
            stages=[_stage(1), _stage(2), _stage(3)],
            min_ios_version=(10, 0),
            max_ios_version=(20, 0),
        )

        with DeviceClient(port=simulator.port) as client:
            device = client.get_device_info()
            orchestrator = AttackOrchestrator(client)
            selected = orchestrator.select_plan(device, [plan])
            result = orchestrator.run(selected, device=device)

        assert selected is plan
        assert result.succeeded is True
        assert [r.status for r in result.stage_results] == [StageStatus.SUCCESS] * 3

    def test_extraction_after_successful_run(self, simulator, tmp_path):
        plan = Attack(stages=[_stage(1)])

        with DeviceClient(port=simulator.port) as client:
            result = AttackOrchestrator(client).run(plan)
            assert result.succeeded is True

            extractor = DataExtractor(client, tmp_path)
            dest = extractor.extract_file("/var/mobile/data.db", local_name="loot.bin")

        assert dest == tmp_path / "loot.bin"
        assert dest.read_bytes() == b"EXTRACTED_DEVICE_DATA_PAYLOAD"


class TestProtocolFraming:
    """Raw wire-protocol edge cases, bypassing DeviceClient's own guards."""

    def test_oversized_read_file_path_does_not_desync_the_connection(self, simulator):
        """An over-long MSG_READ_FILE path must not desync later messages."""
        oversized_path = b"a" * 300  # exceeds the 255-byte path buffer

        with socket.create_connection(("localhost", simulator.port), timeout=5.0) as sock:
            header = struct.pack(">BI", MsgType.READ_FILE, len(oversized_path))
            sock.sendall(header + oversized_path)

            resp_header = sock.recv(8, socket.MSG_WAITALL)
            status, data_len = struct.unpack(">II", resp_header)
            assert status == StatusCode.OK
            data = sock.recv(data_len, socket.MSG_WAITALL)
            assert data == b"EXTRACTED_DEVICE_DATA_PAYLOAD"

            # Confirms the connection is still framed correctly.
            sock.sendall(struct.pack(">BI", MsgType.GET_INFO, 0))
            info_header = sock.recv(8, socket.MSG_WAITALL)
            info_status, info_len = struct.unpack(">II", info_header)
            assert info_status == StatusCode.OK
            assert len(sock.recv(info_len, socket.MSG_WAITALL)) == info_len

    def test_malformed_execute_stage_payload_returns_error_and_stays_in_sync(self, simulator):
        """A bad EXECUTE_STAGE payload_len should error, not desync the connection."""
        bogus_payload = b"\x01\x02\x03"  # payload_len=3, not the expected 1

        with socket.create_connection(("localhost", simulator.port), timeout=5.0) as sock:
            header = struct.pack(">BI", MsgType.EXECUTE_STAGE, len(bogus_payload))
            sock.sendall(header + bogus_payload)

            resp_header = sock.recv(8, socket.MSG_WAITALL)
            status, data_len = struct.unpack(">II", resp_header)
            assert status == StatusCode.ERROR
            assert data_len == 0

            sock.sendall(struct.pack(">BI", MsgType.GET_INFO, 0))
            info_header = sock.recv(8, socket.MSG_WAITALL)
            info_status, info_len = struct.unpack(">II", info_header)
            assert info_status == StatusCode.OK
            assert len(sock.recv(info_len, socket.MSG_WAITALL)) == info_len


class TestStageFailureFaultInjection:
    """Test simulator fault injection for stage failures."""

    def test_orchestrator_stops_at_failed_stage(self, make_simulator):
        sim = make_simulator(["--fail-stage", "2"])
        plan = Attack(stages=[_stage(1), _stage(2), _stage(3)])

        with DeviceClient(port=sim.port) as client:
            result = AttackOrchestrator(client).run(plan)

        statuses = [r.status for r in result.stage_results]
        assert statuses == [StageStatus.SUCCESS, StageStatus.FAILED, StageStatus.SKIPPED]
        assert result.succeeded is False
        assert result.failed_stage.stage.stage_id == 2

    def test_execute_stage_returns_false_directly(self, make_simulator):
        sim = make_simulator(["--fail-stage", "1"])
        with DeviceClient(port=sim.port) as client:
            assert client.execute_stage(1) is False


class TestConnectionDropFaultInjection:
    """Test simulator fault injection for dropped connections."""

    def test_execute_stage_raises_connection_error(self, make_simulator):
        sim = make_simulator(["--drop-stage", "2"])
        with DeviceClient(port=sim.port) as client:
            assert client.execute_stage(1) is True
            with pytest.raises(DeviceConnectionError):
                client.execute_stage(2)

    def test_orchestrator_marks_dropped_stage_and_stops(self, make_simulator):
        sim = make_simulator(["--drop-stage", "2"])
        plan = Attack(stages=[_stage(1), _stage(2), _stage(3)])

        with DeviceClient(port=sim.port) as client:
            result = AttackOrchestrator(client).run(plan)

        statuses = [r.status for r in result.stage_results]
        assert statuses == [StageStatus.SUCCESS, StageStatus.DROPPED, StageStatus.SKIPPED]
        assert result.succeeded is False