from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def run_cbl(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    package = repo / "src" / "demo_pkg"

    write(repo / ".gitignore", ".codecontext/\ndata/\noutputs/\n")
    write(repo / "pyproject.toml", "[project]\nname = 'demo-pkg'\nversion = '0.0.0'\n")
    write(package / "__init__.py", "")
    write(
        package / "core.py",
        """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().casefold()

def build_name(name: str) -> str:
    return normalize_name(name)
""",
    )
    write(package / "large_notes.md", "LARGE\n" + ("x" * 4096))
    write(repo / "data" / "ignored_payload.txt", "ignored data")
    write(repo / "outputs" / "ignored_output.txt", "ignored output")
    write(repo / ".codecontext" / "previous" / "ignored_prior_output.txt", "previous output")

    if shutil.which("git"):
        if run_git(repo, "init").returncode == 0:
            run_git(repo, "config", "user.email", "fixture@example.invalid")
            run_git(repo, "config", "user.name", "CBL Fixture")
            run_git(repo, "add", ".")
            run_git(repo, "commit", "-m", "initial")

    return repo


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_manifest_matches_inventory(repo: Path) -> dict:
    latest = repo / ".codecontext" / "latest"
    manifest = load_json(latest / "manifest.json")
    inventory = load_json(latest / "file_inventory.json")
    manifest_counts = manifest["file_universe"]
    inventory_counts = inventory["counts"]

    for key in [
        "tracked_included_count",
        "untracked_included_count",
        "ignored_count",
        "hard_excluded_ignored_count",
        "hard_excluded_count",
        "large_skipped_count",
        "binary_skipped_count",
        "decode_failed_count",
        "redacted_file_count",
        "unsupported_extension_count",
        "included_count",
        "omitted_files_count",
    ]:
        assert key in manifest_counts
        assert int(manifest_counts.get(key, 0) or 0) == int(inventory_counts.get(key, 0) or 0)

    return manifest_counts


def test_snapshot_pack_and_graph_manifest_file_universe_matches_file_inventory(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    runner = tmp_path / "runner"
    runner.mkdir()

    snapshot = run_cbl("snapshot", "--repo", str(repo), "--budget", "12000", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert snapshot.returncode == 0, snapshot.stdout + snapshot.stderr
    first_counts = assert_manifest_matches_inventory(repo)

    pack = run_cbl("pack", "--repo", str(repo), "--issue", "manifest consistency test", "--budget", "12000", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert pack.returncode == 0, pack.stdout + pack.stderr
    pack_counts = assert_manifest_matches_inventory(repo)

    graph = run_cbl("graph", "--repo", str(repo), "--symbol", "build_name", "--depth", "1", "--limit", "40", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert graph.returncode == 0, graph.stdout + graph.stderr
    graph_counts = assert_manifest_matches_inventory(repo)

    assert first_counts["included_count"] == pack_counts["included_count"] == graph_counts["included_count"]
    assert first_counts["large_skipped_count"] >= 1


def test_hard_excluded_ignored_files_do_not_make_ignored_count_drift(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    runner = tmp_path / "runner"
    runner.mkdir()

    first = run_cbl("snapshot", "--repo", str(repo), "--budget", "12000", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert first.returncode == 0, first.stdout + first.stderr
    first_counts = assert_manifest_matches_inventory(repo)

    second = run_cbl("snapshot", "--repo", str(repo), "--budget", "12000", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert second.returncode == 0, second.stdout + second.stderr
    second_counts = assert_manifest_matches_inventory(repo)

    assert first_counts["ignored_count"] == second_counts["ignored_count"]
    assert first_counts["hard_excluded_ignored_count"] >= 1
    assert second_counts["hard_excluded_ignored_count"] >= first_counts["hard_excluded_ignored_count"]


def test_phase28_manifest_consistency_audit_passes() -> None:
    runner = ROOT / ".codecontext" / "pytest_runner_manifest_consistency"
    runner.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dev" / "audits" / "audit_phase28_manifest_consistency.py")],
        cwd=runner,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Phase 28 manifest consistency audit passed." in result.stdout
