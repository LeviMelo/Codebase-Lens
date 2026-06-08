from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def test_projection_refines_cli_roles_and_recovers_internal_imports() -> None:
    result = run_cbl("pack", "--issue", "projection role import test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads((ROOT / ".codecontext" / "latest" / "handoff_projection.json").read_text(encoding="utf-8"))
    assert payload["schema"]["version"] == 5

    edges = payload["graph"]["representative_edges"]
    assert edges

    base_edges = [edge for edge in edges if "_base_manifest_args" in str(edge["source"])]
    for edge in base_edges:
        assert edge["source_role"] != "cli_handler"
        assert edge["edge_family"] not in {"handler_to_analysis", "cli_handler_to_analysis"}

    run_edges = [edge for edge in edges if str(edge["source"]).split("::")[-1].startswith("_run_")]
    assert run_edges
    for edge in run_edges:
        assert edge["source_role"] == "cli_handler"

    import_edges = [edge for edge in edges if edge["edge_family"] == "import_dependency"]
    assert import_edges
    assert any(edge["kind"] == "internal_import_dependency" for edge in import_edges)
    for edge in import_edges:
        assert edge["target_path"]
        assert edge["target_path"].startswith("src/codebase_lens/")
