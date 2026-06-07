from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/analyzers/tests.py": r'''
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.models import TestRecord
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class TestFixtureRecord:
    path: str
    name: str
    line: int
    scope: str | None
    autouse: bool | None
    confidence: str


@dataclass(frozen=True)
class TestInventoryResult:
    tests: tuple[TestRecord, ...]
    fixtures: tuple[TestFixtureRecord, ...]
    syntax_errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _decorator_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _literal_keyword(call: ast.Call, name: str) -> object | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def _fixture_metadata(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, str | None, bool | None]:
    for decorator in node.decorator_list:
        decorator_name = _decorator_name(decorator)
        if decorator_name == "pytest.fixture" or decorator_name.endswith(".fixture"):
            if isinstance(decorator, ast.Call):
                scope = _literal_keyword(decorator, "scope")
                autouse = _literal_keyword(decorator, "autouse")
                return (
                    True,
                    scope if isinstance(scope, str) else None,
                    autouse if isinstance(autouse, bool) else None,
                )
            return (True, None, None)
    return (False, None, None)


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    parts = set(Path(path).parts)
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in parts or "test" in parts


def _test_kind(path: str) -> str:
    return "pytest" if _is_test_file(path) else "python"


def _likely_targets_from_name(name: str) -> list[str]:
    cleaned = name
    cleaned = re.sub(r"^test_", "", cleaned)
    cleaned = re.sub(r"_(raises|fails|works|ok|success|error|invalid|valid)$", "", cleaned)

    candidates = []
    if cleaned and cleaned != name:
        candidates.append(cleaned)
    if "_for_" in cleaned:
        candidates.append(cleaned.split("_for_", 1)[-1])
    if "_when_" in cleaned:
        candidates.append(cleaned.split("_when_", 1)[0])

    deduped: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip("_")
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


class _TestVisitor(ast.NodeVisitor):
    def __init__(self, *, relative_path: str) -> None:
        self.relative_path = relative_path
        self.test_functions: list[str] = []
        self.test_classes: list[str] = []
        self.fixtures: list[TestFixtureRecord] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name.startswith("Test"):
            self.test_classes.append(node.name)
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_fixture, scope, autouse = _fixture_metadata(node)
        if is_fixture:
            self.fixtures.append(
                TestFixtureRecord(
                    path=self.relative_path,
                    name=node.name,
                    line=int(getattr(node, "lineno", 1)),
                    scope=scope,
                    autouse=autouse,
                    confidence="high",
                )
            )

        if node.name.startswith("test_"):
            self.test_functions.append(node.name)


def collect_tests_for_file(repo_root: str | Path, file_path: str | Path) -> tuple[TestRecord | None, tuple[TestFixtureRecord, ...], tuple[str, ...]]:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return None, (), (f"{relative}: skipped: {read_result.skipped_reason}",)

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return None, (), (message,)

    visitor = _TestVisitor(relative_path=relative)
    visitor.visit(tree)

    if not visitor.test_functions and not visitor.test_classes and not visitor.fixtures and not _is_test_file(relative):
        return None, tuple(visitor.fixtures), ()

    likely_targets: list[str] = []
    for name in [*visitor.test_functions, *visitor.test_classes]:
        for target_name in _likely_targets_from_name(name):
            if target_name not in likely_targets:
                likely_targets.append(target_name)

    record = TestRecord(
        path=relative,
        test_kind=_test_kind(relative),
        test_functions=sorted(visitor.test_functions),
        test_classes=sorted(visitor.test_classes),
        likely_targets=likely_targets,
        confidence="high" if _is_test_file(relative) else "medium",
    )

    return record, tuple(sorted(visitor.fixtures, key=lambda item: (item.path, item.line, item.name))), ()


