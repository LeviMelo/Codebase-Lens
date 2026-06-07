from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.models import SymbolRecord
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class PythonAnalysisResult:
    path: str
    symbols: tuple[SymbolRecord, ...]
    syntax_errors: tuple[str, ...]


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"


def _source_line_signature(node: ast.AST, source_lines: list[str]) -> str | None:
    lineno = getattr(node, "lineno", None)
    if not isinstance(lineno, int) or lineno < 1 or lineno > len(source_lines):
        return None

    first = source_lines[lineno - 1].strip()
    if not first:
        return None

    if first.endswith(":"):
        return first

    collected = [first]
    for index in range(lineno, min(len(source_lines), lineno + 20)):
        part = source_lines[index].strip()
        collected.append(part)
        if part.endswith(":"):
            break

    signature = " ".join(collected)
    if len(signature) > 240:
        signature = signature[:237] + "..."
    return signature


def _docstring_summary(node: ast.AST) -> str | None:
    raw = ast.get_docstring(node)
    if not raw:
        return None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:240]
    return None


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(self, *, repo_root: Path, file_path: Path, source: str) -> None:
        self.repo_root = repo_root
        self.file_path = file_path
        self.relative_path = to_posix_relative(repo_root, file_path)
        self.source_lines = source.splitlines()
        self.parent_stack: list[tuple[str, str]] = []
        self.symbols: list[SymbolRecord] = []

    def _qualified_name(self, name: str) -> str:
        parents = [item[0] for item in self.parent_stack]
        return ".".join([*parents, name]) if parents else name

    def _parent_name(self) -> str | None:
        if not self.parent_stack:
            return None
        return ".".join(item[0] for item in self.parent_stack)

    def _is_method(self) -> bool:
        return bool(self.parent_stack and self.parent_stack[-1][1] == "class")

    def _append_symbol(self, node: ast.AST, *, name: str, kind: str) -> None:
        start_line = int(getattr(node, "lineno", 1))
        end_line = int(getattr(node, "end_lineno", start_line))
        qualified_name = self._qualified_name(name)
        decorators = [_safe_unparse(item) for item in getattr(node, "decorator_list", [])]

        record = SymbolRecord(
            id=f"{self.relative_path}:{qualified_name}:{start_line}-{end_line}",
            name=name,
            qualified_name=qualified_name,
            kind=kind,
            path=self.relative_path,
            start_line=start_line,
            end_line=end_line,
            signature=_source_line_signature(node, self.source_lines),
            decorators=decorators,
            parent=self._parent_name(),
            docstring_summary=_docstring_summary(node),
            imports_used=[],
            is_exported=not name.startswith("_"),
            confidence="high",
        )
        self.symbols.append(record)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._append_symbol(node, name=node.name, kind="class")
        self.parent_stack.append((node.name, "class"))
        self.generic_visit(node)
        self.parent_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        kind = "method" if self._is_method() else "function"
        self._append_symbol(node, name=node.name, kind=kind)
        self.parent_stack.append((node.name, kind))
        self.generic_visit(node)
        self.parent_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        kind = "method" if self._is_method() else "function"
        self._append_symbol(node, name=node.name, kind=kind)
        self.parent_stack.append((node.name, kind))
        self.generic_visit(node)
        self.parent_stack.pop()


def collect_symbols_for_file(repo_root: str | Path, file_path: str | Path) -> PythonAnalysisResult:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return PythonAnalysisResult(
            path=relative,
            symbols=(),
            syntax_errors=(f"{relative}: skipped: {read_result.skipped_reason}",),
        )

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return PythonAnalysisResult(path=relative, symbols=(), syntax_errors=(message,))

    visitor = _SymbolVisitor(repo_root=root, file_path=target, source=source)
    visitor.visit(tree)

    return PythonAnalysisResult(
        path=relative,
        symbols=tuple(sorted(visitor.symbols, key=lambda item: (item.path, item.start_line, item.qualified_name))),
        syntax_errors=(),
    )


def collect_python_symbols(repo_root: str | Path, python_files: list[str | Path]) -> tuple[PythonAnalysisResult, ...]:
    root = Path(repo_root).resolve()
    results = [collect_symbols_for_file(root, root / Path(path)) for path in python_files]
    return tuple(results)


def flatten_symbol_results(results: tuple[PythonAnalysisResult, ...]) -> tuple[SymbolRecord, ...]:
    records: list[SymbolRecord] = []
    for result in results:
        records.extend(result.symbols)
    return tuple(sorted(records, key=lambda item: (item.path, item.start_line, item.qualified_name)))


def find_symbol_matches(
    symbols: tuple[SymbolRecord, ...],
    query: str,
    *,
    path: str | None = None,
    kind: str = "all",
) -> tuple[SymbolRecord, ...]:
    query_lower = query.lower()
    matches: list[SymbolRecord] = []

    for record in symbols:
        if path is not None and record.path != path:
            continue
        if kind != "all" and record.kind != kind:
            continue

        name_match = record.name.lower() == query_lower
        qualified_match = record.qualified_name.lower() == query_lower
        suffix_match = record.qualified_name.lower().endswith("." + query_lower)

        if name_match or qualified_match or suffix_match:
            matches.append(record)

    return tuple(sorted(matches, key=lambda item: (item.path, item.start_line, item.qualified_name)))
