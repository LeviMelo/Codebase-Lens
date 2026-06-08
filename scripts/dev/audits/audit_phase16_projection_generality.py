from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

FORBIDDEN_FAMILIES = {
    "pack_snapshot_flow",
    "evidence_graph_flow",
    "symbol_graph_flow",
    "graph_query_flow",
    "cli_orchestration",
    "reporting_manifest",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


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


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def make_synthetic_repo(base: Path) -> Path:
    repo = base / "acme_repo"
    package = repo / "src" / "acme_tool"
    tests = repo / "tests"
    package.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'acme-tool'\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "parser.py").write_text(
        "\n".join(
            [
                "import ast",
                "",
                "def parse_file(text: str) -> dict[str, int]:",
                "    tree = ast.parse(text)",
                "    return {'nodes': len(list(ast.walk(tree)))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (package / "reports.py").write_text(
        "\n".join(
            [
                "import json",
                "",
                "def write_report(data: dict[str, int]) -> str:",
                "    return json.dumps(data, sort_keys=True)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (package / "cli.py").write_text(
        "\n".join(
            [
                "import argparse",
                "from acme_tool.parser import parse_file",
                "from acme_tool.reports import write_report",
                "",
                "def run_analyze(text: str) -> str:",
                "    data = parse_file(text)",
                "    return write_report(data)",
                "",
                "def build_parser() -> argparse.ArgumentParser:",
                "    parser = argparse.ArgumentParser()",
                "    sub = parser.add_subparsers(dest='command')",
                "    analyze = sub.add_parser('analyze')",
                "    analyze.set_defaults(handler=run_analyze)",
                "    return parser",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tests / "test_parser.py").write_text(
        "\n".join(
            [
                "from acme_tool.parser import parse_file",
                "",
                "def test_parse_file():",
                "    assert parse_file('x = 1')['nodes'] > 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return repo


def main() -> int:
    for relative in [
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 16 projection generality audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed on CBL repo:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    current_payload = json.loads((ROOT / ".codecontext" / "latest" / "handoff_projection.json").read_text(encoding="utf-8"))
    current_edges = current_payload.get("graph", {}).get("representative_edges", [])
    if not current_edges:
        fail("Current repo projection has no representative edges.")

    for edge in current_edges:
        family = edge.get("edge_family")
        if family in FORBIDDEN_FAMILIES:
            fail(f"Current repo projection still uses project-specific family: {family}")

    synthetic_root = ROOT / ".tmp_projection_generality"
    if synthetic_root.exists():
        import shutil
        shutil.rmtree(synthetic_root)
    synthetic_root.mkdir(parents=True, exist_ok=True)

    repo = make_synthetic_repo(synthetic_root)
    synthetic = run_cbl("pack", "--repo", str(repo), "--issue", "synthetic generic repo", "--budget", "24000", "--no-archive")
    if synthetic.returncode != 0:
        fail(f"cbl pack failed on synthetic repo:\nSTDOUT:\n{synthetic.stdout}\nSTDERR:\n{synthetic.stderr}")

    latest = repo / ".codecontext" / "latest"
    projection = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    if "src/acme_tool/" not in projection:
        fail("Synthetic projection did not surface synthetic product source paths.")
    if "codebase_lens" in projection:
        fail("Synthetic projection leaked CBL package names into projection content.")

    prefixes = payload.get("project_profile", {}).get("source_prefixes", [])
    if "src/acme_tool/" not in prefixes:
        fail(f"Synthetic projection did not infer source prefix src/acme_tool/: {prefixes}")

    families = {
        edge.get("edge_family")
        for edge in payload.get("graph", {}).get("representative_edges", [])
    }
    if not families:
        fail("Synthetic projection has no representative edge families.")
    if families & FORBIDDEN_FAMILIES:
        fail(f"Synthetic projection contains forbidden project-specific families: {sorted(families & FORBIDDEN_FAMILIES)}")

    expected_generic = {
        "handler_to_analysis",
        "analysis_to_report",
        "cli_to_handler",
        "import_dependency",
        "other_product_flow",
    }
    if not (families & expected_generic):
        fail(f"Synthetic projection does not contain generic edge families: {sorted(families)}")

    print("PASS: Phase 16 projection generality audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
