from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
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


def test_projection_deduplicates_edges_and_balances_coverage() -> None:
    result = run_cbl("pack", "--issue", "projection dedup balance test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    assert payload["schema"]["version"] >= 4

    edges = payload["graph"]["representative_edges"]
    assert edges

    keys = [
        (
            edge["kind"],
            edge["source"],
            edge["target"],
            edge["edge_family"],
        )
        for edge in edges
    ]
    assert len(keys) == len(set(keys))

    for edge in edges:
        assert "evidence_count" in edge
        assert "sample_evidence" in edge
        assert edge["evidence_count"] >= 1
        assert isinstance(edge["sample_evidence"], list)

    families = Counter(edge["edge_family"] for edge in edges)
    assert families["report_to_output_writer"] <= 2
    assert families["declaration_context"] <= 1
    assert families["handler_to_analysis"] <= 4

    representative = text[text.index("## Representative Dependency Edges"):text.index("## Dynamic / Unresolved Calls")]
    assert "Evidence count:" in representative

    top_six = json.dumps(payload["graph"]["high_connectivity_product_symbols"][:6], sort_keys=True)
    assert "handoff_projection.py::_render_projection_markdown" not in top_six
