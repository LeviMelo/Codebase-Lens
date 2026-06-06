from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codebase_lens.core.paths import (
    detect_repository_root,
    is_hard_excluded_relative,
    resolve_user_path,
)
from codebase_lens.core.errors import PathSafetyError
from codebase_lens.core.redaction import redact_text
from codebase_lens.core.textio import read_text_with_policy
from codebase_lens.reports.manifest import build_manifest, prepare_output_layout, write_manifest_bundle

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


def test_root_detection_uses_project_marker(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "src" / "pkg"
    nested.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    info = detect_repository_root(start=nested)

    assert info.root == repo.resolve()
    assert info.method == "marker:pyproject.toml"
    assert info.is_git_repo is False


def test_path_safety_rejects_traversal_absolute_and_hard_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "safe.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")

    assert resolve_user_path(repo, "safe.py") == (repo / "safe.py").resolve()

    with pytest.raises(PathSafetyError):
        resolve_user_path(repo, ".." / Path("outside.txt"))

    with pytest.raises(PathSafetyError):
        resolve_user_path(repo, str((repo / "safe.py").resolve()))

    with pytest.raises(PathSafetyError):
        resolve_user_path(repo, ".env")


def test_hard_exclusion_patterns_cover_sensitive_and_generated_paths() -> None:
    assert is_hard_excluded_relative(".codecontext/latest/manifest.json")
    assert is_hard_excluded_relative("data/raw/table.parquet")
    assert is_hard_excluded_relative("src/package/__pycache__/x.pyc")
    assert is_hard_excluded_relative(".env")
    assert is_hard_excluded_relative("secret.pem")
    assert not is_hard_excluded_relative("src/codebase_lens/cli.py")


def test_redaction_handles_assignments_json_yaml_and_private_key_blocks() -> None:
    text = "\n".join(
        [
            "OPENAI_API_KEY=sk-real-secret",
            '{"token": "abc123"}',
            "password: hunter2",
            "-----BEGIN RSA PRIVATE KEY-----",
            "private-body",
            "-----END RSA PRIVATE KEY-----",
        ]
    )

    result = redact_text(text)

    assert "sk-real-secret" not in result.text
    assert "abc123" not in result.text
    assert "hunter2" not in result.text
    assert "private-body" not in result.text
    assert "OPENAI_API_KEY=<REDACTED>" in result.text
    assert '"token": "<REDACTED>"' in result.text
    assert "password: <REDACTED>" in result.text
    assert "<REDACTED_PRIVATE_KEY_BLOCK>" in result.text
    assert result.stats.redacted_occurrences_count >= 4


def test_text_policy_detects_binary_large_and_cp1252(tmp_path: Path) -> None:
    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"abc\x00def")
    binary_result = read_text_with_policy(binary)
    assert binary_result.is_binary is True
    assert binary_result.skipped_reason == "binary_skipped"

    large = tmp_path / "large.txt"
    large.write_text("x" * 20, encoding="utf-8")
    large_result = read_text_with_policy(large, max_file_bytes=10)
    assert large_result.skipped_reason == "large_skipped"

    cp1252 = tmp_path / "latin.txt"
    cp1252.write_bytes("ação".encode("cp1252"))
    cp1252_result = read_text_with_policy(cp1252)
    assert cp1252_result.text == "ação"
    assert cp1252_result.encoding in {"cp1252", "latin-1"}


def test_manifest_writer_creates_latest_and_archive(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    layout = prepare_output_layout(repo, ".codecontext", archive=True)
    manifest = build_manifest(
        repo_root=repo,
        repo_name="repo",
        root_redacted_for_ai=True,
        is_git_repo=False,
        git={
            "available": True,
            "is_repo": False,
            "branch": None,
            "head": None,
            "is_dirty": False,
            "staged_count": 0,
            "unstaged_count": 0,
            "untracked_count": 0,
        },
        argv=["cbl", "doctor"],
        subcommand="doctor",
        budget=16000,
        focus=[],
        outputs={"manifest_json": ".codecontext/latest/manifest.json"},
        redaction={
            "enabled": True,
            "redacted_files_count": 0,
            "redacted_occurrences_count": 0,
            "patterns_hit": [],
        },
    )

    manifest_path = write_manifest_bundle(layout, manifest)

    assert manifest_path.is_file()
    assert layout.run_dir is not None
    assert (layout.run_dir / "manifest.json").is_file()

    parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert parsed["repo"]["root_redacted_for_ai"] is True
    assert parsed["command"]["subcommand"] == "doctor"


def test_doctor_writes_manifest_without_absolute_console_path() -> None:
    result = run_cbl("doctor", "--no-archive")

    assert result.returncode == 0, result.stderr
    assert "CBL doctor: OK" in result.stdout
    assert "Output manifest: .codecontext/latest/manifest.json" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "doctor"
    assert manifest["repo"]["root_redacted_for_ai"] is True