def collect_test_inventory(
    repo_root: str | Path,
    python_files: list[str | Path],
    *,
    target: str | None = None,
    include_fixtures: bool = False,
) -> TestInventoryResult:
    root = Path(repo_root).resolve()

    tests: list[TestRecord] = []
    fixtures: list[TestFixtureRecord] = []
    syntax_errors: list[str] = []

    for path in python_files:
        record, file_fixtures, errors = collect_tests_for_file(root, root / Path(path))
        syntax_errors.extend(errors)
        fixtures.extend(file_fixtures)

        if record is None:
            continue

        if target:
            target_lower = target.lower()
            haystack = " ".join(
                [
                    record.path,
                    *record.test_functions,
                    *record.test_classes,
                    *record.likely_targets,
                ]
            ).lower()
            if target_lower not in haystack:
                continue

        tests.append(record)

    if not include_fixtures:
        fixtures = []

    return TestInventoryResult(
        tests=tuple(sorted(tests, key=lambda item: item.path)),
        fixtures=tuple(sorted(fixtures, key=lambda item: (item.path, item.line, item.name))),
        syntax_errors=tuple(syntax_errors),
        warnings=(),
    )
''',

    "src/codebase_lens/analyzers/callers.py": r'''
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class CallerRecord:
    path: str
    line: int
    column: int
    called_name: str
    call_expression: str
    enclosing_symbol: str | None
    context_line: str
    confidence: str


@dataclass(frozen=True)
class CallerAnalysisResult:
    query: str
    callers: tuple[CallerRecord, ...]
    syntax_errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _call_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Subscript):
        return _call_name(node.value)
    return ""


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"


def _context_line(source_lines: list[str], line: int) -> str:
    if line < 1 or line > len(source_lines):
        return ""
    return source_lines[line - 1].strip()


def _matches_query(call_expression: str, query: str) -> bool:
    query = query.strip()
    if not query:
        return False

    if call_expression == query:
        return True

    if call_expression.endswith("." + query):
        return True

    leaf = call_expression.rsplit(".", 1)[-1]
    return leaf == query


class _CallerVisitor(ast.NodeVisitor):
    def __init__(self, *, relative_path: str, query: str, source_lines: list[str]) -> None:
        self.relative_path = relative_path
        self.query = query
        self.source_lines = source_lines
        self.scope_stack: list[str] = []
        self.callers: list[CallerRecord] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        call_expression = _call_name(node.func)
        if _matches_query(call_expression, self.query):
            line = int(getattr(node, "lineno", 1))
            column = int(getattr(node, "col_offset", 0))
            enclosing = ".".join(self.scope_stack) if self.scope_stack else None

            self.callers.append(
                CallerRecord(
                    path=self.relative_path,
                    line=line,
                    column=column,
                    called_name=call_expression.rsplit(".", 1)[-1],
                    call_expression=call_expression or _safe_unparse(node.func),
                    enclosing_symbol=enclosing,
                    context_line=_context_line(self.source_lines, line),
                    confidence="medium" if "." in call_expression else "high",
                )
            )

        self.generic_visit(node)


def collect_callers_for_file(repo_root: str | Path, file_path: str | Path, query: str) -> CallerAnalysisResult:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return CallerAnalysisResult(
            query=query,
            callers=(),
            syntax_errors=(f"{relative}: skipped: {read_result.skipped_reason}",),
            warnings=(),
        )

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return CallerAnalysisResult(query=query, callers=(), syntax_errors=(message,), warnings=())

    visitor = _CallerVisitor(
        relative_path=relative,
        query=query,
        source_lines=source.splitlines(),
    )
    visitor.visit(tree)

    return CallerAnalysisResult(
        query=query,
        callers=tuple(sorted(visitor.callers, key=lambda item: (item.path, item.line, item.column))),
        syntax_errors=(),
        warnings=(),
    )


def collect_callers(repo_root: str | Path, python_files: list[str | Path], query: str) -> CallerAnalysisResult:
    root = Path(repo_root).resolve()

    callers: list[CallerRecord] = []
    syntax_errors: list[str] = []
    warnings: list[str] = []

    for path in python_files:
        result = collect_callers_for_file(root, root / Path(path), query)
        callers.extend(result.callers)
        syntax_errors.extend(result.syntax_errors)
        warnings.extend(result.warnings)

    return CallerAnalysisResult(
        query=query,
        callers=tuple(sorted(callers, key=lambda item: (item.path, item.line, item.column))),
        syntax_errors=tuple(syntax_errors),
        warnings=tuple(warnings),
    )
