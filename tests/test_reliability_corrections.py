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


def test_reliability_corrections_audit_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/dev/audits/audit_phase27_reliability_corrections.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Phase 27 reliability corrections audit passed." in result.stdout


def test_graph_query_default_mentions_seed_unresolved_mode() -> None:
    source = (ROOT / "src" / "codebase_lens" / "analyzers" / "graph_query.py").read_text(encoding="utf-8")
    assert "unresolved_mode" in source
    assert "seed" in source


def test_file_universe_omissions_compatibility_property_exists() -> None:
    source = (ROOT / "src" / "codebase_lens" / "scanners" / "universe.py").read_text(encoding="utf-8")
    assert "def omissions(self)" in source
    assert "return self.omitted_files" in source
