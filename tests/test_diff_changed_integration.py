from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def make_changed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "changed_repo"
    repo.mkdir()

    run_git(repo, "init")
    run_git(repo, "config", "user.email", "cbl@example.invalid")
    run_git(repo, "config", "user.name", "CBL Test")

    (repo / ".gitignore").write_text(".codecontext/\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'changed-repo'\n", encoding="utf-8")
    (repo / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    return 1",
                "",
                "def beta():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    run_git(repo, "add", ".")
    commit = run_git(repo, "commit", "-m", "initial")
    assert commit.returncode == 0, commit.stdout + commit.stderr

    (repo / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    value = 10",
                "    return value",
                "",
                "def beta():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "new_module.py").write_text(
        "\n".join(
            [
                "def gamma():",
                "    return 3",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable is not available")
def test_diff_and_changed_commands_integrate_git_hunks_symbols_reports_and_manifest(tmp_path: Path) -> None:
    repo = make_changed_repo(tmp_path)

    diff_result = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
    assert diff_result.returncode == 0, diff_result.stdout + diff_result.stderr
    assert "CBL diff: OK" in diff_result.stdout
    assert "C:\\Users\\" not in diff_result.stdout

    diff_path = repo / ".codecontext" / "latest" / "diff.json"
    manifest_path = repo / ".codecontext" / "latest" / "manifest.json"
    assert diff_path.is_file()
    assert manifest_path.is_file()

    diff_payload = json.loads(diff_path.read_text(encoding="utf-8"))
    changed_paths = {record["path"] for record in diff_payload["changed_files"]}
    assert "module.py" in changed_paths
    assert "new_module.py" in changed_paths
    assert diff_payload["counts"]["changed_files_count"] >= 2
    assert diff_payload["changed_symbols"]["counts"]["total"] >= 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "diff"
    assert manifest["outputs"]["diff_json"] == ".codecontext/latest/diff.json"

    changed_result = run_cbl("changed", "--repo", str(repo), "--no-archive")
    assert changed_result.returncode == 0, changed_result.stdout + changed_result.stderr
    assert "CBL changed: OK" in changed_result.stdout
    assert "C:\\Users\\" not in changed_result.stdout

    changed_files_path = repo / ".codecontext" / "latest" / "changed_files.json"
    changed_symbols_path = repo / ".codecontext" / "latest" / "changed_symbols.json"

    assert changed_files_path.is_file()
    assert changed_symbols_path.is_file()

    changed_files = json.loads(changed_files_path.read_text(encoding="utf-8"))
    changed_symbols = json.loads(changed_symbols_path.read_text(encoding="utf-8"))

    assert {"module.py", "new_module.py"} <= {record["path"] for record in changed_files["changed_files"]}

    symbol_names = {record["qualified_name"] for record in changed_symbols["changed_symbols"]}
    assert "alpha" in symbol_names
    assert "gamma" in symbol_names

    changed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert changed_manifest["command"]["subcommand"] == "changed"
    assert changed_manifest["outputs"]["changed_files_json"] == ".codecontext/latest/changed_files.json"
    assert changed_manifest["outputs"]["changed_symbols_json"] == ".codecontext/latest/changed_symbols.json"