''',

    "src/codebase_lens/reports/json.py": r'''
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from codebase_lens.analyzers.callers import CallerAnalysisResult
from codebase_lens.analyzers.tests import TestInventoryResult
from codebase_lens.core.models import CommandRecord, ImportRecord, RouteRecord, SymbolRecord
from codebase_lens.git.diff import ChangedFileSet
from codebase_lens.reports.manifest import write_json


def write_json_report(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path)
    write_json(target, payload)
    return target


def symbol_records_payload(records: tuple[SymbolRecord, ...], *, syntax_errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "symbols": [asdict(record) for record in records],
        "syntax_errors": syntax_errors or [],
        "counts": {
            "total": len(records),
            "classes": sum(1 for record in records if record.kind == "class"),
            "functions": sum(1 for record in records if record.kind == "function"),
            "methods": sum(1 for record in records if record.kind == "method"),
        },
    }


def import_records_payload(records: tuple[ImportRecord, ...], *, syntax_errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "imports": [asdict(record) for record in records],
        "syntax_errors": syntax_errors or [],
        "counts": {
            "total": len(records),
            "resolved_project_imports": sum(1 for record in records if record.resolved_project_path),
            "star_imports": sum(1 for record in records if record.name == "*"),
        },
    }


def command_records_payload(records: tuple[CommandRecord, ...], *, syntax_errors: list[str] | None = None, limitations: list[str] | None = None) -> dict[str, Any]:
    return {
        "commands": [asdict(record) for record in records],
        "syntax_errors": syntax_errors or [],
        "limitations": limitations or [],
        "counts": {
            "total": len(records),
            "argparse": sum(1 for record in records if record.framework == "argparse"),
            "click": sum(1 for record in records if record.framework == "click"),
            "typer": sum(1 for record in records if record.framework == "typer"),
            "unknown": sum(1 for record in records if record.framework == "unknown"),
        },
    }


def route_records_payload(records: tuple[RouteRecord, ...], *, syntax_errors: list[str] | None = None, limitations: list[str] | None = None) -> dict[str, Any]:
    return {
        "routes": [asdict(record) for record in records],
        "syntax_errors": syntax_errors or [],
        "limitations": limitations or [],
        "counts": {
            "total": len(records),
            "fastapi": sum(1 for record in records if record.framework == "fastapi"),
            "flask": sum(1 for record in records if record.framework == "flask"),
            "unknown": sum(1 for record in records if record.framework == "unknown"),
        },
    }


def changed_files_payload(result: ChangedFileSet) -> dict[str, Any]:
    return {
        "changed_files": [asdict(record) for record in result.changed_files],
        "counts": dict(result.counts),
        "warnings": list(result.warnings),
    }


def test_inventory_payload(result: TestInventoryResult) -> dict[str, Any]:
    return {
        "tests": [asdict(record) for record in result.tests],
        "fixtures": [asdict(record) for record in result.fixtures],
        "syntax_errors": list(result.syntax_errors),
        "warnings": list(result.warnings),
        "counts": {
            "test_files": len(result.tests),
            "test_functions": sum(len(record.test_functions) for record in result.tests),
            "test_classes": sum(len(record.test_classes) for record in result.tests),
            "fixtures": len(result.fixtures),
        },
    }


def caller_records_payload(result: CallerAnalysisResult) -> dict[str, Any]:
    return {
        "query": result.query,
        "callers": [asdict(record) for record in result.callers],
        "syntax_errors": list(result.syntax_errors),
        "warnings": list(result.warnings),
        "counts": {
            "total": len(result.callers),
            "files": len({record.path for record in result.callers}),
        },
    }
''',

    "tests/test_tests_callers_integration.py": r'''
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

    callers_result = run_cbl("callers", "target", "--repo", str(repo), "--no-archive")
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
''',

    "scripts/dev/audits/audit_phase6_tests_callers.py": r'''
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

    print("PASS: Phase 6 tests/callers audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
}


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative_path: str, content: str) -> None:
    target = ROOT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(normalize(content), encoding="utf-8", newline="\n")


