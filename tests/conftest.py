"""Repo-wide pytest setup.

Makes the `orchestrator` package importable. Simulator fixtures live in
tests/integration/conftest.py so unit tests require no C compiler.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))