from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/core/graph.py": [
        "GraphNode",
        "GraphEdge",
        "EvidenceGraph",
        "evidence_graph_payload",
        "graph_slice_payload",
    ],
    "src/codebase_lens/analyzers/evidence_graph.py": [
        "build_evidence_graph",
    ],
    "src/codebase_lens/reports/graph.py": [
        "write_evidence_graph_reports",
        "render_graph_summary",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


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


def main() -> int:
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    pack = run_cbl("pack", "--issue", "phase 11 evidence graph audit", "--budget", "24000", "--no-archive")
    if pack.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    required_outputs = [
        "evidence_graph.json",
        "graph_summary.md",
        "call_graph.json",
        "module_graph.json",
        "ai_handoff.md",
        "snapshot_index.json",
        "pack_index.json",
    ]

    for name in required_outputs:
        if not (latest / name).is_file():
            fail(f"Missing output: {name}")

    graph = json.loads((latest / "evidence_graph.json").read_text(encoding="utf-8"))
    call_graph = json.loads((latest / "call_graph.json").read_text(encoding="utf-8"))
    module_graph = json.loads((latest / "module_graph.json").read_text(encoding="utf-8"))
    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if len(nodes) < 50:
        fail("evidence_graph.json has unexpectedly few nodes for CBL.")
    if len(edges) < 50:
        fail("evidence_graph.json has unexpectedly few edges for CBL.")

    node_kinds = {node.get("kind") for node in nodes if isinstance(node, dict)}
    edge_kinds = {edge.get("kind") for edge in edges if isinstance(edge, dict)}

    for kind in ["repository", "file", "module", "symbol", "cli_command", "test"]:
        if kind not in node_kinds:
            fail(f"evidence_graph.json missing node kind: {kind}")

    for kind in ["repository_contains_file", "file_contains_symbol", "file_imports_module", "symbol_calls_name", "symbol_calls_symbol"]:
        if kind not in edge_kinds:
            fail(f"evidence_graph.json missing edge kind: {kind}")

    edge_ids = [edge.get("id") for edge in edges if isinstance(edge, dict)]
    if len(edge_ids) != len(set(edge_ids)):
        fail("evidence_graph.json contains duplicate edge IDs.")

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("kind") == "symbol_calls_symbol" and not edge.get("target"):
            fail("symbol_calls_symbol edge missing target.")
        if edge.get("kind") == "symbol_calls_name" and edge.get("target") is not None:
            fail("symbol_calls_name edge should preserve unresolved call text rather than pretending a target.")

    if not call_graph.get("edges"):
        fail("call_graph.json contains no edges.")
    if not module_graph.get("edges"):
        fail("module_graph.json contains no edges.")

    summary = (latest / "graph_summary.md").read_text(encoding="utf-8")
    for marker in ["# CBL Evidence Graph Summary", "## Node Kinds", "## Edge Kinds", "## Follow-Up Commands"]:
        if marker not in summary:
            fail(f"graph_summary.md missing marker: {marker}")

    outputs = snapshot_index.get("outputs", {})
    for key in ["evidence_graph_json", "graph_summary_md", "call_graph_json", "module_graph_json"]:
        if key not in outputs:
            fail(f"snapshot_index outputs missing {key}")

    if "C:\\Users\\" in summary:
        fail("graph_summary.md leaked an absolute Windows user path.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 11 evidence graph audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
