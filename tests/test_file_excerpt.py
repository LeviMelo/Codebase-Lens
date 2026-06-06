from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from codebase_lens.analyzers.excerpts import build_file_excerpt, render_excerpt_markdown
from codebase_lens.core.errors import PathSafetyError
from codebase_lens.core.paths import resolve_user_path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


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


def test_build_file_excerpt_is_line_numbered_and_redacted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "settings.py"
    target.write_text(
        "alpha = 1\nAPI_KEY = 'sk-fake-secret'\nomega = 3\n",
        encoding="utf-8",
    )

    excerpt = build_file_excerpt(repo, target, line_selector="1:3")
    rendered = render_excerpt_markdown(excerpt)

    assert "settings.py:L1-L3" in rendered
    assert "0001: alpha = 1" in rendered
    assert "0002: API_KEY = '<REDACTED>'" in rendered
    assert "sk-fake-secret" not in rendered


def test_file_command_rejects_hard_excluded_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")

    try:
        resolve_user_path(repo, ".env")
    except PathSafetyError:
        pass
    else:
        raise AssertionError(".env should be rejected by path safety")


def test_file_command_writes_excerpt_and_uses_relative_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (repo / "module.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")

    result = run_cbl("file", "module.py", "--repo", str(repo), "--lines", "1:2", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Evidence: module.py:L1-L2" in result.stdout
    assert "0001: x = 1" in result.stdout
    assert "0002: y = 2" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    excerpt_path = repo / ".codecontext" / "latest" / "file_excerpt.md"
    assert excerpt_path.is_file()
    assert "module.py:L1-L2" in excerpt_path.read_text(encoding="utf-8")
