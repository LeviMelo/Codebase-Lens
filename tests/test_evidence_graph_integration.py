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


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "graph_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'graph-repo'\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")

    (package / "service.py").write_text(
        "\n".join(
            [
                "from demo.util import double",
                "",
                "def transform(value: int) -> int:",
                "    return double(value) + 1",
                "",
                "def run(value: int) -> int:",
                "    return transform(value)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (package / "util.py").write_text(
        "\n".join(
            [
                "def double(value: int) -> int:",
                "    return value * 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_service.py").write_text(
        "\n".join(
            [
                "from demo.service import transform",
                "",
                "def test_transform():",
                "    assert transform(2) == 5",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_pack_writes_normalized_evidence_graph(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("pack", "--repo", str(repo), "--issue", "evidence graph test", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    evidence_graph = latest / "evidence_graph.json"
    call_graph = latest / "call_graph.json"
    module_graph = latest / "module_graph.json"
    graph_summary = latest / "graph_summary.md"

    for path in [evidence_graph, call_graph, module_graph, graph_summary]:
        assert path.is_file(), path

    payload = json.loads(evidence_graph.read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    edges = payload["edges"]

    node_kinds = {node["kind"] for node in nodes}
    edge_kinds = {edge["kind"] for edge in edges}

    assert {"repository", "file", "module", "symbol", "test"}.issubset(node_kinds)
    assert "file_contains_symbol" in edge_kinds
    assert "file_imports_module" in edge_kinds
    assert "symbol_calls_name" in edge_kinds
    assert "symbol_calls_symbol" in edge_kinds

    labels = {node["label"] for node in nodes}
    assert "transform" in labels
    assert "double" in labels

    call_edges = [
        edge
        for edge in edges
        if edge["kind"] == "symbol_calls_symbol"
    ]
    assert call_edges
    assert len({edge["id"] for edge in call_edges}) == len(call_edges)

    summary = graph_summary.read_text(encoding="utf-8")
    assert "# CBL Evidence Graph Summary" in summary
    assert "## Follow-Up Commands" in summary


def test_snapshot_index_exposes_evidence_graph_outputs(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("snapshot", "--repo", str(repo), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))

    outputs = snapshot_index["outputs"]
    assert outputs["evidence_graph_json"] == ".codecontext/latest/evidence_graph.json"
    assert outputs["call_graph_json"] == ".codecontext/latest/call_graph.json"
    assert outputs["module_graph_json"] == ".codecontext/latest/module_graph.json"
    assert outputs["graph_summary_md"] == ".codecontext/latest/graph_summary.md"

    counts = snapshot_index["counts"]
    assert counts["evidence_graph_nodes"] > 0
    assert counts["evidence_graph_edges"] > 0
