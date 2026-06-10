from __future__ import annotations

import json
import subprocess
from pathlib import Path

from codebase_lens.reports.dump import write_codebase_dump
from codebase_lens.reports.manifest import prepare_output_layout
from codebase_lens.scanners.universe import discover_file_universe


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "cbl@example.invalid")
    _git(repo, "config", "user.name", "CBL Test")

    _write(repo / "pyproject.toml", "[project]\nname='fixture'\nversion='0.0.0'")
    _write(repo / ".env.example", "TOKEN=example-only")
    _write(repo / ".env", "TOKEN=secret")
    _write(repo / "src/pkg/output/denominator.py", "def denominator():\n    return 1")
    _write(repo / "src/pkg/data/schema.py", "SCHEMA = {'ok': True}")
    _write(repo / "src/pkg/cache/store.py", "def store():\n    return 'ok'")
    _write(repo / "src/pkg/r_scripts/fetch.R", "cat('fetch')\n")
    _write(repo / "scripts/check_r_microdatasus.R", "cat('check')\n")
    _write(repo / "config/intents/alagoas_smoke.json", json.dumps({"execution_scale": "smoke"}))
    _write(repo / "config/registries/sidra_table_seed.jsonl", '{"table_id":"9606"}')
    _write(repo / "tests/fixtures/sidra_flat_fixture.json", json.dumps({"payload": [1]}))
    _write(repo / "tests/fixtures/small.csv", "a,b\n1,2")
    _write(repo / "data/small_tracked_fixture.csv", "a,b\n1,2")
    _write(repo / ".codecontext/latest/old.md", "generated")
    _write(repo / "model.parquet", "not really parquet but suffix must be excluded")

    _git(repo, "add", ".")
    return repo


def test_file_universe_is_evidence_driven_not_directory_name_driven(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    universe = discover_file_universe(repo)
    paths = {record.path for record in universe.included_files}
    omitted = {record.path: record.reason for record in universe.omitted_files}

    assert "src/pkg/output/denominator.py" in paths
    assert "src/pkg/data/schema.py" in paths
    assert "src/pkg/cache/store.py" in paths
    assert "src/pkg/r_scripts/fetch.R" in paths
    assert "scripts/check_r_microdatasus.R" in paths
    assert "config/intents/alagoas_smoke.json" in paths
    assert "config/registries/sidra_table_seed.jsonl" in paths
    assert "tests/fixtures/sidra_flat_fixture.json" in paths
    assert "tests/fixtures/small.csv" in paths
    assert "data/small_tracked_fixture.csv" in paths
    assert ".env.example" in paths

    assert ".env" not in paths
    assert omitted[".env"] == "hard_excluded"
    assert ".codecontext/latest/old.md" not in paths
    assert omitted[".codecontext/latest/old.md"] == "hard_excluded"
    assert "model.parquet" not in paths
    assert omitted["model.parquet"] == "hard_excluded"
    assert universe.counts["unsupported_extension_count"] == 0


def test_dump_uses_scanner_text_universe_without_second_extension_gate(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    layout = prepare_output_layout(repo, ".codecontext", archive=False)

    result = write_codebase_dump(
        layout,
        repo,
        max_file_bytes=262144,
        tracked_only=True,
        include_untracked=False,
        include_tests=True,
        include_docs=True,
        include_config=True,
        include_json=False,
        line_numbers=True,
    )

    dump = (repo / ".codecontext/latest/codebase_dump.md").read_text(encoding="utf-8")
    index = json.loads((repo / ".codecontext/latest/codebase_dump_index.json").read_text(encoding="utf-8"))
    dumped_paths = {item["path"] for item in index["files"]}

    expected = {
        "src/pkg/output/denominator.py",
        "src/pkg/data/schema.py",
        "src/pkg/cache/store.py",
        "src/pkg/r_scripts/fetch.R",
        "scripts/check_r_microdatasus.R",
        "config/intents/alagoas_smoke.json",
        "config/registries/sidra_table_seed.jsonl",
        "tests/fixtures/sidra_flat_fixture.json",
        "tests/fixtures/small.csv",
        "data/small_tracked_fixture.csv",
        ".env.example",
    }
    assert expected <= dumped_paths
    for path in expected:
        assert f"### FILE: `{path}`" in dump

    assert ".env" not in dumped_paths
    assert ".codecontext/latest/old.md" not in dumped_paths
    assert "model.parquet" not in dumped_paths
    assert result.counts["included_files"] >= len(expected)
