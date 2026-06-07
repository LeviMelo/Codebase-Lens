from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/analyzers/tests.py": [
        "TestFixtureRecord",
        "TestInventoryResult",
        "collect_tests_for_file",
        "collect_test_inventory",
    ],
    "src/codebase_lens/analyzers/callers.py": [
        "CallerRecord",
        "CallerAnalysisResult",
        "collect_callers_for_file",
        "collect_callers",
    ],
    "src/codebase_lens/reports/json.py": [
        "test_inventory_payload",
        "caller_records_payload",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


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


def make_repo(base: Path) -> Path:
    repo = base / "test_callers_repo"
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


def main() -> int:
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    project_tests = run_cbl("tests", "--show-fixtures", "--no-archive")
    if project_tests.returncode != 0:
        fail(f"project cbl tests failed:\nSTDOUT:\n{project_tests.stdout}\nSTDERR:\n{project_tests.stderr}")
    if "CBL tests: OK" not in project_tests.stdout:
        fail("project cbl tests did not report success.")
    if "C:\\Users\\" in project_tests.stdout:
        fail("project cbl tests leaked an absolute Windows user path.")

    tests_path = ROOT / ".codecontext" / "latest" / "tests_inventory.json"
    if not tests_path.is_file():
        fail("project cbl tests did not write tests_inventory.json.")

    tests_payload = json.loads(tests_path.read_text(encoding="utf-8"))
    if tests_payload["counts"]["test_files"] < 1:
        fail("project tests_inventory.json reports no test files.")
    if tests_payload["counts"]["test_functions"] < 1:
        fail("project tests_inventory.json reports no test functions.")

    project_callers = run_cbl("callers", "main", "--path", "src/codebase_lens/cli.py", "--no-archive")
    if project_callers.returncode != 0:
        fail(f"project cbl callers failed:\nSTDOUT:\n{project_callers.stdout}\nSTDERR:\n{project_callers.stderr}")
    if "CBL callers: OK" not in project_callers.stdout:
        fail("project cbl callers did not report success.")
    if "C:\\Users\\" in project_callers.stdout:
        fail("project cbl callers leaked an absolute Windows user path.")

    callers_path = ROOT / ".codecontext" / "latest" / "callers.json"
    if not callers_path.is_file():
        fail("project cbl callers did not write callers.json.")

    callers_payload = json.loads(callers_path.read_text(encoding="utf-8"))
    if callers_payload["counts"]["total"] < 1:
        fail("project callers.json reports no calls to main in cli.py.")

    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))

        tests_result = run_cbl("tests", "--repo", str(repo), "--show-fixtures", "--no-archive")
        if tests_result.returncode != 0:
            fail(f"fixture cbl tests failed:\nSTDOUT:\n{tests_result.stdout}\nSTDERR:\n{tests_result.stderr}")

        fixture_tests = json.loads((repo / ".codecontext" / "latest" / "tests_inventory.json").read_text(encoding="utf-8"))
        if fixture_tests["counts"]["fixtures"] != 1:
            fail("fixture tests inventory did not detect the pytest fixture.")
        if fixture_tests["counts"]["test_functions"] < 2:
            fail("fixture tests inventory did not detect expected test functions.")

        callers_result = run_cbl("callers", "target", "--repo", str(repo), "--no-archive")
        if callers_result.returncode != 0:
            fail(f"fixture cbl callers failed:\nSTDOUT:\n{callers_result.stdout}\nSTDERR:\n{callers_result.stderr}")

        fixture_callers = json.loads((repo / ".codecontext" / "latest" / "callers.json").read_text(encoding="utf-8"))
        if fixture_callers["counts"]["total"] < 2:
            fail("fixture callers did not detect both calls to target.")

        manifest = json.loads((repo / ".codecontext" / "latest" / "manifest.json").read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "callers":
            fail("manifest command.subcommand is not callers after cbl callers.")
        if manifest["outputs"].get("callers_json") != ".codecontext/latest/callers.json":
            fail("manifest does not declare callers_json.")
        if manifest["repo"].get("root") != "<redacted>":
            fail("manifest repo.root must be redacted when root_redacted_for_ai is true.")

    print("PASS: Phase 6 tests/callers audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
