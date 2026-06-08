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


def test_v01_release_status_document_exists_and_names_release_gates() -> None:
    path = ROOT / "docs" / "V0_1_RELEASE_STATUS.md"

    assert path.is_file()
    text = path.read_text(encoding="utf-8")

    for required in [
        "CBL v0.1 Release Status",
        "Implemented Public Command Surface",
        "Canonical v0.1 Report Outputs",
        "Safety Invariants",
        "Release Gates",
        "Known v0.1 Boundaries",
        "audit_phase26_v01_release_closure.py",
    ]:
        assert required in text


def test_v01_release_closure_audit_passes_without_recursive_pytest() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/dev/audits/audit_phase26_v01_release_closure.py",
            "--skip-pytest",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Phase 26 v0.1 release closure audit passed." in result.stdout

    report = ROOT / ".codecontext" / "audits" / "v01_release_closure.json"
    assert report.is_file()

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema"]["name"] == "cbl.v01_release_closure"
    assert payload["ok"] is True
    assert payload["skipped_pytest"] is True
    assert payload["counts"]["failures"] == 0
