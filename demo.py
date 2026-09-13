#!/usr/bin/env python3
"""End-to-end demo: build the simulator, run a multi-stage attack, extract a file.

Usage:
    python3 demo.py
    make demo
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from python_framework.client import DeviceClient, DeviceConnectionError, DeviceProtocolError
from python_framework.extractor import DataExtractor
from python_framework.models import Attack, AttackStage
from python_framework.orchestrator import AttackOrchestrator, OrchestratorError

REPO_ROOT = Path(__file__).resolve().parent
SIM_DIR = REPO_ROOT / "c_simulator"
SIM_BINARY = SIM_DIR / "device_sim"
PORT = 8888


def build_simulator() -> None:
    """Force a clean rebuild so the demo never runs against a stale binary."""
    print("==> Building device_sim ...")
    subprocess.run(["make", "clean"], cwd=SIM_DIR, check=True, capture_output=True)
    subprocess.run(["make"], cwd=SIM_DIR, check=True)


def wait_for_port(port: int, timeout: float = 3.0) -> None:
    """Blocks until device_sim accepts TCP connections, or raises."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"device_sim never started listening on port {port}")


def main() -> int:
    build_simulator()

    print(f"==> Starting device_sim on port {PORT} ...")
    process = subprocess.Popen([str(SIM_BINARY), "--port", str(PORT)])
    try:
        wait_for_port(PORT)

        with DeviceClient(port=PORT) as client:
            device = client.get_device_info()
            print(
                f"==> Connected to {device.model} "
                f"(iOS {device.ios_version_string}, battery {device.battery_level}%)"
            )

            candidate_plans = [
                Attack(
                    stages=[
                        AttackStage(1, "gain-access", "Establish initial foothold"),
                        AttackStage(2, "escalate", "Escalate privileges"),
                        AttackStage(3, "extract", "Stage data for extraction"),
                    ],
                    min_ios_version=(10, 0),
                    max_ios_version=(20, 0),
                    min_battery_level=50,
                    success_probability=0.6,
                ),
                Attack(
                    stages=[
                        AttackStage(1, "gain-access", "Establish initial foothold"),
                        AttackStage(2, "escalate", "Escalate privileges"),
                        AttackStage(3, "extract", "Stage data for extraction"),
                    ],
                    min_ios_version=(10, 0),
                    max_ios_version=(20, 0),
                    min_battery_level=10,
                    success_probability=0.9,
                ),
                Attack(
                    stages=[AttackStage(1, "gain-access", "Establish initial foothold")],
                    min_ios_version=(10, 0),
                    max_ios_version=(20, 0),
                    compatible_models=("iPhoneX,1",),  # never matches this device
                    success_probability=1.0,
                ),
            ]

            orchestrator = AttackOrchestrator(client)
            selected = orchestrator.select_plan(device, candidate_plans)
            print(
                f"==> Selected plan with {len(selected.stages)} stages "
                f"(success_probability={selected.success_probability}, "
                f"out of {len(candidate_plans)} candidates)"
            )

            result = orchestrator.run(selected, device=device)
            for stage_result in result.stage_results:
                print(
                    f"    stage {stage_result.stage.stage_id} "
                    f"({stage_result.stage.stage_name}): {stage_result.status.value}"
                )

            if not result.succeeded:
                print("==> Attack run did not fully succeed; skipping extraction.")
                return 1

            with tempfile.TemporaryDirectory() as tmp_dir:
                extractor = DataExtractor(client, tmp_dir)
                dest = extractor.extract_file(
                    "/var/mobile/demo_data.db", local_name="demo_loot.bin"
                )
                print(f"==> Extracted {dest.stat().st_size} bytes to {dest}")

        print("==> Demo complete.")
        return 0

    except (DeviceConnectionError, DeviceProtocolError, OrchestratorError) as exc:
        print(f"==> Demo failed: {exc}", file=sys.stderr)
        return 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    sys.exit(main())
