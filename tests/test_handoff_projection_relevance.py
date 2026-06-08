from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run_cbl(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_handoff_projection_prioritizes_product_edges_over_audit_helpers() -> None:
    result = run_cbl("pack", "--issue", "projection relevance test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    representative_start = text.index("## Representative Dependency Edges")
    unresolved_start = text.index("## Dynamic / Unresolved Calls")
    changed_start = text.index("## Changed Scope")

    representative = text[representative_start:unresolved_start]
    unresolved = text[unresolved_start:changed_start]

    assert "src/codebase_lens/" in representative
    assert "scripts/dev/audits/" not in representative
    assert "`fail`" not in representative
    assert "`run_cbl`" not in representative
    assert "`names_in_file`" not in representative

    assert "scripts/dev/audits/" not in unresolved
    assert "`SystemExit`" not in unresolved
    assert "`print`" not in unresolved

    edges = payload["graph"]["representative_edges"]
    assert edges
    for edge in edges[:10]:
        blob = json.dumps(edge, sort_keys=True)
        assert "scripts/dev/audits/" not in blob

    symbols = payload["graph"]["high_connectivity_product_symbols"]
    labels = {item["label"] for item in symbols}
    assert {"write_snapshot_bundle", "build_evidence_graph", "write_handoff_pack"} & labels
