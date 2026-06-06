from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codebase_lens.scanners.universe import discover_file_universe


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable is not available")
def test_git_file_universe_includes_tracked_and_untracked_nonignored(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    run_git(repo, "init")
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repo / "tracked.py").write_text("print('tracked')\n", encoding="utf-8")
    (repo / "untracked.py").write_text("print('untracked')\n", encoding="utf-8")
    (repo / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "data" / "tracked_data.py").write_text("print('no')\n", encoding="utf-8")

    run_git(repo, "add", ".gitignore", "tracked.py", "data/tracked_data.py")

    result = discover_file_universe(repo)

    paths = {record.path for record in result.included_files}

    assert "tracked.py" in paths
    assert "untracked.py" in paths
    assert "ignored.txt" not in paths
    assert "data/tracked_data.py" not in paths

    assert result.is_git_repo is True
    assert result.counts["tracked_included_count"] >= 1
    assert result.counts["untracked_included_count"] >= 1
    assert result.counts["ignored_count"] >= 1
    assert result.counts["hard_excluded_count"] >= 1


def test_non_git_file_universe_uses_filesystem_walk_and_skips_unsafe(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    (repo / "blob.bin").write_bytes(b"abc\x00def")

    result = discover_file_universe(repo)

    paths = {record.path for record in result.included_files}
    omitted = {record.path: record.reason for record in result.omitted_files}

    assert "pyproject.toml" in paths
    assert "src/main.py" in paths
    assert ".env" not in paths
    assert "blob.bin" not in paths
    assert omitted[".env"] == "hard_excluded"
    assert omitted["blob.bin"] in {"hard_excluded", "binary_skipped", "unsupported_extension"}
    assert result.is_git_repo is False


def test_file_universe_records_redaction_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "settings.py").write_text("API_KEY = 'sk-fake-secret'\n", encoding="utf-8")

    result = discover_file_universe(repo)

    assert result.counts["redacted_file_count"] == 1
    assert result.redaction.redacted_occurrences_count == 1
    assert "API_KEY" in result.redaction.patterns_hit
