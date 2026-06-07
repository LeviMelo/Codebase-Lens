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
    "src/codebase_lens/analyzers/graph_query.py": [
        "GraphQueryResult",
        "query_evidence_graph_payload",
        "graph_query_payload",
    ],
    "src/codebase_lens/reports/graph_query.py": [
        "write_graph_query_reports",
        "render_graph_query_markdown",
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

    constants_text = (ROOT / "src" / "codebase_lens" / "core" / "constants.py").read_text(encoding="utf-8")
    if "\"graph\"" not in constants_text and "'graph'" not in constants_text:
        fail("PUBLIC_COMMANDS does not include graph.")

    cli_text = (ROOT / "src" / "codebase_lens" / "cli.py").read_text(encoding="utf-8")
    if "def _run_graph(" not in cli_text:
        fail("cli.py does not define _run_graph().")
    if "graph.set_defaults(handler=_run_graph)" not in cli_text:
        fail("graph parser does not bind handler=_run_graph.")

    help_result = run_cbl("--help")
    if help_result.returncode != 0:
        fail("cbl --help failed.")
    if "graph" not in help_result.stdout:
        fail("cbl --help does not expose graph command.")

    graph = run_cbl("graph", "--symbol", "write_handoff_pack", "--depth", "2", "--budget", "24000", "--no-archive")
    if graph.returncode != 0:
        fail(f"cbl graph failed:\nSTDOUT:\n{graph.stdout}\nSTDERR:\n{graph.stderr}")

    if "CBL graph: OK" not in graph.stdout:
        fail("graph command did not report success.")

    latest = ROOT / ".codecontext" / "latest"
    for name in ["graph_query.json", "graph_query.md", "evidence_graph.json", "graph_summary.md", "manifest.json"]:
        if not (latest / name).is_file():
            fail(f"Missing graph command output: {name}")

    payload = json.loads((latest / "graph_query.json").read_text(encoding="utf-8"))
    labels = {node.get("label") for node in payload.get("nodes", []) if isinstance(node, dict)}

    if "write_handoff_pack" not in labels:
        fail("graph query did not include requested symbol write_handoff_pack.")

    if payload.get("counts", {}).get("edges", 0) <= 0:
        fail("graph query returned no edges for write_handoff_pack.")

    markdown = (latest / "graph_query.md").read_text(encoding="utf-8")
    for marker in ["# CBL Graph Query", "## Nodes", "## Edges", "## Follow-Up Commands"]:
        if marker not in markdown:
            fail(f"graph_query.md missing marker: {marker}")

    if "C:\\Users\\" in markdown:
        fail("graph_query.md leaked an absolute Windows user path.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 12 graph query audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
