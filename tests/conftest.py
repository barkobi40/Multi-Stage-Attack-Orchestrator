"""Shared pytest fixtures for launching and managing the `device_sim` C subprocess."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SIM_DIR = REPO_ROOT / "c_simulator"
SIM_BINARY = SIM_DIR / "device_sim"

sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _rebuild_simulator_once() -> None:
    """Force a clean rebuild of device_sim once per test session."""
    subprocess.run(["make", "clean"], cwd=SIM_DIR, capture_output=True, text=True)
    result = subprocess.run(["make"], cwd=SIM_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(
            f"Failed to build {SIM_BINARY}:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _free_port() -> int:
    """Find an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


def _wait_until_listening(port: int, timeout: float = 3.0) -> None:
    """Block until the port accepts TCP connections or timeout occurs."""
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise TimeoutError(f"device_sim never started listening on port {port}: {last_error}")


class SimulatorProcess:
    """Wraps a running device_sim subprocess and its port."""

    def __init__(self, process: subprocess.Popen, port: int) -> None:
        self.process = process
        self.port = port

    def stop(self) -> None:
        """Terminate the process, escalating to kill if necessary."""
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


def _start_simulator(extra_args: list[str] | None = None) -> SimulatorProcess:
    """Launch device_sim on a free port with given CLI arguments."""
    port = _free_port()
    args = [str(SIM_BINARY), "--port", str(port), *(extra_args or [])]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_until_listening(port)
    except TimeoutError:
        process.kill()
        output = process.stdout.read() if process.stdout else ""
        pytest.fail(f"device_sim failed to start on port {port}:\n{output}")
    return SimulatorProcess(process, port)


@pytest.fixture
def simulator() -> Iterator[SimulatorProcess]:
    """Provide a plain device_sim instance with automatic cleanup."""
    sim = _start_simulator()
    try:
        yield sim
    finally:
        sim.stop()


@pytest.fixture
def make_simulator() -> Iterator:
    """Factory fixture to start device_sim with custom CLI arguments."""
    started: list[SimulatorProcess] = []

    def _make(extra_args: list[str] | None = None) -> SimulatorProcess:
        sim = _start_simulator(extra_args)
        started.append(sim)
        return sim

    yield _make

    for sim in started:
        sim.stop()
