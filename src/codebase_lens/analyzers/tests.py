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
class TestLikeSymbolRecord:
    path: str
    name: str
    kind: str
    line: int
    reason: str
    confidence: str


@dataclass(frozen=True)
class TestInventoryResult:
    tests: tuple[TestRecord, ...]
    fixtures: tuple[TestFixtureRecord, ...]
    test_like_symbols: tuple[TestLikeSymbolRecord, ...]
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


def classify_test_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    parts = tuple(part for part in normalized.split("/") if part)

    if name == "conftest.py":
        return "fixture_container"
    if normalized.startswith("tests/") or "tests" in parts:
        return "test_file"
    if name.startswith("test_") and name.endswith(".py"):
        return "test_file"
    if name.endswith("_test.py"):
        return "test_file"
    return "non_test_source"


def _is_test_file(path: str) -> bool:
    return classify_test_path(path) == "test_file"


def _test_kind(path: str) -> str:
    classification = classify_test_path(path)
    if classification == "fixture_container":
        return "pytest_fixture_container"
    if classification == "test_file":
        return "pytest"
    return "test_like_source"


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
        self.path_class = classify_test_path(relative_path)
        self.test_functions: list[str] = []
        self.test_classes: list[str] = []
        self.test_like_symbols: list[TestLikeSymbolRecord] = []
        self.fixtures: list[TestFixtureRecord] = []

    @property
    def is_real_test_file(self) -> bool:
        return self.path_class == "test_file"

    @property
    def allows_fixtures(self) -> bool:
        return self.path_class in {"test_file", "fixture_container"}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name.startswith("Test"):
            if self.is_real_test_file:
                self.test_classes.append(node.name)
            else:
                self.test_like_symbols.append(
                    TestLikeSymbolRecord(
                        path=self.relative_path,
                        name=node.name,
                        kind="class",
                        line=int(getattr(node, "lineno", 1)),
                        reason="production_class_name_starts_with_Test",
                        confidence="medium",
                    )
                )
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_fixture, scope, autouse = _fixture_metadata(node)
        if is_fixture and self.allows_fixtures:
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
        elif is_fixture:
            self.test_like_symbols.append(
                TestLikeSymbolRecord(
                    path=self.relative_path,
                    name=node.name,
                    kind="fixture",
                    line=int(getattr(node, "lineno", 1)),
                    reason="pytest_fixture_declared_outside_test_path",
                    confidence="medium",
                )
            )

        if node.name.startswith("test_"):
            if self.is_real_test_file:
                self.test_functions.append(node.name)
            else:
                self.test_like_symbols.append(
                    TestLikeSymbolRecord(
                        path=self.relative_path,
                        name=node.name,
                        kind="function",
                        line=int(getattr(node, "lineno", 1)),
                        reason="production_function_name_starts_with_test_",
                        confidence="medium",
                    )
                )


def collect_tests_for_file(
    repo_root: str | Path,
    file_path: str | Path,
) -> tuple[TestRecord | None, tuple[TestFixtureRecord, ...], tuple[TestLikeSymbolRecord, ...], tuple[str, ...]]:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return None, (), (), (f"{relative}: skipped: {read_result.skipped_reason}",)

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return None, (), (), (message,)

    visitor = _TestVisitor(relative_path=relative)
    visitor.visit(tree)

    likely_targets: list[str] = []
    for name in [*visitor.test_functions, *visitor.test_classes]:
        for target_name in _likely_targets_from_name(name):
            if target_name not in likely_targets:
                likely_targets.append(target_name)

    record: TestRecord | None = None
    if visitor.is_real_test_file and (visitor.test_functions or visitor.test_classes):
        record = TestRecord(
            path=relative,
            test_kind=_test_kind(relative),
            test_functions=sorted(visitor.test_functions),
            test_classes=sorted(visitor.test_classes),
            likely_targets=likely_targets,
            confidence="high",
        )

    return (
        record,
        tuple(sorted(visitor.fixtures, key=lambda item: (item.path, item.line, item.name))),
        tuple(sorted(visitor.test_like_symbols, key=lambda item: (item.path, item.line, item.kind, item.name))),
        (),
    )


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
    test_like_symbols: list[TestLikeSymbolRecord] = []
    syntax_errors: list[str] = []

    for path in python_files:
        record, file_fixtures, file_test_like, errors = collect_tests_for_file(root, root / Path(path))
        syntax_errors.extend(errors)
        fixtures.extend(file_fixtures)
        test_like_symbols.extend(file_test_like)

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
        test_like_symbols=tuple(sorted(test_like_symbols, key=lambda item: (item.path, item.line, item.kind, item.name))),
        syntax_errors=tuple(syntax_errors),
        warnings=(),
    )
