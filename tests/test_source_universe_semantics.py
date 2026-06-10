
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codebase_lens.core.paths import is_hard_excluded_relative


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) if not current else str(SRC) + os.pathsep + current
    return env


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _run_cbl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def _make_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is required for the source-universe integration test")

    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, check=True)

    _write(repo / ".gitignore", ".codecontext/\n")
    _write(repo / "pyproject.toml", "[project]\nname = 'target'\nversion = '0.0.0'\n")
    _write(repo / "src" / "demo_pkg" / "__init__.py", "")
    _write(repo / "src" / "demo_pkg" / "output" / "bundle.py", "def build_bundle() -> dict:\n    return {'ok': True}\n")
    _write(repo / "src" / "demo_pkg" / "data" / "transforms.py", "def transform() -> int:\n    return 1\n")
    _write(repo / "src" / "demo_pkg" / "r_scripts" / "fetch.R", "cat('source R bridge')\n")
    _write(repo / "scripts" / "check_r.R", "cat('script source')\n")
    _write(repo / "config" / "intents" / "smoke.json", json.dumps({"intent": "smoke"}))
    _write(repo / "config" / "registries" / "seed.jsonl", '{"id":"seed"}\n')
    _write(repo / "tests" / "test_bundle.py", "from demo_pkg.output.bundle import build_bundle\n\ndef test_build_bundle():\n    assert build_bundle()['ok']\n")
    _write(repo / "tests" / "fixtures" / "payload.json", json.dumps({"fixture": True}))

    # These are tracked but still must be excluded because they are top-level generated/data roots.
    _write(repo / "output" / "generated.py", "def generated():\n    return 'no'\n")
    _write(repo / "data" / "script.py", "def data_lake_script():\n    return 'no'\n")

    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=True)
    return repo


def _file_headings(markdown: str) -> set[str]:
    return set(re.findall(r"^### FILE: `([^`]+)`", markdown, flags=re.MULTILINE))


def test_hard_exclusion_does_not_reject_source_package_output_modules() -> None:
    assert not is_hard_excluded_relative("src/demo_pkg/output/bundle.py")
    assert not is_hard_excluded_relative("src/demo_pkg/data/transforms.py")
    assert not is_hard_excluded_relative("src/demo_pkg/r_scripts/fetch.R")
    assert is_hard_excluded_relative("output/generated.py")
    assert is_hard_excluded_relative("data/script.py")
    assert is_hard_excluded_relative("src/demo_pkg/output/model.parquet")


def test_dump_includes_polyglot_source_config_json_and_protected_package_dirs(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = _run_cbl("dump", "--repo", str(repo), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    dump_path = repo / ".codecontext" / "latest" / "codebase_dump.md"
    index_path = repo / ".codecontext" / "latest" / "codebase_dump_index.json"
    assert dump_path.is_file()
    assert index_path.is_file()

    markdown = dump_path.read_text(encoding="utf-8")
    headings = _file_headings(markdown)

    expected = {
        "src/demo_pkg/output/bundle.py",
        "src/demo_pkg/data/transforms.py",
        "src/demo_pkg/r_scripts/fetch.R",
        "scripts/check_r.R",
        "config/intents/smoke.json",
        "config/registries/seed.jsonl",
        "tests/test_bundle.py",
    }
    missing = expected - headings
    assert not missing, f"missing dumped source headings: {sorted(missing)}"

    forbidden = {
        "output/generated.py",
        "data/script.py",
        "tests/fixtures/payload.json",
    }
    leaked = forbidden & headings
    assert not leaked, f"unexpected dumped headings: {sorted(leaked)}"

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    indexed_paths = {item["path"] for item in payload["files"]}
    assert expected <= indexed_paths
    assert not (forbidden & indexed_paths)

    assert "Language: `r`" in markdown
    assert "src/demo_pkg/output/bundle.py" not in {
        item["path"]
        for item in payload.get("omitted_files", [])
        if item.get("reason") == "hard_excluded"
    }


def test_dump_include_json_expands_non_config_json(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = _run_cbl("dump", "--repo", str(repo), "--include-json", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    markdown = (repo / ".codecontext" / "latest" / "codebase_dump.md").read_text(encoding="utf-8")
    headings = _file_headings(markdown)

    assert "tests/fixtures/payload.json" in headings
    assert "output/generated.py" not in headings
