# Multi-Stage-Attack-Orchestrator

A framework for orchestrating multi-stage simulated device interactions, combining a low-level C device simulator with a Python orchestration, client, and testing framework.

---

## Architecture & Components

- **C Simulator (`c_simulator/`)**: A TCP server binary (`device_sim`) simulating target device behavior, supporting CLI fault injection (`--fail-stage`, `--drop-stage`).
- **Python Package (`orchestrator/`)**:
  - **`attacks/`**: Attack definitions (`attack.py`), a small preset registry (`catalog.py`), and plan-compatibility selection (`selector.py`).
  - **`connection/`**: A shared `DeviceConnection` interface (`base.py`), the real TCP implementation (`tcp.py`), a scriptable in-memory implementation (`mock.py`), a backend factory (`provider.py`), and a context-manager convenience (`session.py`).
  - **`models/`**: Device state (`device.py`).
  - **`protocol.py`**: Pure binary encode/decode for the wire protocol (no socket I/O) — matches `c_simulator/protocol.h`.
  - **`orchestrator.py`**: Sequential multi-stage execution and status tracking (Success, Failed, Skipped, Dropped).
  - **`extractor.py`**: Reads files off a device connection and writes them to a local output directory.
  - **`errors.py`**: The shared exception hierarchy.
- **Test Suite (`tests/`)**:
  - **`unit/`**: Fast, isolated tests against `MockConnection`/fakes — no sockets, no C build.
  - **`integration/`**: End-to-end tests over real TCP sockets against the freshly compiled C simulator binary (fixtures in `integration/conftest.py`).

### Repo layout

```
c_simulator/
  protocol.h, main.c, Makefile, device_sim

orchestrator/
  __init__.py                Re-exports the public API
  errors.py                  Shared exception hierarchy
  protocol.py                Wire-format encode/decode (no I/O)
  orchestrator.py            AttackOrchestrator: plan selection + sequential execution
  extractor.py                DataExtractor: pulls files off a device connection
  attacks/
    attack.py                 Attack, AttackStage
    catalog.py                 Reusable Attack presets
    selector.py                 select_plan()
  connection/
    base.py                    DeviceConnection interface
    tcp.py                      TCPConnection (real socket I/O)
    mock.py                     MockConnection (scriptable in-memory fake)
    provider.py                  get_connection() factory
    session.py                   device_session() context manager
  models/
    device.py                  DeviceState

tests/
  conftest.py                 sys.path setup only
  unit/                       No sockets, no C build required
  integration/                Real device_sim subprocess (conftest.py here builds it)
```

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

### 2. Run Tests

```bash
pytest tests/ -v                 # everything
pytest tests/unit/ -v            # fast, no C build or sockets
pytest tests/integration/ -v     # against the real simulator
```

### 3. One-Command Shortcuts

A top-level `Makefile` wraps the common commands:

```bash
make build            # clean rebuild of the C simulator
make test             # pytest tests/ -v
make test-unit        # pytest tests/unit/ -v
make test-integration # pytest tests/integration/ -v
make lint             # ruff check .
make typecheck        # mypy orchestrator
make demo             # build the simulator and run a full attack scenario end-to-end
```

`demo.py` (invoked by `make demo`) builds `device_sim`, launches it, runs a
multi-stage attack via `AttackOrchestrator` (using the `"basic-three-stage"`
preset from `orchestrator.attacks.catalog`), extracts a file via
`DataExtractor`, and tears the simulator back down — a single command that
exercises the whole stack.

### Usage example

```python
from orchestrator import CATALOG, AttackOrchestrator, DataExtractor, TCPConnection

with TCPConnection(host="localhost", port=8888) as connection:
    device = connection.get_device_info()

    plan = CATALOG["basic-three-stage"]
    orchestrator = AttackOrchestrator(connection)
    selected = orchestrator.select_plan(device, [plan])
    result = orchestrator.run(selected, device=device)

    if result.succeeded:
        DataExtractor(connection, "./extracted").extract_file("/var/mobile/some_file")
```

Swap `TCPConnection` for `orchestrator.MockConnection` (or
`orchestrator.get_connection("mock", ...)`) to run the same code offline,
without a compiled simulator — both implement the same `DeviceConnection`
interface.

---

## Code Quality

Install the tooling once:

```bash
pip install ruff mypy
```

Then:

```bash
ruff check .          # lint
mypy orchestrator     # static type checking
```

Both are configured in `pyproject.toml`.

---

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request to `main`: it
lints with `ruff`, type-checks with `mypy`, builds the C simulator, and runs
the full pytest suite across Python 3.9 and 3.11.
