# Multi-Stage Attack Orchestrator

A framework for orchestrating multi-stage simulated device interactions,
combining a low-level C device simulator with a Python
orchestration, client, and testing framework.

---

## Architecture & Components

- **C Simulator (`c_simulator/`)**: A TCP server binary (`device_sim`)
  simulating target device behavior over a custom binary protocol, with
  CLI fault injection (`--fail-stage`, `--drop-stage`) for testing failure
  paths.
- **Python Framework (`python_framework/`)**:
  - **`models.py`** — `DeviceState`, `AttackStage`, and `Attack`, including
    iOS version compatibility bounds.
  - **`client.py`** — `DeviceClient`: binary packet framing/parsing via
    `struct`, TCP socket communication, and error handling
    (`DeviceConnectionError`, `DeviceProtocolError`).
  - **`orchestrator.py`** — `AttackOrchestrator`: plan selection,
    sequential multi-stage execution, and per-stage status tracking
    (`SUCCESS`, `FAILED`, `DROPPED`, `SKIPPED`).
  - **`extractor.py`** — `DataExtractor`: reads files off the device and
    writes them to a local output directory.
- **Test Suite (`tests/`)**:
  - **Unit tests** (`test_framework_unit.py`) — fast, isolated tests using
    in-memory fakes and mocks (`FakeSocket`, `FakeDeviceClient`), no real
    sockets or subprocesses.
  - **Integration tests** (`test_simulator_integration.py`) — end-to-end
    tests over real TCP sockets against a freshly compiled `device_sim`
    binary, managed by fixtures in `conftest.py`.

### Repo layout

```
c_simulator/
  protocol.h                     Wire protocol: message types, status codes, structs
  main.c                         Server implementation (fault injection included)
  Makefile                       Builds ./device_sim
  device_sim                     Compiled binary (build artifact, not committed)

python_framework/
  models.py                      DeviceState, AttackStage, Attack (domain data)
  client.py                      DeviceClient: TCP client speaking the binary protocol
  orchestrator.py                AttackOrchestrator: plan selection + sequential execution
  extractor.py                   DataExtractor: pulls files off the device to disk

tests/
  conftest.py                    Shared fixtures for launching device_sim as a subprocess
  test_simulator_integration.py  Tests against the real, compiled simulator
  test_framework_unit.py         Unit tests using in-memory fakes/mocks (no sockets)
```

---

## Prerequisites

- Python 3.8+
- `make` and a C compiler (`gcc`/`clang`)

---

## Setup & Installation

1. Clone the repository and navigate into it:

   ```bash
   git clone https://github.com/barkobi40/Multi-Stage-Attack-Orchestrator.git
   cd Multi-Stage-Attack-Orchestrator
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install pytest
   ```

---

## How to Build and Run

### 1. Build the C simulator

