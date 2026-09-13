# Multi-Stage-Attack-Orchestrator

A framework for orchestrating multi-stage simulated device interactions, combining a low-level C device simulator with a Python orchestration, client, and testing framework.

---

## Architecture & Components

- **C Simulator (`c_simulator/`)**: A TCP server binary (`device_sim`) simulating target device behavior, supporting CLI fault injection (`--fail-stage`, `--drop-stage`).
- **Python Framework (`python_framework/`)**:
  - **`models.py`**: Device states, attack stages, and iOS version compatibility bounds.
  - **`client.py`**: Binary packet framing/parsing via `struct`, TCP socket communication, and error handling (`DeviceConnectionError`, `DeviceProtocolError`).
  - **`orchestrator.py`**: Plan selection, sequential multi-stage execution, and status tracking (Success, Failed, Skipped, Dropped).
  - **`extractor.py`**: Reads files off the device and writes them to a local output directory.
- **Test Suite (`tests/`)**:
  - **Unit Tests (`test_framework_unit.py`)**: Fast, isolated tests using in-memory mocks and fakes.
  - **Integration Tests (`test_simulator_integration.py`)**: End-to-end tests over real TCP sockets against the freshly compiled C simulator binary (`conftest.py`).

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
