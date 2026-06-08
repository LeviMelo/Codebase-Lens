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

    result = run_cbl("pack", "--issue", "phase 18 projection dedup audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))
    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])

    schema_version = int(payload.get("schema", {}).get("version") or 0)
    if schema_version < 4:
        fail(f"handoff_projection schema version regressed below 4: {schema_version}")

    if not edges:
        fail("No representative edges emitted.")

    keys = [
        (
            edge.get("kind"),
            edge.get("source"),
            edge.get("target"),
            edge.get("edge_family"),
        )
        for edge in edges
    ]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        fail(f"Representative edge duplicates remain: {duplicates[:5]}")

    for edge in edges:
        if "evidence_count" not in edge:
            fail(f"Representative edge missing evidence_count: {edge}")
        if "sample_evidence" not in edge:
            fail(f"Representative edge missing sample_evidence: {edge}")
        if int(edge.get("evidence_count") or 0) < 1:
            fail(f"Representative edge has invalid evidence_count: {edge}")
        samples = edge.get("sample_evidence")
        if not isinstance(samples, list):
            fail(f"Representative edge sample_evidence is not a list: {edge}")

    family_counts = Counter(str(edge.get("edge_family")) for edge in edges)
    if family_counts["report_to_output_writer"] > 2:
        fail("report_to_output_writer consumed too many representative slots.")
    if family_counts["declaration_context"] > 1:
        fail("declaration_context consumed too many representative slots.")
    if family_counts["handler_to_analysis"] > 4:
        fail("handler_to_analysis consumed too many representative slots.")

    representative = section(text, "Representative Dependency Edges")
    if "Evidence count:" not in representative:
        fail("Markdown does not surface collapsed evidence counts.")

    report_pairs = [
        (edge.get("source"), edge.get("target"))
        for edge in edges
        if edge.get("edge_family") == "report_to_output_writer"
    ]
    if len(report_pairs) != len(set(report_pairs)):
        fail("Duplicate report writer source-target pairs remain.")

    symbols = graph.get("high_connectivity_product_symbols", [])
    top_six_blob = json.dumps(symbols[:6], sort_keys=True)
    if "handoff_projection.py::_render_projection_markdown" in top_six_blob:
        fail("Projection renderer still appears in the top-six product symbols without projection focus.")

    print("PASS: Phase 18 projection deduplication and coverage audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
