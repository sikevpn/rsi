"""Shared fixtures: a real, tiny target project with a genuinely failing test suite.

The stub backend fixes (or fails to fix) this project, so backpressure, audit and cheat
detection are exercised against real ``pytest`` runs rather than mocks.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LOOP_PROJECT = REPO_ROOT / "loop-project"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BROKEN_IMPL = 'def divide(a, b):\n    return a // b\n'
FIXED_IMPL = (
    'def divide(a, b):\n'
    '    if b == 0:\n'
    '        raise ValueError("division by zero")\n'
    '    return a / b\n'
)
TEST_FILE = (
    "import pytest\n"
    "from calculator import divide\n\n"
    "def test_divide_exact():\n"
    "    assert divide(7, 2) == 3.5\n\n"
    "def test_divide_negative():\n"
    "    assert divide(-7, 2) == -3.5\n\n"
    "def test_divide_zero_denominator():\n"
    "    with pytest.raises(ValueError):\n"
    "        divide(1, 0)\n"
)
TEST_COMMAND = "python3 -m pytest -q test_calculator.py"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A copy of loop-project/ plus a broken calculator and its failing tests."""
    root = tmp_path / "target"
    shutil.copytree(LOOP_PROJECT, root)
    (root / "calculator.py").write_text(BROKEN_IMPL, encoding="utf-8")
    (root / "test_calculator.py").write_text(TEST_FILE, encoding="utf-8")
    (root / "receipts").mkdir(exist_ok=True)
    return root


@pytest.fixture
def config(project: Path):
    from rsi.config import LoopConfig

    cfg = LoopConfig.load(project / "config" / "loop.yaml")
    cfg.test_commands = (TEST_COMMAND,)
    cfg.max_iterations = 6
    return cfg
