"""Integration tests against the real, compiled C device simulator."""

from __future__ import annotations

import pytest

from python_framework.client import DeviceClient, DeviceConnectionError
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