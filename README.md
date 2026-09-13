# Multi-Stage-Attack-Orchestrator

A framework for orchestrating multi-stage simulated device interactions, combining a low-level C device simulator with a Python orchestration, client, and testing framework.

---

## Architecture & Components

- **C Simulator (`c_simulator/`)**: A TCP server binary (`device_sim`) simulating target device behavior, supporting CLI fault injection (`--fail-stage`, `--drop-stage`). See [Wire Protocol](#wire-protocol) below for the binary framing it speaks.
- **Python Framework (`python_framework/`)**:
  - **`models.py`**: `DeviceState` and the immutable `Attack`/`AttackStage`. An `Attack` declares the device state it needs — an iOS version range, a minimum battery level, and (optionally) a specific set of compatible device models — plus a `success_probability` used to rank it against other viable attacks. `Attack` is frozen (its `stages` are normalized to a tuple in `__post_init__`), so its validated invariants can't be invalidated by mutation after construction.
  - **`client.py`**: Binary packet framing/parsing via `struct`, TCP socket communication, error handling (`DeviceConnectionError`, `DeviceProtocolError`), and the `StageExecutor`/`FileReader` structural interfaces (`typing.Protocol`) that `AttackOrchestrator` and `DataExtractor` actually depend on, instead of the concrete `DeviceClient` — see [Design Trade-offs](#design-trade-offs).
  - **`orchestrator.py`**: `AttackOrchestrator.select_plan()` filters candidate attacks down to those whose requirements the current `DeviceState` satisfies, then picks the highest-`success_probability` one among them (ties keep the given order). `run()` then executes the chosen plan's stages sequentially, tracking per-stage status (Success, Failed, Skipped, Dropped).
  - **`extractor.py`**: Reads one or more files off the device and writes them to a local output directory (`extract_file` / `extract_files`).
- **Test Suite (`tests/`)**:
  - **Unit Tests (`test_framework_unit.py`)**: Fast, isolated tests using in-memory mocks and fakes.
  - **Integration Tests (`test_simulator_integration.py`)**: End-to-end tests over real TCP sockets against the freshly compiled C simulator binary (`conftest.py`), including raw wire-protocol edge cases (oversized payloads) that bypass the Python client's own guards.

---

## Wire Protocol

`python_framework/client.py` and `c_simulator/protocol.h`/`main.c` implement the same binary, big-endian, length-prefixed protocol over a single persistent TCP connection. Every request and response starts with a fixed header; the client always initiates.

### Request header (client → server)

| Field         | Type     | Notes                              |
|---------------|----------|-------------------------------------|
| `msg_type`    | `uint8`  | One of the message types below      |
| `payload_len` | `uint32` | Length in bytes of what follows     |

Packed with `struct.pack(">BI", msg_type, len(payload))` on the Python side; `#pragma pack(push, 1)` on the C side.

### Message types

| Value  | Name              | Request payload                          | Response payload                         |
|--------|-------------------|-------------------------------------------|--------------------------------------------|
| `0x01` | `MSG_GET_INFO`    | none (`payload_len` must be `0`)          | `DeviceInfoPayload`                        |
| `0x02` | `MSG_EXECUTE_STAGE` | `ExecuteStagePayload` (`uint8 stage_id`) | none                                        |
| `0x03` | `MSG_READ_FILE`   | UTF-8 device path, up to 255 bytes        | raw file bytes                             |
| `0x04` | `MSG_RESPONSE`    | *(reserved — never sent by the client)*   | —                                           |

`DeviceInfoPayload` (37 bytes, packed):

| Field                | Type      |
|----------------------|-----------|
| `battery_level`      | `uint8`   |
| `ios_version_major`  | `uint16`  |
| `ios_version_minor`  | `uint16`  |
| `model`              | `char[32]`, NUL-padded |

### Response header (server → client)

Every response — regardless of which request it answers — starts with:

| Field       | Type     | Notes                                   |
|-------------|----------|-------------------------------------------|
| `status`    | `uint32` | One of the status codes below             |
| `data_len`  | `uint32` | Length in bytes of the payload that follows (`0` for `MSG_EXECUTE_STAGE`) |

followed by exactly `data_len` bytes of payload (device info, file bytes, or nothing).

### Status codes

| Value | Name                    | Meaning                                                    |
|-------|-------------------------|--------------------------------------------------------------|
| `0`   | `STATUS_OK`             | Request succeeded                                             |
| `1`   | `STATUS_STAGE_FAILED`   | `MSG_EXECUTE_STAGE` ran but the stage did not succeed         |
| `2`   | `STATUS_FILE_NOT_FOUND` | Reserved for `MSG_READ_FILE`; the current simulator always returns dummy file data instead, so this status is currently only exercised by mocked unit tests, never by the real binary |
| `99`  | `STATUS_ERROR`          | Malformed request (e.g. wrong `payload_len` for the message type) |

### Error scenarios

- **Dropped connection mid-chain** (`device_sim --drop-stage N`): the server closes the socket instead of responding to `MSG_EXECUTE_STAGE` for stage `N`. The client surfaces this as `DeviceConnectionError`, and `AttackOrchestrator.run()` marks that stage `DROPPED` and skips the remaining stages.
- **Stage failure** (`device_sim --fail-stage N`): the server responds normally with `STATUS_STAGE_FAILED` for stage `N`. `execute_stage()` returns `False`, and `run()` marks the stage `FAILED` and skips the rest.
- **Malformed payload length**: every handler drains exactly the `payload_len` it was told to expect — even when it's larger than the handler needs (e.g. an over-long `MSG_READ_FILE` path, or a `MSG_GET_INFO`/`MSG_EXECUTE_STAGE` payload that doesn't match the expected size) — so a non-conforming request can't desync the framing of the next message on the same connection. `MSG_EXECUTE_STAGE` responds `STATUS_ERROR` when `payload_len` doesn't match the expected 1-byte stage id.
- **Stalled or slow-sending client**: each accepted connection gets a 5-second `SO_RCVTIMEO`. A client that declares a `payload_len` and then never (or too slowly) finishes sending it has its `recv()` fail instead of blocking forever — important because the server is single-threaded and one-connection-at-a-time (see [Design Trade-offs](#design-trade-offs)), so a single stuck connection would otherwise starve every other client.

---

## Design Trade-offs

A few deliberate choices worth calling out explicitly, since they shape how the framework should (and shouldn't) be read:

- **`success_probability` informs planning, not execution.** `select_plan()` uses it purely to rank *candidate* attacks before anything runs — it never feeds randomness into `AttackOrchestrator.run()`. Whether a stage actually succeeds always comes from the real device's response (or the simulator's `--fail-stage`/`--drop-stage` fault injection), never a coin flip. This keeps stage execution deterministic and the test suite reproducible, at the cost of `success_probability` being only as accurate as whatever a caller sets it to — it's an a-priori risk estimate for choosing between attacks, not a simulation of real-world reliability.
- **The C simulator is single-threaded and handles one connection at a time by design** (`accept()` → `handle_client()` → loop). That's the right model for a test harness where each test spins up its own `device_sim` subprocess and talks to it alone — it is *not* a concurrency model suitable for multiple simultaneous orchestrator sessions against one simulator instance. The per-connection `SO_RCVTIMEO` bounds how long one stalled client can block the others, but doesn't add concurrency.
- **`StageExecutor`/`FileReader` are structural (`typing.Protocol`) interfaces, not a shared base class.** `AttackOrchestrator` and `DataExtractor` depend on the minimal method each actually calls, rather than the concrete `DeviceClient`. This keeps the dependency direction correct (policy code depends on an abstraction, not on the transport) and means a test double only needs to implement the one method it's exercising — no need to subclass `DeviceClient` or stub out the rest of its surface.
- **`STATUS_FILE_NOT_FOUND` is defined but currently unreachable in the real simulator** — `MSG_READ_FILE` always returns the same dummy payload regardless of the requested path. It's disclosed here rather than hidden: the status code and the client-side handling for it are real and tested (via a mocked socket), but nothing in `main.c` triggers it today. Extending the simulator with something like a `--missing-file <path>` flag would close this gap if it matters for a given use case.

---

## Prerequisites

- Python 3.8+
- `make` and a C compiler (`gcc`/`clang`)

---

## Setup & Installation

1. **Clone the repository and navigate into it:**
   ```bash
   git clone https://github.com/barkobi40/Multi-Stage-Attack-Orchestrator.git
   cd Multi-Stage-Attack-Orchestrator
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install pytest
   ```

---

## How to Build and Run

### 1. Build the C Simulator Manually (Optional)

The integration tests automatically clean and rebuild the binary before running, but you can build it manually via:

```bash
cd c_simulator
make clean
make
cd ..
```

### 2. Run All Tests

Execute the entire test suite (both unit tests and real C-simulator integration tests) using pytest:

```bash
pytest tests/ -v
```

### 3. One-Command Shortcuts

A top-level `Makefile` wraps the common commands:

```bash
make build      # clean rebuild of the C simulator
make test       # pytest tests/ -v
make lint       # ruff check .
make typecheck  # mypy python_framework
make demo       # build the simulator and run a full attack scenario end-to-end
```

`demo.py` (invoked by `make demo`) builds `device_sim`, launches it, fetches
the device state, picks the best of several candidate `Attack` plans via
`AttackOrchestrator.select_plan()` (excluding ones the device's battery or
model can't satisfy, preferring the highest `success_probability` among the
rest), runs the selected multi-stage attack, extracts a file via
`DataExtractor`, and tears the simulator back down — a single command that
exercises the whole stack.

---

## Code Quality

Install the tooling once:

```bash
pip install ruff mypy
```

Then:

```bash
ruff check .              # lint
mypy python_framework     # static type checking
```

Both are configured in `pyproject.toml`.

---

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request to `main`: it
lints with `ruff`, type-checks with `mypy`, builds the C simulator, and runs
the full pytest suite across Python 3.9 and 3.11.

