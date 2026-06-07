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
    "src/codebase_lens/analyzers/symbol_graph.py": [
        "SymbolGraphNode",
        "SymbolGraphResult",
        "collect_symbol_graph",
        "symbol_graph_payload",
        "render_symbol_graph_markdown",
    ],
    "src/codebase_lens/reports/symbol_graph.py": [
        "write_symbol_graph_reports",
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

    pack = run_cbl("pack", "--issue", "phase 10 symbol graph audit", "--budget", "20000", "--no-archive")
    if pack.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")
    if "CBL pack: OK" not in pack.stdout:
        fail("pack did not report success.")

    latest = ROOT / ".codecontext" / "latest"
    graph_json = latest / "symbol_graph.json"
    graph_md = latest / "symbol_graph.md"
    handoff = latest / "ai_handoff.md"

    for path in [graph_json, graph_md, handoff]:
        if not path.is_file():
            fail(f"Missing expected output: {path.name}")

    payload = json.loads(graph_json.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", [])
    if not nodes:
        fail("symbol_graph.json has no nodes for the CBL repository.")

    names = {node.get("qualified_name") for node in nodes if isinstance(node, dict)}
    required_names = {"write_handoff_pack", "write_snapshot_bundle", "collect_symbol_graph"}
    missing_names = required_names - names
    if missing_names:
        fail(f"symbol_graph.json missing expected symbols: {sorted(missing_names)}")

    handoff_text = handoff.read_text(encoding="utf-8")
    for marker in [
        "## Symbol Relationship Graph",
        "symbol_graph.json",
        "Function I/O and static calls",
        "phase 10 symbol graph audit",
    ]:
        if marker not in handoff_text:
            fail(f"ai_handoff.md missing marker: {marker}")

    if "C:\\Users\\" in handoff_text:
        fail("ai_handoff.md leaked an absolute Windows user path.")

    first_src_symbol = min(
        [handoff_text.find(token) for token in ["### `write_snapshot_bundle`", "### `write_handoff_pack`", "### `build_parser`"] if handoff_text.find(token) != -1],
        default=-1,
    )
    first_fail = handoff_text.find("### `fail`")

    if first_src_symbol == -1:
        fail("ai_handoff.md does not surface a core src/ symbol in the visible symbol graph excerpt.")

    if first_fail != -1 and first_fail < first_src_symbol:
        fail("ai_handoff.md is still front-loaded with audit helper noise before product symbols.")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("simple_name") != "fail":
            continue
        node_path = node.get("path")
        for caller in node.get("called_by", []):
            if isinstance(caller, dict) and caller.get("path") != node_path:
                fail("symbol_graph.json still contains cross-file false caller edges for helper function fail().")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 10 symbol graph audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
