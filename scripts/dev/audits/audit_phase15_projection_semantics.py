from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections import Counter
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

    result = run_cbl("pack", "--issue", "phase 15 projection semantics audit", "--budget", "24000", "--no-archive")
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

    if "src/codebase_lens/" not in representative:
        fail("Representative edges do not surface product code.")
    if "::" not in representative:
        fail("Representative edges do not path-qualify symbol display.")
    if "scripts/dev/audits/" in representative:
        fail("Representative edges are polluted by audit helper files.")
    if "`fail`" in representative or "`run_cbl`" in representative or "`names_in_file`" in representative:
        fail("Representative edges include low-value audit helper symbols.")
    if "Family:" not in representative or "reason:" not in representative or "score:" not in representative:
        fail("Representative edges do not expose selection metadata.")

    if "scripts/dev/audits/" in unresolved:
        fail("Unresolved calls are polluted by audit helper files.")
    if "`print`" in unresolved or "`SystemExit`" in unresolved:
        fail("Unresolved calls include low-value builtins/audit exits.")

    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])
    if not isinstance(edges, list) or not edges:
        fail("handoff_projection.json has no representative edges.")

    required_edge_fields = {"edge_family", "selection_reason", "relevance_score", "source_path", "target_path"}
    for edge in edges[:10]:
        missing = required_edge_fields - set(edge)
        if missing:
            fail(f"Representative edge missing fields: {sorted(missing)}")
        blob = json.dumps(edge, sort_keys=True)
        if "scripts/dev/audits/" in blob:
            fail("handoff_projection.json representative edges include audit paths.")

    family_counts = Counter(str(edge.get("edge_family")) for edge in edges)
    if family_counts["cli_orchestration"] > 4:
        fail("Representative edges overuse cli_orchestration family.")
    if family_counts["reporting_manifest"] > 4:
        fail("Representative edges overuse reporting_manifest family.")

    if "dynamic_or_dispatch_calls" not in graph:
        fail("Projection JSON missing dynamic_or_dispatch_calls.")
    if "external_library_calls" not in graph:
        fail("Projection JSON missing external_library_calls.")
    if "attribute_or_external_calls" not in graph:
        fail("Projection JSON missing attribute_or_external_calls.")
    if "omitted_low_value_unresolved_call_count" not in graph:
        fail("Projection JSON missing omitted low-value unresolved call count.")

    if "External/library calls summarized" not in unresolved and graph.get("external_library_calls"):
        fail("Markdown does not summarize external/library calls.")

    if graph.get("omitted_low_value_unresolved_call_count", 0) < 1:
        fail("Projection did not count omitted low-value unresolved calls.")

    print("PASS: Phase 15 projection semantics audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
