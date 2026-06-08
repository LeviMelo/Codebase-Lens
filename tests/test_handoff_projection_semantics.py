from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
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


def test_handoff_projection_adds_semantic_edge_metadata_and_filters_low_value_calls() -> None:
    result = run_cbl("pack", "--issue", "projection semantics test", "--budget", "24000", "--no-archive")
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
    assert "::" in representative
    assert "Family:" in representative
    assert "reason:" in representative
    assert "score:" in representative
    assert "scripts/dev/audits/" not in representative
    assert "`fail`" not in representative
    assert "`run_cbl`" not in representative

    forbidden_families = {
        "pack_snapshot_flow",
        "evidence_graph_flow",
        "symbol_graph_flow",
        "graph_query_flow",
        "cli_orchestration",
        "reporting_manifest",
    }
    for family in forbidden_families:
        assert family not in representative

    assert "scripts/dev/audits/" not in unresolved
    assert "`print`" not in unresolved
    assert "`SystemExit`" not in unresolved

    graph = payload["graph"]
    edges = graph["representative_edges"]
    assert edges

    for edge in edges:
        assert "edge_family" in edge
        assert "selection_reason" in edge
        assert "relevance_score" in edge
        assert "source_path" in edge
        assert "target_path" in edge
        assert "source_role" in edge
        assert "target_role" in edge
        assert edge["edge_family"] not in forbidden_families

    families = Counter(edge["edge_family"] for edge in edges)
    assert families["cli_to_handler"] <= 4
    assert families["report_to_output_writer"] <= 4
    assert {
        "handler_to_analysis",
        "analysis_to_report",
        "import_dependency",
        "scanner_or_io_flow",
        "analysis_to_model",
        "other_product_flow",
    } & set(families)

    assert "project_profile" in payload
    assert payload["project_profile"]["source_prefixes"]

    assert "dynamic_or_dispatch_calls" in graph
    assert "external_library_calls" in graph
    assert "attribute_or_external_calls" in graph
    assert "omitted_low_value_unresolved_call_count" in graph
    assert graph["omitted_low_value_unresolved_call_count"] >= 1

    for item in graph["dynamic_or_dispatch_calls"]:
        blob = json.dumps(item, sort_keys=True)
        assert "scripts/dev/audits/" not in blob
        assert "SystemExit" not in blob
        assert "print" not in blob
