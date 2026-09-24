"""Test bootstrap for the conformance runner.

The runner is a script-style package (modules import each other by bare name),
so the runner directory is added to sys.path here rather than turning
``runner/`` into an installed package.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
RUNNER_DIR = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"

if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))


@pytest.fixture
def load_fixture():
    """Load a captured suite payload from ``tests/fixtures``."""

    def _load(name: str):
        return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
