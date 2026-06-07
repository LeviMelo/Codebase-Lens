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
    repo = tmp_path / "symbol_graph_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'symbol-graph-repo'\n", encoding="utf-8")

    (package / "service.py").write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "",
                "class Worker:",
                "    def run(self, value: int) -> int:",
                "        return transform(value)",
                "",
                "def transform(value: int) -> int:",
                "    output = helper(value)",
                "    return output + 1",
                "",
                "def helper(value: int) -> int:",
                "    return value * 2",
                "",
                "def write_result(path: Path, value: int) -> None:",
                "    path.write_text(str(transform(value)))",
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


def test_pack_writes_symbol_graph_and_handoff_uses_it(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("pack", "--repo", str(repo), "--issue", "graph test", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL pack: OK" in result.stdout

    latest = repo / ".codecontext" / "latest"
    graph_json = latest / "symbol_graph.json"
    graph_md = latest / "symbol_graph.md"
    handoff = latest / "ai_handoff.md"

    assert graph_json.is_file()
    assert graph_md.is_file()
    assert handoff.is_file()

    payload = json.loads(graph_json.read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    by_name = {node["qualified_name"]: node for node in nodes}

    assert "transform" in by_name
    assert "helper" in by_name
    assert "Worker.run" in by_name

    transform = by_name["transform"]
    assert transform["inputs"][0]["name"] == "value"
    assert transform["inputs"][0]["annotation"] == "int"
    assert transform["returns_annotation"] == "int"
    assert any(call["name"] == "helper" for call in transform["calls"])
    assert any(caller["symbol"] == "Worker.run" for caller in transform["called_by"])

    handoff_text = handoff.read_text(encoding="utf-8")
    assert "## Symbol Relationship Graph" in handoff_text
    assert "`transform`" in handoff_text
    assert "`helper`" in handoff_text
    assert "graph test" in handoff_text


def test_changed_pack_on_clean_repo_warns_that_scope_is_empty(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, text=True, capture_output=True, check=False)

    result = run_cbl("pack", "--repo", str(repo), "--changed", "--issue", "clean changed pack", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    handoff = (repo / ".codecontext" / "latest" / "ai_handoff.md").read_text(encoding="utf-8")
    assert "No Git changes detected for this changed-only pack." in handoff
    assert "cbl pack --budget" in handoff
