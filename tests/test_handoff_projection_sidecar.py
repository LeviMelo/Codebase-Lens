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
    repo = tmp_path / "projection_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'projection-repo'\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")

    (package / "app.py").write_text(
        "\n".join(
            [
                "from demo.service import transform",
                "",
                "def main() -> int:",
                "    return transform(2)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (package / "service.py").write_text(
        "\n".join(
            [
                "def transform(value: int) -> int:",
                "    return value + 1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_app.py").write_text(
        "\n".join(
            [
                "from demo.app import main",
                "",
                "def test_main():",
                "    assert main() == 3",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_pack_writes_handoff_projection_sidecar_without_rewriting_legacy_handoff(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("pack", "--repo", str(repo), "--issue", "projection sidecar", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    handoff = latest / "ai_handoff.md"
    projection_md = latest / "handoff_projection.md"
    projection_json = latest / "handoff_projection.json"
    pack_index = latest / "pack_index.json"

    assert handoff.is_file()
    assert projection_md.is_file()
    assert projection_json.is_file()
    assert pack_index.is_file()

    legacy_text = handoff.read_text(encoding="utf-8")
    projection_text = projection_md.read_text(encoding="utf-8")

    assert "# CBL AI Handoff Pack" in legacy_text
    assert "# CBL Handoff Projection" in projection_text
    assert "The legacy `ai_handoff.md` is preserved unchanged." in projection_text
    assert "evidence_graph.json" in projection_text
    assert "cbl graph --symbol <symbol> --depth 2" in projection_text
    assert "# CBL Symbol Relationship Graph\n\nEvidence scope:" not in projection_text

    payload = json.loads(projection_json.read_text(encoding="utf-8"))
    assert payload["schema"]["name"] == "cbl.handoff_projection"
    assert payload["counts"]["evidence_graph_nodes"] > 0
    assert payload["counts"]["evidence_graph_edges"] > 0

    index = json.loads(pack_index.read_text(encoding="utf-8"))
    assert index["outputs"]["handoff_projection_md"] == ".codecontext/latest/handoff_projection.md"
    assert index["outputs"]["handoff_projection_json"] == ".codecontext/latest/handoff_projection.json"


def test_changed_pack_projection_reports_changed_scope(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, text=True, capture_output=True, check=False)

    result = run_cbl("pack", "--repo", str(repo), "--changed", "--issue", "clean changed projection", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    projection_text = (repo / ".codecontext" / "latest" / "handoff_projection.md").read_text(encoding="utf-8")
    assert "## Changed Scope" in projection_text
    assert "No Git changes detected for this changed-only pack." in projection_text

    payload = json.loads((repo / ".codecontext" / "latest" / "handoff_projection.json").read_text(encoding="utf-8"))
    assert payload["changed_scope"]["empty_changed_scope"] is True
