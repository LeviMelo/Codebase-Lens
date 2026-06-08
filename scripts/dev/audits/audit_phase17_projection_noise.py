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

    result = run_cbl("pack", "--issue", "phase 17 projection noise audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    representative = section(text, "Representative Dependency Edges")
    unresolved = section(text, "Dynamic / Unresolved Calls")

    if "pathlib" in representative:
        fail("Representative edges still surface stdlib pathlib import.")
    if "`file_imports_module`: `src/" in representative and "target_path\": \"\"" in json.dumps(payload.get("graph", {}).get("representative_edges", [])):
        fail("Representative edges include unresolved/external imports as first-class dependencies.")

    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])
    if not edges:
        fail("No representative edges were emitted.")

    for edge in edges:
        if edge.get("kind") in {"file_imports_module", "module_resolves_to_file"} and not edge.get("target_path"):
            fail(f"External/unresolved import selected as representative edge: {edge}")
        if edge.get("edge_family") == "external_import_dependency":
            fail(f"External import dependency should be fallback-only and absent in this repo: {edge}")

    if "actual_dispatch_calls" not in graph:
        fail("Projection JSON missing actual_dispatch_calls.")
    if "reflective_attribute_reads" not in graph:
        fail("Projection JSON missing reflective_attribute_reads.")
    if "omitted_repetitive_reflection_count" not in graph:
        fail("Projection JSON missing omitted_repetitive_reflection_count.")

    dynamic = graph.get("dynamic_or_dispatch_calls", [])
    actual = graph.get("actual_dispatch_calls", [])
    reflective = graph.get("reflective_attribute_reads", [])

    if dynamic != actual:
        fail("dynamic_or_dispatch_calls should be a compatibility alias for actual_dispatch_calls.")

    for item in actual:
        if item.get("target_text") in {"getattr", "hasattr", "setattr", "delattr"}:
            fail(f"Reflective call leaked into actual dispatch calls: {item}")

    if len(reflective) > 3:
        fail("Reflective attribute reads are not capped.")

    if graph.get("omitted_repetitive_reflection_count", 0) < 1:
        fail("Repetitive reflective reads were not counted as omitted.")

    if "Reflective attribute reads" not in unresolved:
        fail("Markdown does not summarize capped reflective attribute reads.")
    if unresolved.count("getattr") > 3:
        fail("Markdown still over-displays repeated getattr calls.")

    print("PASS: Phase 17 projection noise audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
