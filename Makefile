.PHONY: build test lint typecheck demo clean

PYTHON ?= python3

# Force a clean rebuild of the C simulator (avoids stale-binary surprises).
build:
	$(MAKE) -C c_simulator clean
	$(MAKE) -C c_simulator

test:
	pytest tests/ -v

lint:
	ruff check .

typecheck:
	mypy python_framework

# Builds the simulator, runs a full attack scenario end to end, tears it down.
demo:
	$(PYTHON) demo.py

clean:
	$(MAKE) -C c_simulator clean
