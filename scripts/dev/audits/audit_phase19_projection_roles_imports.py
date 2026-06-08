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
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 19 projection role/import audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    if payload.get("schema", {}).get("version") != 5:
        fail("handoff_projection schema version was not advanced to 5.")

    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])

    if not edges:
        fail("No representative edges emitted.")

    base_manifest_edges = [
        edge
        for edge in edges
        if "_base_manifest_args" in str(edge.get("source"))
    ]
    for edge in base_manifest_edges:
        if edge.get("source_role") == "cli_handler":
            fail(f"_base_manifest_args incorrectly classified as cli_handler: {edge}")
        if edge.get("edge_family") in {"handler_to_analysis", "cli_handler_to_analysis"}:
            fail(f"_base_manifest_args incorrectly emitted as handler edge: {edge}")

    if base_manifest_edges and not any(
        edge.get("edge_family") in {"cli_support_to_analysis", "cli_support_to_io_or_config"}
        for edge in base_manifest_edges
    ):
        fail(f"_base_manifest_args did not receive a CLI support family: {base_manifest_edges}")

    handler_edges = [
        edge
        for edge in edges
        if str(edge.get("source")).split("::")[-1].startswith("_run_")
    ]
    if not handler_edges:
        fail("No _run_* CLI handler edge was selected.")

    for edge in handler_edges:
        if edge.get("source_role") != "cli_handler":
            fail(f"_run_* source not classified as cli_handler: {edge}")
        if edge.get("edge_family") not in {
            "cli_handler_to_analysis",
            "report_to_output_writer",
            "other_product_flow",
            "cli_support_to_analysis",
        }:
            fail(f"_run_* source received unexpected family: {edge}")

    import_edges = [
        edge
        for edge in edges
        if edge.get("edge_family") == "import_dependency"
    ]
    if not import_edges:
        fail("No import_dependency edge was selected.")

    for edge in import_edges:
        if edge.get("kind") == "file_imports_module" and not edge.get("target_path"):
            fail(f"Unresolved/external import was surfaced as internal import dependency: {edge}")
        if not edge.get("target_path"):
            fail(f"Import dependency lacks target_path: {edge}")
        if not str(edge.get("target_path")).startswith("src/codebase_lens/"):
            fail(f"Import dependency target is not a product path: {edge}")

    if not any(edge.get("kind") == "internal_import_dependency" for edge in import_edges):
        fail("No recovered internal import dependency was selected.")

    print("PASS: Phase 19 projection role/import audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
