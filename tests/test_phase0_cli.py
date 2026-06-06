from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from codebase_lens.core.constants import PARTIAL_IMPLEMENTATION_MESSAGE, PUBLIC_COMMANDS

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run_cbl(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_top_level_help_renders_command_surface() -> None:
    result = run_cbl("--help")
    assert result.returncode == 0
    for command in ("doctor", "pack", "contract", "changed", "callers"):
        assert command in result.stdout


def test_doctor_is_explicit_partial_implementation() -> None:
    result = run_cbl("doctor")
    assert result.returncode == 1
    assert "CBL command: doctor" in result.stdout
    assert PARTIAL_IMPLEMENTATION_MESSAGE in result.stdout


def test_all_public_commands_have_help() -> None:
    for command in PUBLIC_COMMANDS:
        result = run_cbl(command, "--help")
        assert result.returncode == 0, command
