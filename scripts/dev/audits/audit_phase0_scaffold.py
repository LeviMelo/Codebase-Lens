from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

PUBLIC_COMMANDS = (
    "doctor",
    "snapshot",
    "tree",
    "symbols",
    "imports",
    "cli",
    "routes",
    "tests",
    "diff",
    "changed",
    "file",
    "symbol",
    "callers",
    "contract",
    "pack",
    "clean",
)

REQUIRED_FILES = [
    "pyproject.toml",
    "README.md",
    ".gitignore",
    "src/codebase_lens/__init__.py",
    "src/codebase_lens/__main__.py",
    "src/codebase_lens/cli.py",
    "src/codebase_lens/core/constants.py",
    "src/codebase_lens/core/result.py",
    "src/codebase_lens/core/models.py",
    "tests/test_phase0_cli.py",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


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


def main() -> int:
    for file in REQUIRED_FILES:
        if not (ROOT / file).is_file():
            fail(f"Missing required file: {file}")

    help_result = run_cbl("--help")
    if help_result.returncode != 0:
        fail(help_result.stderr)

    for command in PUBLIC_COMMANDS:
        if command not in help_result.stdout:
            fail(f"Missing command in top-level help: {command}")

        command_help = run_cbl(command, "--help")
        if command_help.returncode != 0:
            fail(f"Help failed for command: {command}")

    doctor = run_cbl("doctor")
    if doctor.returncode != 1:
        fail(f"doctor should return 1 during Phase 0, got {doctor.returncode}")

    if "PARTIAL IMPLEMENTATION" not in doctor.stdout:
        fail("doctor did not report explicit partial implementation")

    print("PASS: Phase 0 scaffold audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