def patch_cli() -> None:
    path = ROOT / "src/codebase_lens/cli.py"
    text = path.read_text(encoding="utf-8")

    replacements = [
        (
            "from codebase_lens.analyzers.changed_symbols import changed_symbol_result_payload, map_changed_symbols\n"
            "from codebase_lens.analyzers.cli_static import collect_cli_commands, flatten_cli_results\n",
            "from codebase_lens.analyzers.changed_symbols import changed_symbol_result_payload, map_changed_symbols\n"
            "from codebase_lens.analyzers.callers import collect_callers\n"
            "from codebase_lens.analyzers.cli_static import collect_cli_commands, flatten_cli_results\n",
        ),
        (
            "from codebase_lens.analyzers.routes_static import collect_routes, flatten_route_results\n",
            "from codebase_lens.analyzers.routes_static import collect_routes, flatten_route_results\n"
            "from codebase_lens.analyzers.tests import collect_test_inventory\n",
        ),
        (
            "    changed_files_payload,\n"
            "    command_records_payload,\n",
            "    caller_records_payload,\n"
            "    changed_files_payload,\n"
            "    command_records_payload,\n",
        ),
        (
            "    symbol_records_payload,\n"
            "    write_json_report,\n",
            "    symbol_records_payload,\n"
            "    test_inventory_payload,\n"
            "    write_json_report,\n",
        ),
        (
            "    tests.set_defaults(handler=_run_partial)\n",
            "    tests.set_defaults(handler=_run_tests_inventory)\n",
        ),
        (
            "    callers.set_defaults(handler=_run_partial)\n",
            "    callers.set_defaults(handler=_run_callers)\n",
        ),
    ]

    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"Could not patch cli.py; missing expected marker:\n{old}")
        text = text.replace(old, new, 1)

    insert_before = "\ndef _run_diff(args: argparse.Namespace) -> int:\n"
    if insert_before not in text:
        raise RuntimeError("Could not patch cli.py; missing _run_diff insertion marker.")

    inserted = r'''

def _run_tests_inventory(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)

        inventory = collect_test_inventory(
            repo_root,
            python_files,
            target=args.target,
            include_fixtures=args.show_fixtures,
        )
        payload = test_inventory_payload(inventory)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        tests_path = write_json_report(layout.latest_dir / "tests_inventory.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "tests",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "tests_inventory_json": ".codecontext/latest/tests_inventory.json",
                },
                file_universe=universe.manifest_counts() if universe is not None else None,
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except PathSafetyError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_PATH_SAFETY_VIOLATION
    except ValueError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_INVALID_ARGUMENTS
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not write test inventory report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL tests: OK")
        print(f"Python files analyzed: {len(python_files)}")
        print(f"Test files: {payload['counts']['test_files']}")
        print(f"Test functions: {payload['counts']['test_functions']}")
        print(f"Test classes: {payload['counts']['test_classes']}")
        print(f"Fixtures: {payload['counts']['fixtures']}")
        print(f"Tests inventory: {display_path(repo_root, tests_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        if inventory.syntax_errors:
            print(f"Syntax errors: {len(inventory.syntax_errors)}")

    return 0


def _run_callers(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)

        result = collect_callers(repo_root, python_files, args.name)
        payload = caller_records_payload(result)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        callers_path = write_json_report(layout.latest_dir / "callers.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "callers",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "callers_json": ".codecontext/latest/callers.json",
                },
                file_universe=universe.manifest_counts() if universe is not None else None,
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except PathSafetyError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_PATH_SAFETY_VIOLATION
    except ValueError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_INVALID_ARGUMENTS
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not write caller report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL callers: OK")
        print(f"Python files analyzed: {len(python_files)}")
        print(f"Query: {args.name}")
        print(f"Call sites: {payload['counts']['total']}")
        print(f"Files with call sites: {payload['counts']['files']}")
        print(f"Callers report: {display_path(repo_root, callers_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        if result.syntax_errors:
            print(f"Syntax errors: {len(result.syntax_errors)}")

    return 0

'''
    text = text.replace(insert_before, inserted + insert_before, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_cli()

    print("Slice 007 applied: Phase 6 test inventory and caller analysis implemented.")
    print("Run the Phase 6 audit and integration tests before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())