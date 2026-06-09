from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def env() -> dict[str, str]:
    values = os.environ.copy()
    src = str(ROOT / "src")
    current = values.get("PYTHONPATH", "")
    values["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return values


def run_cbl(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        env=env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )


def _read_latest_dump() -> tuple[str, dict[str, object]]:
    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "codebase_dump.md").read_text(encoding="utf-8")
    index = json.loads((latest / "codebase_dump_index.json").read_text(encoding="utf-8"))
    return text, index


def test_dump_path_scope_limits_dump_to_src_tree() -> None:
    result = run_cbl("dump", "--path", "src", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    text, index = _read_latest_dump()

    assert "Scope: `src`" in text
    assert "### FILE: `src/codebase_lens/cli.py`" in text
    assert "### FILE: `README.md`" not in text
    assert "### FILE: `docs/" not in text
    assert "### FILE: `scripts/" not in text
    assert index["scope_paths"] == ["src"]
    assert index["files"]
    assert all(str(item["path"]).startswith("src/") for item in index["files"])


def test_dump_cwd_scope_uses_current_directory_as_scope() -> None:
    result = run_cbl("dump", "--cwd-scope", "--no-archive", cwd=ROOT / "src")
    assert result.returncode == 0, result.stdout + result.stderr

    text, index = _read_latest_dump()

    assert "Scope: `src`" in text
    assert "### FILE: `src/codebase_lens/cli.py`" in text
    assert "### FILE: `README.md`" not in text
    assert index["scope_paths"] == ["src"]
    assert all(str(item["path"]).startswith("src/") for item in index["files"])