The integration tests clean and rebuild the binary automatically before
running (see [Known gotchas](#known-gotchas)), but you can also build it
manually:

```bash
cd c_simulator
make clean
make
cd ..
```

This produces `c_simulator/device_sim`, which prints
`[BUILD_VER_101] Device simulator starting...` on launch — a quick way to
confirm you're running a binary built from the current `main.c` rather than
a leftover build from earlier.

### 2. Run it standalone

```bash
cd c_simulator
./device_sim --port 8888
```

CLI flags:

| Flag | Effect |
|---|---|
| `--port <n>` | Listening port (default `8888`) |
| `--fail-stage <id>` | `MSG_EXECUTE_STAGE` for this stage id returns `STATUS_STAGE_FAILED` instead of `STATUS_OK` |
| `--drop-stage <id>` | The connection is closed abruptly when this stage id is executed, simulating a device crash/disconnect mid-chain |

### 3. Run all tests

Execute the entire suite (unit tests + real C-simulator integration tests)
from the repo root:

```bash
pytest tests/ -v
```

Or run a subset:

```bash
pytest tests/test_framework_unit.py -v          # fast, no network
pytest tests/test_simulator_integration.py -v   # against the real simulator
```

---

## Wire Protocol (`protocol.h`)

All multi-byte integers are **big-endian / network byte order**
(`htons`/`htonl` on the C side, `>` format strings on the Python side).
Every struct is packed with no padding (`#pragma pack(push, 1)`), so the
Python side mirrors these exact layouts:

| Struct | Layout | Size |
|---|---|---|
| `MessageHeader` | `msg_type` (**uint8**), `payload_len` (uint32) | 5 bytes |
| `ResponseHeader` | `status` (uint32), `data_len` (uint32) | 8 bytes |
| `DeviceInfoPayload` | `battery_level` (uint8), `ios_version_major` (uint16), `ios_version_minor` (uint16), `model` (32-byte string) | 37 bytes |
| `ExecuteStagePayload` | `stage_id` (uint8) | 1 byte |

Message types: `MSG_GET_INFO=0x01`, `MSG_EXECUTE_STAGE=0x02`, `MSG_READ_FILE=0x03`, `MSG_RESPONSE=0x04`.
Status codes: `STATUS_OK=0`, `STATUS_STAGE_FAILED=1`, `STATUS_FILE_NOT_FOUND=2`, `STATUS_ERROR=99`.

> **`msg_type` is a single byte**, not two — packing it as a uint16 anywhere
> (client code or a hand-rolled test script) desyncs every following byte on
> the wire. `python_framework/client.py` packs it as `>BI`, and
> `tests/test_framework_unit.py` has a regression test asserting the exact
> request bytes for this reason.

---

## Using the Python Framework

```python
from python_framework.client import DeviceClient
from python_framework.models import Attack, AttackStage
from python_framework.orchestrator import AttackOrchestrator
from python_framework.extractor import DataExtractor

with DeviceClient(host="localhost", port=8888) as client:
    device = client.get_device_info()

    plan = Attack(
        stages=[AttackStage(1, "unlock"), AttackStage(2, "extract")],
        min_ios_version=(14, 0),
        max_ios_version=(18, 0),
    )

    orchestrator = AttackOrchestrator(client)
    selected = orchestrator.select_plan(device, [plan])
    result = orchestrator.run(selected, device=device)

    print(result.succeeded, [(r.stage.stage_id, r.status) for r in result.stage_results])

    if result.succeeded:
        extractor = DataExtractor(client, "./extracted")
        extractor.extract_file("/var/mobile/some_file.db")
```

- `DeviceClient` raises `DeviceConnectionError` for socket/timeout/dropped-connection
  problems, and `DeviceProtocolError` for framing issues or unexpected status codes.
- `AttackOrchestrator.run()` stops at the first stage that fails
  (`StageStatus.FAILED`) or drops the connection (`StageStatus.DROPPED`);
  remaining stages are recorded as `StageStatus.SKIPPED` rather than attempted.

---

## What the Test Suite Covers

**`test_framework_unit.py`** — in-memory fakes/mocks only, no sockets or
subprocesses:
- `models.py`: validation rules (battery level range, stage id range,
  duplicate stage ids, inverted version bounds) and `Attack.is_compatible()`
  boundary values.
- `orchestrator.py`: plan selection, and `run()` behavior across
  all-succeed / a stage failing / a connection dropping / a protocol error /
  an explicitly incompatible device, via a small `FakeDeviceClient`.
- `extractor.py`: successful writes, wrapping device errors into
  `ExtractionError`, and batch extraction skipping individual failures.
- `client.py`: the real `struct.pack`/`unpack` framing logic, exercised
  against a `FakeSocket` so no real network I/O happens.

**`test_simulator_integration.py`** — talks over a real TCP socket to a
freshly built `device_sim` subprocess (launched and torn down per test by
fixtures in `conftest.py`):
- `get_device_info()` / `read_device_file()` round trips.
- A full multi-stage attack run where every stage succeeds, followed by a
  `DataExtractor` pull.
- `--fail-stage` fault injection: confirms `STATUS_STAGE_FAILED` is surfaced
  correctly and halts the remaining stages.
- `--drop-stage` fault injection: confirms an abrupt disconnect raises
  `DeviceConnectionError` and is recorded distinctly as `DROPPED` (not
  `FAILED`) by the orchestrator.

`conftest.py`'s session-scoped fixture runs `make clean && make` once before
any integration test executes, so the suite always tests the binary actually
built from the current `main.c` rather than a possibly-stale leftover build.

---

## Known gotchas

- **Stale `device_sim` binary**: `make` only rebuilds when its sources are
  newer than the existing binary. If you edit `main.c` and don't see the
  change take effect, run `make clean && make` rather than trusting `make`
  alone — the test suite already does this automatically.
- **Byte order**: every multi-byte field on the wire is big-endian. If a
  value like `ios_major`/`ios_minor` looks byte-swapped (e.g. `16` reading
  back as `4096`), it means one side of the connection isn't applying
  `htons`/`>` correctly — check which binary is actually running before
  assuming the Python client is wrong.
