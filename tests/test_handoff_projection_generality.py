from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

FORBIDDEN_FAMILIES = {
    "pack_snapshot_flow",
    "evidence_graph_flow",
    "symbol_graph_flow",
    "graph_query_flow",
    "cli_orchestration",
    "reporting_manifest",
}


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


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "acme_repo"
    package = repo / "src" / "acme_tool"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

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


def test_projection_uses_generic_heuristics_on_synthetic_non_cbl_repo(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("pack", "--repo", str(repo), "--issue", "synthetic generic repo", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    projection = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    assert "src/acme_tool/" in projection
    assert "codebase_lens" not in projection
    assert "src/acme_tool/" in payload["project_profile"]["source_prefixes"]

    families = {edge["edge_family"] for edge in payload["graph"]["representative_edges"]}
    assert families
    assert not (families & FORBIDDEN_FAMILIES)
    assert families & {
        "handler_to_analysis",
        "analysis_to_report",
        "cli_to_handler",
        "import_dependency",
        "other_product_flow",
    }

    edge_blob = json.dumps(payload["graph"]["representative_edges"], sort_keys=True)
    assert "src/acme_tool/" in edge_blob
    assert "codebase_lens" not in edge_blob
