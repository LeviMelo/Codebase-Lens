from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_exposes_cbl_console_script() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" in text
    assert 'cbl = "codebase_lens.cli:main"' in text


def test_installation_docs_cover_powershell_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")

    for needle in (
        "python -m pip install -e .",
        "cbl doctor",
        "cbl pack",
        "cbl dump",
        "cbl diffdump",
        "CBL is local-only and does not upload your code.",
        "Review generated AI handoff reports before sharing them.",
    ):
        assert needle in readme

    assert "Get-Command cbl" in installation
    assert "conda run -n cbl-dev cbl" in installation


def test_phase30_audit_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dev" / "audits" / "audit_phase30_installation_docs.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Phase 30 installation and documentation audit passed." in result.stdout
