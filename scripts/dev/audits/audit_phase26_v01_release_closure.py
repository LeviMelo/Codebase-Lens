from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
SRC = ROOT / "src"


@dataclass(frozen=True)
class ReleaseCheck:
    name: str
    command: list[str]
    returncode: int
    duration_seconds: float
    stdout_tail: str
    stderr_tail: str


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def run_command(name: str, command: list[str]) -> ReleaseCheck:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )
    duration = round(time.perf_counter() - started, 3)

    return ReleaseCheck(
        name=name,
        command=command,
        returncode=result.returncode,
        duration_seconds=duration,
        stdout_tail=result.stdout[-3000:],
        stderr_tail=result.stderr[-3000:],
    )


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def assert_file_contains(relative: str, required: list[str]) -> None:
    path = ROOT / relative
    if not path.is_file():
        fail(f"Required release file is missing: {relative}")

    text = path.read_text(encoding="utf-8")
    missing = [item for item in required if item not in text]
    if missing:
        fail(f"{relative} is missing required release text: {missing}")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"Expected JSON artifact is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"Expected JSON object in artifact: {path}")
    return value


def write_release_report(checks: list[ReleaseCheck], *, skipped_pytest: bool) -> Path:
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    failures = [check for check in checks if check.returncode != 0]
    payload = {
        "schema": {
            "name": "cbl.v01_release_closure",
            "version": 1,
        },
        "ok": not failures,
        "skipped_pytest": skipped_pytest,
        "counts": {
            "checks": len(checks),
            "failures": len(failures),
            "passed": len(checks) - len(failures),
        },
        "checks": [asdict(check) for check in checks],
    }

    stable_path, _latest_path = write_audit_report_pair(ROOT, "v01_release_closure", payload)
    return stable_path


def assert_latest_artifacts() -> None:
    latest = ROOT / ".codecontext" / "latest"

    required = [
        "manifest.json",
        "contract_audit.json",
        "contract_audit.md",
        "contract_report.json",
    ]

    for filename in required:
        if not (latest / filename).is_file():
            fail(f"Missing latest release artifact after contract check: {filename}")

    payload = load_json(latest / "contract_audit.json")
    if payload.get("schema", {}).get("name") != "cbl.contract_audit":
        fail("contract_audit.json has wrong schema name.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-pytest", action="store_true", help="Skip full pytest run for non-recursive test contexts.")
    args = parser.parse_args(argv)

    for relative in [
        "scripts/dev/audits/audit_phase26_v01_release_closure.py",
        "tests/test_v01_release_closure.py",
    ]:
        assert_parseable(relative)

    assert_file_contains(
        "docs/V0_1_RELEASE_STATUS.md",
        [
            "CBL v0.1 Release Status",
            "Implemented Public Command Surface",
            "Canonical v0.1 Report Outputs",
            "Safety Invariants",
            "Release Gates",
            "Known v0.1 Boundaries",
        ],
    )

    checks: list[ReleaseCheck] = []

    commands: list[tuple[str, list[str]]] = [
        ("phase25_report_contract_parity", [sys.executable, "scripts/dev/audits/audit_phase25_report_contract_parity.py"]),
        ("phase24_documentation_workflow", [sys.executable, "scripts/dev/audits/audit_phase24_documentation_workflow.py"]),
        ("phase23_audit_report_sanitization", [sys.executable, "scripts/dev/audits/audit_phase23_audit_report_sanitization.py"]),
        ("phase22_release_safety", [sys.executable, "scripts/dev/audits/audit_phase22_release_safety.py"]),
        ("phase21_release_fixture_matrix", [sys.executable, "scripts/dev/audits/audit_phase21_release_fixture_matrix.py"]),
        ("phase20_public_command_stability", [sys.executable, "scripts/dev/audits/audit_phase20_public_command_stability.py"]),
        ("contract", [sys.executable, "-m", "codebase_lens", "contract", "--no-archive"]),
        ("snapshot_smoke", [sys.executable, "-m", "codebase_lens", "snapshot", "--budget", "24000", "--no-archive"]),
        ("pack_smoke", [sys.executable, "-m", "codebase_lens", "pack", "--issue", "v0.1 release closure smoke", "--budget", "24000", "--no-archive"]),
        ("graph_smoke", [sys.executable, "-m", "codebase_lens", "graph", "--symbol", "write_handoff_pack", "--depth", "1", "--limit", "60", "--no-archive"]),
        ("diff_smoke", [sys.executable, "-m", "codebase_lens", "diff", "--symbols", "--no-archive"]),
    ]

    if not args.skip_pytest:
        commands.append(("pytest", [sys.executable, "-m", "pytest"]))

    commands.append(("git_diff_check", ["git", "diff", "--check"]))

    for name, command in commands:
        check = run_command(name, command)
        checks.append(check)
        status = "PASS" if check.returncode == 0 else "FAIL"
        print(f"{status}: {name} ({check.duration_seconds}s)")

        if check.returncode != 0:
            print(check.stdout_tail)
            print(check.stderr_tail)
            report_path = write_release_report(checks, skipped_pytest=args.skip_pytest)
            fail(f"Release closure failed at {name}. Report: {report_path}")

        if name == "contract":
            assert_latest_artifacts()

    report_path = write_release_report(checks, skipped_pytest=args.skip_pytest)

    print("PASS: Phase 26 v0.1 release closure audit passed.")
    print(f"Stable release report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
