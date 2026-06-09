from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def run_cbl(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[1] / "src")
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return subprocess.run([sys.executable, "-m", "codebase_lens", *args], cwd=repo, env=env, text=True, capture_output=True, check=False)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    pkg = repo / "src" / "pkg"
    tests = repo / "tests"
    data = repo / "data"
    pkg.mkdir(parents=True); tests.mkdir(parents=True); data.mkdir(parents=True)
    write(repo / "pyproject.toml", "[project]\nname = 'pkg'\nversion = '0.0.0'\n")
    write(repo / "codebase_dump.md", "previous dump poison\n")
    write(data / "raw.csv", "a,b\n1,2\n")
    write(pkg / "core.py", "\"\"\"Core module docs.\"\"\"\n\n\ndef normalize(value: str) -> str:\n    \"\"\"Normalize a value.\"\"\"\n    return value.strip().lower()\n")
    write(tests / "test_core.py", "from pkg.core import normalize\n\n\ndef test_normalize():\n    assert normalize(\" A \") == \"a\"\n")
    git(repo, "init"); git(repo, "config", "user.email", "fixture@example.invalid"); git(repo, "config", "user.name", "CBL Fixture")
    git(repo, "add", ".")
    result = git(repo, "commit", "-m", "initial")
    assert result.returncode == 0, result.stdout + result.stderr
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    write(pkg / "core.py", "\"\"\"Core module docs.\"\"\"\n\n\ndef normalize(value: str) -> str:\n    \"\"\"Normalize a value.\"\"\"\n    return value.strip().casefold()\n\n\ndef render(value: str) -> str:\n    \"\"\"Render a value.\"\"\"\n    return f\"value={normalize(value)}\"\n")
    git(repo, "add", ".")
    result = git(repo, "commit", "-m", "add render")
    assert result.returncode == 0, result.stdout + result.stderr
    return repo, base


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable is not available")
def test_dump_writes_searchable_markdown_source_corpus(tmp_path: Path) -> None:
    repo, _base = make_repo(tmp_path)
    result = run_cbl(repo, "dump", "--repo", str(repo), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr
    latest = repo / ".codecontext" / "latest"
    dump = latest / "codebase_dump.md"
    index = latest / "codebase_dump_index.json"
    manifest = latest / "manifest.json"
    assert dump.is_file() and index.is_file() and manifest.is_file()
    text = dump.read_text(encoding="utf-8")
    assert "# CBL Codebase Dump" in text
    assert "FILE: `src/pkg/core.py`" in text
    assert "Core module docs." in text
    assert "SYMBOL: `normalize`" in text
    assert "def render" in text
    assert "previous dump poison" not in text
    assert "FILE: `data/raw.csv`" not in text
    assert "a,b" not in text
    payload = json.loads(index.read_text(encoding="utf-8"))
    assert payload["counts"]["included_files"] >= 3
    assert payload["counts"]["symbols"] >= 2
    assert any(item["path"] == "src/pkg/core.py" for item in payload["files"])
    assert "codebase_dump.md" in manifest.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable is not available")
def test_diffdump_writes_git_range_patch_corpus(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    result = run_cbl(repo, "diffdump", "--repo", str(repo), "--from", base, "--to", "HEAD", "--symbols", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr
    latest = repo / ".codecontext" / "latest"
    dump = latest / "diff_dump.md"
    index = latest / "diff_dump_index.json"
    manifest = latest / "manifest.json"
    assert dump.is_file() and index.is_file() and manifest.is_file()
    text = dump.read_text(encoding="utf-8")
    assert "# CBL Diff Dump" in text
    assert f"From: `{base}`" in text
    assert "To: `HEAD`" in text
    assert "src/pkg/core.py" in text
    assert "~~~~diff" in text
    assert "+def render" in text
    payload = json.loads(index.read_text(encoding="utf-8"))
    assert payload["counts"]["changed_files_count"] >= 1
    assert payload["patch_bytes"] > 0
    assert "diff_dump.md" in manifest.read_text(encoding="utf-8")
