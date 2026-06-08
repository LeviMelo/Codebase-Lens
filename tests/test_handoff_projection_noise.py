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


def test_projection_suppresses_external_import_and_repetitive_reflection_noise() -> None:
    result = run_cbl("pack", "--issue", "projection noise suppression test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    representative = text[text.index("## Representative Dependency Edges"):text.index("## Dynamic / Unresolved Calls")]
    unresolved = text[text.index("## Dynamic / Unresolved Calls"):text.index("## Changed Scope")]
    graph = payload["graph"]

    assert "pathlib" not in representative

    for edge in graph["representative_edges"]:
        if edge["kind"] in {"file_imports_module", "module_resolves_to_file"}:
            assert edge["target_path"], edge
        assert edge["edge_family"] != "external_import_dependency"

    assert "actual_dispatch_calls" in graph
    assert "reflective_attribute_reads" in graph
    assert "omitted_repetitive_reflection_count" in graph
    assert graph["dynamic_or_dispatch_calls"] == graph["actual_dispatch_calls"]

    for item in graph["actual_dispatch_calls"]:
        assert item["target_text"] not in {"getattr", "hasattr", "setattr", "delattr"}

    assert len(graph["reflective_attribute_reads"]) <= 3
    assert graph["omitted_repetitive_reflection_count"] >= 1

    assert "Reflective attribute reads" in unresolved
    assert unresolved.count("getattr") <= 3
