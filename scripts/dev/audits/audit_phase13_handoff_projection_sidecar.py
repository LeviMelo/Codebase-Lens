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


def main() -> int:
    for relative in [
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 13 sidecar projection audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    for name in ["ai_handoff.md", "handoff_projection.md", "handoff_projection.json", "pack_index.json", "evidence_graph.json"]:
        if not (latest / name).is_file():
            fail(f"Missing expected output: {name}")

    legacy = (latest / "ai_handoff.md").read_text(encoding="utf-8")
    projection = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))
    pack_index = json.loads((latest / "pack_index.json").read_text(encoding="utf-8"))

    if "# CBL AI Handoff Pack" not in legacy:
        fail("Legacy ai_handoff.md title was not preserved.")

    required_sections = [
        "# CBL Handoff Projection",
        "## Purpose",
        "## Repository State",
        "## Budget",
        "## Evidence Graph Summary",
        "## Entrypoints",
        "## High-Connectivity Product Symbols",
        "## Representative Dependency Edges",
        "## Dynamic / Unresolved Calls",
        "## Changed Scope",
        "## Follow-Up Commands",
        "## Sidecar Artifacts",
    ]
    for marker in required_sections:
        if marker not in projection:
            fail(f"handoff_projection.md missing section: {marker}")

    required_phrases = [
        "The legacy `ai_handoff.md` is preserved unchanged.",
        "evidence_graph.json",
        "symbol_graph.json",
        "cbl graph --symbol <symbol> --depth 2",
    ]
    for phrase in required_phrases:
        if phrase not in projection:
            fail(f"handoff_projection.md missing phrase: {phrase}")

    if "# CBL Symbol Relationship Graph\n\nEvidence scope:" in projection:
        fail("handoff_projection.md pasted the raw symbol graph.")

    if "C:\\Users\\" in projection:
        fail("handoff_projection.md leaked an absolute Windows user path.")

    if len(projection.splitlines()) > 260:
        fail("handoff_projection.md is too large for a sidecar projection.")

    outputs = pack_index.get("outputs", {})
    for key in ["handoff_projection_md", "handoff_projection_json"]:
        if key not in outputs:
            fail(f"pack_index outputs missing {key}")

    if payload.get("schema", {}).get("name") != "cbl.handoff_projection":
        fail("handoff_projection.json has wrong schema name.")

    if payload.get("counts", {}).get("evidence_graph_nodes", 0) <= 0:
        fail("handoff_projection.json did not capture evidence graph node count.")

    changed = run_cbl("pack", "--changed", "--issue", "phase 13 clean changed projection audit", "--budget", "24000", "--no-archive")
    if changed.returncode != 0:
        fail(f"changed cbl pack failed:\nSTDOUT:\n{changed.stdout}\nSTDERR:\n{changed.stderr}")

    changed_projection = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    if "## Changed Scope" not in changed_projection:
        fail("changed projection missing changed scope section.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 13 handoff projection sidecar audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
