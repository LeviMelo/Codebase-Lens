from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


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


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start == -1:
        fail(f"Missing section: {heading}")
    next_start = text.find("\n## ", start + len(marker))
    if next_start == -1:
        return text[start:]
    return text[start:next_start]


def main() -> int:
    for relative in [
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 14 projection relevance audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    projection_path = latest / "handoff_projection.md"
    projection_json_path = latest / "handoff_projection.json"

    if not projection_path.is_file():
        fail("handoff_projection.md was not generated.")
    if not projection_json_path.is_file():
        fail("handoff_projection.json was not generated.")

    text = projection_path.read_text(encoding="utf-8")
    payload = json.loads(projection_json_path.read_text(encoding="utf-8"))

    representative = section(text, "Representative Dependency Edges")
    unresolved = section(text, "Dynamic / Unresolved Calls")
    symbols = section(text, "High-Connectivity Product Symbols")

    if "src/codebase_lens/" not in representative:
        fail("Representative edges do not surface product code.")
    if "scripts/dev/audits/" in representative:
        fail("Representative edges are polluted by audit helper files.")
    if "`fail`" in representative or "`run_cbl`" in representative or "`names_in_file`" in representative:
        fail("Representative edges include low-value audit helper symbols.")

    if "scripts/dev/audits/" in unresolved:
        fail("Unresolved calls are polluted by audit helper files.")
    if "`print`" in unresolved or "`SystemExit`" in unresolved:
        fail("Unresolved calls include low-value builtins/audit exits.")

    if "write_snapshot_bundle" not in symbols and "write_handoff_pack" not in symbols and "build_evidence_graph" not in symbols:
        fail("High-connectivity product symbols do not surface core orchestration symbols.")

    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])
    unresolved_json = graph.get("unresolved_static_calls", [])

    if not isinstance(edges, list) or not edges:
        fail("handoff_projection.json has no representative edges.")

    for edge in edges[:10]:
        blob = json.dumps(edge, sort_keys=True)
        if "scripts/dev/audits/" in blob:
            fail("handoff_projection.json representative edges include audit paths.")

    for call in unresolved_json[:10]:
        blob = json.dumps(call, sort_keys=True)
        if "scripts/dev/audits/" in blob:
            fail("handoff_projection.json unresolved calls include audit paths.")

    print("PASS: Phase 14 projection relevance audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
