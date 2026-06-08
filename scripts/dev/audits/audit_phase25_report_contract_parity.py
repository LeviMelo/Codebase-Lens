from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


REQUIRED_SNAPSHOT_SECTIONS = [
    "# Repository Snapshot",
    "## Generation Metadata",
    "## Repository Identity",
    "## Git State",
    "## Project Markers",
    "## File Universe Summary",
    "## Top-Level Tree",
    "## Language/Extension Summary",
    "## Python Package Summary",
    "## Important Symbols",
    "## CLI Inventory Summary",
    "## Test Inventory Summary",
    "## Import Graph Summary",
    "## Safety and Redaction Summary",
    "## Skipped/Omitted Files Summary",
    "## Suggested Follow-Up Commands",
]

REQUIRED_DIFF_SECTIONS = [
    "# Diff Summary",
    "## Git Base",
    "## Staged Changes",
    "## Unstaged Changes",
    "## Untracked Source Files",
    "## Changed Files",
    "## Changed Symbols",
    "## Diff Stats",
    "## Follow-Up Commands",
]

REQUIRED_CONTRACT_SECTIONS = [
    "# Architecture Contract Audit",
    "## Contract Metadata",
    "## Summary",
    "## Failed Rules",
    "## Warnings",
    "## Informational Findings",
    "## Passed Rules",
    "## Skipped Rules",
    "## Evidence",
    "## Suggested Remediation",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def run_cbl(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def make_repo(base: Path) -> Path:
    repo = base / "report_contract_repo"
    package = repo / "src" / "demo_pkg"
    tests = repo / "tests"

    write(
        repo / "pyproject.toml",
        """
[project]
name = 'demo-pkg'
version = '0.0.0'
""",
    )

    write(package / "__init__.py", "")
    write(
        package / "core.py",
        """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().lower()

def build_name(name: str) -> str:
    return normalize_name(name)
""",
    )
    write(
        package / "cli.py",
        """
from __future__ import annotations

import argparse
from demo_pkg.core import build_name

def _run_build(raw: str) -> str:
    return build_name(raw)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command')
    build = sub.add_parser('build')
    build.set_defaults(handler=_run_build)
    return parser
""",
    )
    write(
        tests / "test_core.py",
        """
from demo_pkg.core import normalize_name

def test_normalize_name():
    assert normalize_name(' A ') == 'a'
""",
    )

    init = run_git(repo, "init")
    if init.returncode == 0:
        run_git(repo, "config", "user.email", "fixture@example.invalid")
        run_git(repo, "config", "user.name", "CBL Fixture")
        run_git(repo, "add", ".")
        run_git(repo, "commit", "-m", "initial")
        write(
            package / "core.py",
            """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().casefold()

def build_name(name: str) -> str:
    return normalize_name(name)

def changed_symbol() -> str:
    return build_name('changed')
""",
        )
        write(
            package / "new_file.py",
            """
from __future__ import annotations

def untracked_symbol() -> str:
    return 'new'
""",
        )

    return repo


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def assert_contains(path: Path, required: list[str]) -> None:
    if not path.is_file():
        fail(f"Missing required file: {path}")
    text = path.read_text(encoding="utf-8")
    missing = [item for item in required if item not in text]
    if missing:
        fail(f"{path} is missing required sections/text: {missing}")


def main() -> int:
    for relative in [
        "src/codebase_lens/core/budget.py",
        "src/codebase_lens/reports/snapshot.py",
        "src/codebase_lens/reports/diff.py",
        "src/codebase_lens/reports/contract.py",
        "scripts/dev/audits/audit_phase25_report_contract_parity.py",
    ]:
        assert_parseable(relative)

    snapshot_source = (ROOT / "src/codebase_lens/reports/snapshot.py").read_text(encoding="utf-8")
    if "size_bytes // 4" in snapshot_source:
        fail("Budget token estimation still lives directly in reports/snapshot.py.")

    budget_source = (ROOT / "src/codebase_lens/core/budget.py").read_text(encoding="utf-8")
    if "size_bytes // 4" not in budget_source:
        fail("Budget token estimation was not moved into core/budget.py.")

    with tempfile.TemporaryDirectory(prefix="cbl_report_contract_") as temp_dir:
        repo = make_repo(Path(temp_dir))

        snapshot = run_cbl("snapshot", "--repo", str(repo), "--no-archive")
        if snapshot.returncode != 0:
            fail(f"cbl snapshot failed:\nSTDOUT:\n{snapshot.stdout}\nSTDERR:\n{snapshot.stderr}")

        latest = repo / ".codecontext" / "latest"
        assert_contains(latest / "repo_snapshot.md", REQUIRED_SNAPSHOT_SECTIONS)

        for filename in [
            "git_state.json",
            "repo_snapshot.md",
            "snapshot_index.json",
            "file_inventory.json",
            "symbol_index.json",
            "import_graph.json",
            "cli_inventory.json",
            "test_inventory.json",
            "omissions.json",
        ]:
            if not (latest / filename).is_file():
                fail(f"snapshot did not write required report: {filename}")

        git_state = json.loads((latest / "git_state.json").read_text(encoding="utf-8"))
        if git_state.get("schema", {}).get("name") != "cbl.git_state":
            fail("git_state.json has wrong schema name.")

        diff = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
        if diff.returncode != 0:
            fail(f"cbl diff --symbols failed:\nSTDOUT:\n{diff.stdout}\nSTDERR:\n{diff.stderr}")

        assert_contains(latest / "diff_summary.md", REQUIRED_DIFF_SECTIONS)
        if not (latest / "diff.json").is_file():
            fail("diff did not write diff.json.")
        if "changed_symbols" not in json.loads((latest / "diff.json").read_text(encoding="utf-8")):
            fail("diff --symbols did not include changed_symbols in diff.json.")

    contract = run_cbl("contract", "--repo", str(ROOT), "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    assert_contains(latest / "contract_audit.md", REQUIRED_CONTRACT_SECTIONS)

    for filename in [
        "contract_audit.json",
        "contract_audit.md",
        "contract_report.json",
    ]:
        if not (latest / filename).is_file():
            fail(f"contract did not write required report or compatibility alias: {filename}")

    payload = json.loads((latest / "contract_audit.json").read_text(encoding="utf-8"))
    if payload.get("schema", {}).get("name") != "cbl.contract_audit":
        fail("contract_audit.json has wrong schema name.")

    print("PASS: Phase 25 report contract parity audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
