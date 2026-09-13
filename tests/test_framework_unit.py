"""Unit tests using in-memory fakes/mocks """

from __future__ import annotations

import struct

import pytest

from python_framework.client import (
    DeviceClient,
    DeviceConnectionError,
    DeviceProtocolError,
    MsgType,
    StatusCode,
)
from python_framework.extractor import DataExtractor, ExtractionError
from python_framework.models import Attack, AttackStage, DeviceState
from python_framework.orchestrator import (
    AttackOrchestrator,
    AttackResult,
    NoCompatiblePlanError,
    OrchestratorError,
    StageStatus,
)


def _stage(stage_id: int) -> AttackStage:
    return AttackStage(stage_id=stage_id, stage_name=f"stage-{stage_id}")


def _device(major: int = 16, minor: int = 5) -> DeviceState:
    return DeviceState(ios_major=major, ios_minor=minor, model="iPhone14,2", battery_level=80)


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------


class TestDeviceState:
    def test_valid_construction_exposes_version_helpers(self):
        state = DeviceState(ios_major=16, ios_minor=5, model="iPhone14,2", battery_level=85)
        assert state.ios_version == (16, 5)
        assert state.ios_version_string == "16.5"

    @pytest.mark.parametrize("battery_level", [-1, 101])
    def test_rejects_out_of_range_battery_level(self, battery_level):
        with pytest.raises(ValueError):
            DeviceState(ios_major=16, ios_minor=5, model="x", battery_level=battery_level)


class TestAttackStage:
    @pytest.mark.parametrize("stage_id", [-1, 256])
    def test_rejects_out_of_range_stage_id(self, stage_id):
        with pytest.raises(ValueError):
            AttackStage(stage_id=stage_id, stage_name="x")

    def test_rejects_empty_name(self):
        with pytest.raises(ValueError):
            AttackStage(stage_id=1, stage_name="")


class TestAttack:
    def test_rejects_duplicate_stage_ids(self):
        with pytest.raises(ValueError):
            Attack(stages=[_stage(1), _stage(1)])

    def test_rejects_inverted_version_bounds(self):
        with pytest.raises(ValueError):
            Attack(min_ios_version=(17, 0), max_ios_version=(16, 0))

    @pytest.mark.parametrize(
        "device_version, expected_compatible",
        [
            ((15, 9), False),
            ((16, 0), True),
            ((17, 5), True),
            ((18, 0), True),
            ((18, 1), False),
        ],
    )
    def test_is_compatible_boundaries(self, device_version, expected_compatible):
        attack = Attack(
            stages=[_stage(1)], min_ios_version=(16, 0), max_ios_version=(18, 0)
        )
        device = _device(*device_version)
        assert attack.is_compatible(device) is expected_compatible

    def test_stage_ids_preserves_declared_order(self):
        attack = Attack(stages=[_stage(3), _stage(1), _stage(2)])
        assert attack.stage_ids() == [3, 1, 2]

    @pytest.mark.parametrize("min_battery_level", [-1, 101])
    def test_rejects_out_of_range_min_battery_level(self, min_battery_level):
        with pytest.raises(ValueError):
            Attack(stages=[_stage(1)], min_battery_level=min_battery_level)

    @pytest.mark.parametrize("success_probability", [-0.1, 1.1])
    def test_rejects_out_of_range_success_probability(self, success_probability):
        with pytest.raises(ValueError):
            Attack(stages=[_stage(1)], success_probability=success_probability)

    def test_is_compatible_rejects_low_battery(self):
        attack = Attack(stages=[_stage(1)], min_battery_level=50)
        low_battery = DeviceState(
            ios_major=16, ios_minor=5, model="iPhone14,2", battery_level=20
        )
        assert attack.is_compatible(low_battery) is False

    def test_is_compatible_accepts_sufficient_battery(self):
        attack = Attack(stages=[_stage(1)], min_battery_level=50)
        device = _device()
        assert attack.is_compatible(device) is True

    def test_is_compatible_enforces_model_allowlist(self):
        attack = Attack(stages=[_stage(1)], compatible_models=("iPhone15,2",))
        assert attack.is_compatible(_device()) is False

        matching_model = DeviceState(
            ios_major=16, ios_minor=5, model="iPhone15,2", battery_level=80
        )
        assert attack.is_compatible(matching_model) is True

    def test_is_compatible_allows_any_model_by_default(self):
        attack = Attack(stages=[_stage(1)])
        assert attack.is_compatible(_device()) is True


