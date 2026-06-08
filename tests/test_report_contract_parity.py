from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


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
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    package = repo / "src" / "demo_pkg"
    tests = repo / "tests"

    write(repo / "pyproject.toml", "[project]\nname = 'demo-pkg'\nversion = '0.0.0'\n")
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

def run() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('build')
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
    return repo


def make_git_repo(tmp_path: Path) -> Path:
    repo = make_repo(tmp_path)
    if run_git(repo, "init").returncode != 0:
        return repo
    run_git(repo, "config", "user.email", "fixture@example.invalid")
    run_git(repo, "config", "user.name", "CBL Fixture")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "initial")
    write(
        repo / "src" / "demo_pkg" / "core.py",
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
    return repo


def test_snapshot_writes_tdd_canonical_reports(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("snapshot", "--repo", str(repo), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"

    assert (latest / "repo_snapshot.md").is_file()
    assert (latest / "git_state.json").is_file()
    assert (latest / "snapshot_index.json").is_file()

    text = (latest / "repo_snapshot.md").read_text(encoding="utf-8")
    for section in [
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
    ]:
        assert section in text

    git_state = json.loads((latest / "git_state.json").read_text(encoding="utf-8"))
    assert git_state["schema"]["name"] == "cbl.git_state"


def test_diff_writes_summary_markdown_and_changed_symbols_when_requested(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)

    result = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    assert (latest / "diff.json").is_file()
    assert (latest / "diff_summary.md").is_file()

    text = (latest / "diff_summary.md").read_text(encoding="utf-8")
    for section in [
        "# Diff Summary",
        "## Git Base",
        "## Staged Changes",
        "## Unstaged Changes",
        "## Untracked Source Files",
        "## Changed Files",
        "## Changed Symbols",
        "## Diff Stats",
        "## Follow-Up Commands",
    ]:
        assert section in text

    payload = json.loads((latest / "diff.json").read_text(encoding="utf-8"))
    assert "changed_symbols" in payload


def test_contract_writes_canonical_audit_reports_and_alias() -> None:
    result = run_cbl("contract", "--repo", str(ROOT), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = ROOT / ".codecontext" / "latest"
    assert (latest / "contract_audit.json").is_file()
    assert (latest / "contract_audit.md").is_file()
    assert (latest / "contract_report.json").is_file()

    payload = json.loads((latest / "contract_audit.json").read_text(encoding="utf-8"))
    assert payload["schema"]["name"] == "cbl.contract_audit"

    text = (latest / "contract_audit.md").read_text(encoding="utf-8")
    for section in [
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
    ]:
        assert section in text


def test_budget_estimation_is_owned_by_core_budget() -> None:
    snapshot_source = (ROOT / "src/codebase_lens/reports/snapshot.py").read_text(encoding="utf-8")
    budget_source = (ROOT / "src/codebase_lens/core/budget.py").read_text(encoding="utf-8")

    assert "size_bytes // 4" not in snapshot_source
    assert "size_bytes // 4" in budget_source
    assert "build_budget_report_payload" in budget_source
