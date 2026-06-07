from __future__ import annotations

import json
import os
import subprocess
import sys
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
    repo = tmp_path / "test_callers_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'test-callers-repo'\n", encoding="utf-8")

    (package / "service.py").write_text(
        "\n".join(
            [
                "def target(value):",
                "    return value + 1",
                "",
                "def wrapper(value):",
                "    return target(value)",
                "",
                "class Worker:",
                "    def run(self, value):",
                "        return target(value)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_service.py").write_text(
        "\n".join(
            [
                "import pytest",
                "from demo.service import wrapper",
                "",
                "@pytest.fixture(scope='module')",
                "def sample_value():",
                "    return 1",
                "",
                "def test_wrapper(sample_value):",
                "    assert wrapper(sample_value) == 2",
                "",
                "class TestService:",
                "    def test_worker(self):",
                "        assert True",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_tests_and_callers_commands_cross_slice_outputs(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    tests_result = run_cbl("tests", "--repo", str(repo), "--show-fixtures", "--no-archive")
    assert tests_result.returncode == 0, tests_result.stdout + tests_result.stderr
    assert "CBL tests: OK" in tests_result.stdout
    assert "C:\\Users\\" not in tests_result.stdout

    tests_path = repo / ".codecontext" / "latest" / "tests_inventory.json"
    manifest_path = repo / ".codecontext" / "latest" / "manifest.json"

    assert tests_path.is_file()
    assert manifest_path.is_file()

    tests_payload = json.loads(tests_path.read_text(encoding="utf-8"))
    assert tests_payload["counts"]["test_files"] >= 1
    assert tests_payload["counts"]["test_functions"] >= 2
    assert tests_payload["counts"]["fixtures"] == 1
    assert any(record["path"] == "tests/test_service.py" for record in tests_payload["tests"])

    tests_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert tests_manifest["command"]["subcommand"] == "tests"
    assert tests_manifest["outputs"]["tests_inventory_json"] == ".codecontext/latest/tests_inventory.json"

    callers_result = run_cbl("callers", "target", "--repo", str(repo), "--path", "src/demo/service.py", "--no-archive")
    assert callers_result.returncode == 0, callers_result.stdout + callers_result.stderr
    assert "CBL callers: OK" in callers_result.stdout
    assert "C:\\Users\\" not in callers_result.stdout

    callers_path = repo / ".codecontext" / "latest" / "callers.json"
    assert callers_path.is_file()

    callers_payload = json.loads(callers_path.read_text(encoding="utf-8"))
    assert callers_payload["counts"]["total"] >= 2
    contexts = {record["enclosing_symbol"] for record in callers_payload["callers"]}
    assert "wrapper" in contexts
    assert "Worker.run" in contexts or "run" in contexts

    callers_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert callers_manifest["command"]["subcommand"] == "callers"
    assert callers_manifest["outputs"]["callers_json"] == ".codecontext/latest/callers.json"