# ---------------------------------------------------------------------------
# orchestrator.py
# ---------------------------------------------------------------------------


class FakeDeviceClient:
    """Stands in for DeviceClient.execute_stage in orchestrator tests."""

    def __init__(self, outcomes: dict[int, bool | Exception]) -> None:
        self._outcomes = outcomes
        self.calls: list[int] = []

    def execute_stage(self, stage_id: int) -> bool:
        self.calls.append(stage_id)
        outcome = self._outcomes[stage_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestSelectPlan:
    def test_selects_first_compatible_plan(self):
        device = _device(16, 5)
        too_old = Attack(stages=[_stage(1)], min_ios_version=(10, 0), max_ios_version=(12, 0))
        matching = Attack(stages=[_stage(1)], min_ios_version=(14, 0), max_ios_version=(18, 0))
        orchestrator = AttackOrchestrator(FakeDeviceClient({}))

        selected = orchestrator.select_plan(device, [too_old, matching])

        assert selected is matching

    def test_raises_when_no_plan_matches(self):
        device = _device(9, 0)
        plan = Attack(stages=[_stage(1)], min_ios_version=(14, 0), max_ios_version=(18, 0))
        orchestrator = AttackOrchestrator(FakeDeviceClient({}))

        with pytest.raises(NoCompatiblePlanError):
            orchestrator.select_plan(device, [plan])

    def test_selects_highest_probability_among_viable_plans(self):
        device = _device()
        risky = Attack(stages=[_stage(1)], success_probability=0.3)
        safest = Attack(stages=[_stage(1)], success_probability=0.9)
        moderate = Attack(stages=[_stage(1)], success_probability=0.6)
        orchestrator = AttackOrchestrator(FakeDeviceClient({}))

        selected = orchestrator.select_plan(device, [risky, safest, moderate])

        assert selected is safest

    def test_excludes_plans_the_device_battery_cannot_support(self):
        device_low_battery = DeviceState(
            ios_major=16, ios_minor=5, model="iPhone14,2", battery_level=10
        )
        needs_battery = Attack(
            stages=[_stage(1)], min_battery_level=50, success_probability=0.9
        )
        low_power_ok = Attack(
            stages=[_stage(1)], min_battery_level=0, success_probability=0.5
        )
        orchestrator = AttackOrchestrator(FakeDeviceClient({}))

        selected = orchestrator.select_plan(
            device_low_battery, [needs_battery, low_power_ok]
        )

        assert selected is low_power_ok

    def test_excludes_plans_the_device_model_does_not_match(self):
        device = _device()
        wrong_model = Attack(
            stages=[_stage(1)], compatible_models=("iPhone15,2",), success_probability=0.9
        )
        any_model = Attack(stages=[_stage(1)], success_probability=0.5)
        orchestrator = AttackOrchestrator(FakeDeviceClient({}))

        selected = orchestrator.select_plan(device, [wrong_model, any_model])

        assert selected is any_model


class TestRun:
    def test_all_stages_succeed(self):
        plan = Attack(stages=[_stage(1), _stage(2), _stage(3)])
        client = FakeDeviceClient({1: True, 2: True, 3: True})

        result = AttackOrchestrator(client).run(plan)

        assert isinstance(result, AttackResult)
        assert result.succeeded is True
        assert [r.status for r in result.stage_results] == [StageStatus.SUCCESS] * 3
        assert client.calls == [1, 2, 3]

    def test_stage_failure_stops_remaining_stages(self):
        plan = Attack(stages=[_stage(1), _stage(2), _stage(3)])
        client = FakeDeviceClient({1: True, 2: False, 3: True})

        result = AttackOrchestrator(client).run(plan)

        statuses = [r.status for r in result.stage_results]
        assert statuses == [StageStatus.SUCCESS, StageStatus.FAILED, StageStatus.SKIPPED]
        assert result.succeeded is False
        assert result.failed_stage.stage.stage_id == 2
        assert client.calls == [1, 2]

    def test_dropped_connection_stops_remaining_stages(self):
        plan = Attack(stages=[_stage(1), _stage(2)])
        client = FakeDeviceClient({1: DeviceConnectionError("dropped"), 2: True})

        result = AttackOrchestrator(client).run(plan)

        statuses = [r.status for r in result.stage_results]
        assert statuses == [StageStatus.DROPPED, StageStatus.SKIPPED]
        assert client.calls == [1]

    def test_protocol_error_marks_stage_failed(self):
        plan = Attack(stages=[_stage(1)])
        client = FakeDeviceClient({1: DeviceProtocolError("bad status")})

        result = AttackOrchestrator(client).run(plan)

        assert result.stage_results[0].status == StageStatus.FAILED
        assert "bad status" in result.stage_results[0].error

    def test_run_rejects_incompatible_device(self):
        plan = Attack(stages=[_stage(1)], min_ios_version=(14, 0), max_ios_version=(15, 0))
        client = FakeDeviceClient({1: True})
        incompatible_device = _device(16, 5)

        with pytest.raises(OrchestratorError):
            AttackOrchestrator(client).run(plan, device=incompatible_device)

    def test_run_rejects_device_with_insufficient_battery(self):
        plan = Attack(stages=[_stage(1)], min_battery_level=90)
        client = FakeDeviceClient({1: True})

        with pytest.raises(OrchestratorError):
            AttackOrchestrator(client).run(plan, device=_device())

    def test_run_rejects_device_with_unsupported_model(self):
        plan = Attack(stages=[_stage(1)], compatible_models=("iPhone15,2",))
        client = FakeDeviceClient({1: True})

        with pytest.raises(OrchestratorError):
            AttackOrchestrator(client).run(plan, device=_device())


# ---------------------------------------------------------------------------
# extractor.py
# ---------------------------------------------------------------------------


class FakeReadClient:
    """Stands in for DeviceClient.read_device_file in extractor tests."""

    def __init__(self, files: dict[str, bytes | Exception]) -> None:
        self._files = files

    def read_device_file(self, path: str) -> bytes:
        outcome = self._files[path]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestDataExtractor:
    def test_extract_file_writes_bytes_to_disk(self, tmp_path):
        client = FakeReadClient({"/var/mobile/secret.db": b"top-secret-bytes"})
        extractor = DataExtractor(client, tmp_path)

        dest = extractor.extract_file("/var/mobile/secret.db")

        assert dest == tmp_path / "secret.db"
        assert dest.read_bytes() == b"top-secret-bytes"

    def test_extract_file_raises_extraction_error_on_device_failure(self, tmp_path):
        client = FakeReadClient({"/missing": DeviceProtocolError("not found")})
        extractor = DataExtractor(client, tmp_path)

        with pytest.raises(ExtractionError):
            extractor.extract_file("/missing")

    def test_extract_files_skips_failures_and_keeps_successes(self, tmp_path):
        client = FakeReadClient(
            {"/ok": b"data", "/bad": DeviceConnectionError("dropped mid-read")}
        )
        extractor = DataExtractor(client, tmp_path)

        results = extractor.extract_files(["/ok", "/bad"])

        assert list(results.keys()) == ["/ok"]
        assert results["/ok"].read_bytes() == b"data"


# ---------------------------------------------------------------------------
# client.py
# ---------------------------------------------------------------------------


class FakeSocket:
    """Minimal in-memory stand-in for a TCP socket."""

    def __init__(self, recv_buffer: bytes = b"") -> None:
        self.sent = bytearray()
        self._recv_buffer = bytearray(recv_buffer)

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def recv(self, n: int) -> bytes:
        chunk = bytes(self._recv_buffer[:n])
        del self._recv_buffer[:n]
        return chunk

    def close(self) -> None:
        pass


@pytest.fixture
def client_with_socket(monkeypatch):
    """Factory fixture for DeviceClient using a FakeSocket."""

    def _make(recv_buffer: bytes = b"") -> tuple[DeviceClient, FakeSocket]:
        fake_socket = FakeSocket(recv_buffer)
        monkeypatch.setattr(
            "python_framework.client.socket.create_connection",
            lambda *args, **kwargs: fake_socket,
        )
        client = DeviceClient(host="fake-host", port=0)
        return client, fake_socket

    return _make


class TestDeviceClientFraming:
    def test_get_device_info_parses_response(self, client_with_socket):
        info_payload = struct.pack(">BHH32s", 90, 16, 5, b"iPhone14,2")
        response = struct.pack(">II", StatusCode.OK, len(info_payload)) + info_payload
        client, sock = client_with_socket(response)

        state = client.get_device_info()

        assert state.battery_level == 90
        assert state.ios_major == 16
        assert state.ios_minor == 5
        assert state.model == "iPhone14,2"
        assert bytes(sock.sent) == struct.pack(">BI", MsgType.GET_INFO, 0)

    def test_execute_stage_returns_true_on_ok(self, client_with_socket):
        response = struct.pack(">II", StatusCode.OK, 0)
        client, sock = client_with_socket(response)

        assert client.execute_stage(3) is True
        expected = struct.pack(">BI", MsgType.EXECUTE_STAGE, 1) + struct.pack(">B", 3)
        assert bytes(sock.sent) == expected

    def test_execute_stage_returns_false_on_stage_failed(self, client_with_socket):
        response = struct.pack(">II", StatusCode.STAGE_FAILED, 0)
        client, _sock = client_with_socket(response)

        assert client.execute_stage(1) is False

    def test_execute_stage_rejects_out_of_range_id(self, client_with_socket):
        client, _sock = client_with_socket(b"")
        with pytest.raises(ValueError):
            client.execute_stage(256)

    def test_read_device_file_returns_bytes(self, client_with_socket):
        data = b"EXTRACTED_DEVICE_DATA_PAYLOAD"
        response = struct.pack(">II", StatusCode.OK, len(data)) + data
        client, _sock = client_with_socket(response)

        assert client.read_device_file("/some/path") == data

    def test_read_device_file_raises_on_file_not_found(self, client_with_socket):
        response = struct.pack(">II", StatusCode.FILE_NOT_FOUND, 0)
        client, _sock = client_with_socket(response)

        with pytest.raises(DeviceProtocolError):
            client.read_device_file("/missing")

    def test_read_device_file_rejects_path_too_long(self, client_with_socket):
        client, _sock = client_with_socket(b"")
        with pytest.raises(ValueError):
            client.read_device_file("a" * 300)

    def test_truncated_response_raises_connection_error(self, client_with_socket):
        client, _sock = client_with_socket(b"\x00\x00\x00\x00")
        with pytest.raises(DeviceConnectionError):
            client.execute_stage(1)

    def test_unknown_status_code_raises_protocol_error(self, client_with_socket):
        response = struct.pack(">II", 123, 0)
        client, _sock = client_with_socket(response)

        with pytest.raises(DeviceProtocolError):
            client.execute_stage(1)

    def test_operations_after_close_raise_connection_error(self, client_with_socket):
        client, _sock = client_with_socket(b"")
        client.close()

        with pytest.raises(DeviceConnectionError):
            client.execute_stage(1)

    def test_context_manager_closes_on_exit(self, client_with_socket):
        client, _sock = client_with_socket(b"")

        with client:
            pass

        with pytest.raises(DeviceConnectionError):
            client.execute_stage(1)