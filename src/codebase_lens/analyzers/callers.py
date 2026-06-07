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
