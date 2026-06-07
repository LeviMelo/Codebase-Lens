from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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
    repo = tmp_path / "clean_repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'clean-repo'\n", encoding="utf-8")

    runs = repo / ".codecontext" / "runs"
    runs.mkdir(parents=True)

    for index in range(3):
        run_dir = runs / f"20260101T00000{index}Z"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        time.sleep(0.01)

    return repo


def test_clean_command_deletes_old_archives_and_writes_report(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("clean", "--repo", str(repo), "--keep", "1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL clean: OK" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    latest = repo / ".codecontext" / "latest"
    report_path = latest / "clean_report.json"
    manifest_path = latest / "manifest.json"

    assert report_path.is_file()
    assert manifest_path.is_file()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["counts"]["runs_seen"] == 3
    assert report["counts"]["kept"] == 1
    assert report["counts"]["deleted"] == 2
    assert report["counts"]["errors"] == 0

    remaining_runs = [item for item in (repo / ".codecontext" / "runs").iterdir() if item.is_dir()]
    assert len(remaining_runs) == 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "clean"
    assert manifest["outputs"]["clean_report_json"] == ".codecontext/latest/clean_report.json"
    assert manifest["repo"]["root"] == "<redacted>"
