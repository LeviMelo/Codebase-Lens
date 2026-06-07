from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


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
    repo = tmp_path / "graph_query_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'graph-query-repo'\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")

    (package / "service.py").write_text(
        "\n".join(
            [
                "from demo.util import double",
                "",
                "def transform(value: int) -> int:",
                "    return double(value) + 1",
                "",
                "def run(value: int) -> int:",
                "    return transform(value)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (package / "util.py").write_text(
        "\n".join(
            [
                "def double(value: int) -> int:",
                "    return value * 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_service.py").write_text(
        "\n".join(
            [
                "from demo.service import transform",
                "",
                "def test_transform():",
                "    assert transform(2) == 5",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_graph_command_queries_symbol_neighborhood(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("graph", "--repo", str(repo), "--symbol", "transform", "--depth", "2", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL graph: OK" in result.stdout

    latest = repo / ".codecontext" / "latest"
    query_json = latest / "graph_query.json"
    query_md = latest / "graph_query.md"
    evidence_graph = latest / "evidence_graph.json"

    assert query_json.is_file()
    assert query_md.is_file()
    assert evidence_graph.is_file()

    payload = json.loads(query_json.read_text(encoding="utf-8"))
    labels = {node["label"] for node in payload["nodes"]}

    assert "transform" in labels
    assert "double" in labels or "run" in labels
    assert payload["counts"]["nodes"] > 0
    assert payload["counts"]["edges"] > 0

    markdown = query_md.read_text(encoding="utf-8")
    assert "# CBL Graph Query" in markdown
    assert "## Follow-Up Commands" in markdown
    assert "transform" in markdown


def test_graph_command_reports_empty_match_without_failure(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("graph", "--repo", str(repo), "--symbol", "does_not_exist", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads((repo / ".codecontext" / "latest" / "graph_query.json").read_text(encoding="utf-8"))
    assert payload["counts"]["nodes"] == 0
    assert payload["warnings"] == ["No graph nodes matched the requested query."]
