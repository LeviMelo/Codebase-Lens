from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/analyzers/python_ast.py": r'''
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
''',

    "src/codebase_lens/analyzers/imports.py": r'''
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.models import ImportRecord
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class PythonImportAnalysisResult:
    path: str
    imports: tuple[ImportRecord, ...]
    syntax_errors: tuple[str, ...]


def _raw_line(source_lines: list[str], lineno: int) -> str:
    if lineno < 1 or lineno > len(source_lines):
        return ""
    return source_lines[lineno - 1].strip()


def _candidate_module_paths(root: Path, parts: list[str]) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for base in (root / "src", root):
        candidates.append(base.joinpath(*parts).with_suffix(".py"))
        candidates.append(base.joinpath(*parts) / "__init__.py")
    return tuple(candidates)


def _module_parts_for_relative_import(repo_root: Path, file_path: Path, level: int, module: str | None) -> list[str]:
    try:
        relative = file_path.relative_to(repo_root / "src")
    except ValueError:
        relative = file_path.relative_to(repo_root)

    package_parts = list(relative.parent.parts)

    if file_path.name == "__init__.py":
        package_parts = list(relative.parent.parts)

    climb = max(level - 1, 0)
    if climb:
        package_parts = package_parts[:-climb] if climb <= len(package_parts) else []

    if module:
        package_parts.extend(part for part in module.split(".") if part)

    return package_parts


def resolve_project_import(
    repo_root: str | Path,
    file_path: str | Path,
    *,
    module: str | None,
    name: str | None,
    level: int = 0,
) -> str | None:
    root = Path(repo_root).resolve()
    target_file = Path(file_path).resolve()

    if level > 0:
        parts = _module_parts_for_relative_import(root, target_file, level, module)
    elif module:
        parts = [part for part in module.split(".") if part]
    else:
        return None

    candidate_parts = list(parts)
    if name and name != "*":
        candidate_parts_with_name = [*candidate_parts, name]
    else:
        candidate_parts_with_name = candidate_parts

    for candidate in _candidate_module_paths(root, candidate_parts_with_name):
        if candidate.is_file():
            return to_posix_relative(root, candidate)

    for candidate in _candidate_module_paths(root, candidate_parts):
        if candidate.is_file():
            return to_posix_relative(root, candidate)

    return None


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, *, repo_root: Path, file_path: Path, source: str) -> None:
        self.repo_root = repo_root
        self.file_path = file_path
        self.relative_path = to_posix_relative(repo_root, file_path)
        self.source_lines = source.splitlines()
        self.imports: list[ImportRecord] = []

    def visit_Import(self, node: ast.Import) -> None:
        raw = _raw_line(self.source_lines, int(getattr(node, "lineno", 1)))
        for alias in node.names:
            module = alias.name
            record = ImportRecord(
                path=self.relative_path,
                line=int(getattr(node, "lineno", 1)),
                module=module,
                name=None,
                alias=alias.asname,
                level=0,
                raw=raw,
                resolved_project_path=resolve_project_import(
                    self.repo_root,
                    self.file_path,
                    module=module,
                    name=None,
                    level=0,
                ),
                confidence="medium",
            )
            self.imports.append(record)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raw = _raw_line(self.source_lines, int(getattr(node, "lineno", 1)))
        module = node.module
        level = int(getattr(node, "level", 0))

        for alias in node.names:
            record = ImportRecord(
                path=self.relative_path,
                line=int(getattr(node, "lineno", 1)),
                module=module,
                name=alias.name,
                alias=alias.asname,
                level=level,
                raw=raw,
                resolved_project_path=resolve_project_import(
                    self.repo_root,
                    self.file_path,
                    module=module,
                    name=alias.name,
                    level=level,
                ),
                confidence="medium" if record_like_import_is_dynamic(module, alias.name) else "high",
            )
            self.imports.append(record)


def record_like_import_is_dynamic(module: str | None, name: str | None) -> bool:
    if name == "*":
        return True
    if module is None and name is None:
        return True
    return False


def collect_imports_for_file(repo_root: str | Path, file_path: str | Path) -> PythonImportAnalysisResult:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return PythonImportAnalysisResult(
            path=relative,
            imports=(),
            syntax_errors=(f"{relative}: skipped: {read_result.skipped_reason}",),
        )

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return PythonImportAnalysisResult(path=relative, imports=(), syntax_errors=(message,))

    visitor = _ImportVisitor(repo_root=root, file_path=target, source=source)
    visitor.visit(tree)

    return PythonImportAnalysisResult(
        path=relative,
        imports=tuple(sorted(visitor.imports, key=lambda item: (item.path, item.line, item.module or "", item.name or ""))),
        syntax_errors=(),
    )


def collect_python_imports(repo_root: str | Path, python_files: list[str | Path]) -> tuple[PythonImportAnalysisResult, ...]:
    root = Path(repo_root).resolve()
    results = [collect_imports_for_file(root, root / Path(path)) for path in python_files]
    return tuple(results)


def flatten_import_results(results: tuple[PythonImportAnalysisResult, ...]) -> tuple[ImportRecord, ...]:
    records: list[ImportRecord] = []
    for result in results:
        records.extend(result.imports)
    return tuple(sorted(records, key=lambda item: (item.path, item.line, item.module or "", item.name or "")))


def filter_imports_by_module(imports: tuple[ImportRecord, ...], module_query: str | None) -> tuple[ImportRecord, ...]:
    if not module_query:
        return imports

    lowered = module_query.lower()
    filtered = []
    for record in imports:
        haystack = " ".join(
            part
            for part in (
                record.module,
                record.name,
                record.alias,
                record.resolved_project_path,
                record.raw,
            )
            if part
        ).lower()
        if lowered in haystack:
            filtered.append(record)

    return tuple(filtered)
''',

    "src/codebase_lens/reports/json.py": r'''
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from codebase_lens.core.models import ImportRecord, SymbolRecord
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
''',

    "src/codebase_lens/cli.py": r'''
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from codebase_lens import __version__
from codebase_lens.analyzers.excerpts import build_file_excerpt, render_excerpt_markdown
from codebase_lens.analyzers.imports import (
    collect_python_imports,
    filter_imports_by_module,
    flatten_import_results,
)
from codebase_lens.analyzers.python_ast import (
    collect_python_symbols,
    find_symbol_matches,
    flatten_symbol_results,
)
from codebase_lens.core.constants import (
    DEFAULT_BUDGET,
    DEFAULT_MAX_EXCERPT_BYTES,
    DEFAULT_MAX_FILE_BYTES,
    EXIT_GENERAL_ERROR,
    EXIT_INVALID_ARGUMENTS,
    EXIT_OUTPUT_WRITE_FAILURE,
    EXIT_PATH_SAFETY_VIOLATION,
    EXIT_ROOT_DETECTION_FAILURE,
    PUBLIC_COMMANDS,
)
from codebase_lens.core.errors import CblError, PathSafetyError, RootDetectionError
from codebase_lens.core.paths import detect_repository_root, display_path, gitignore_mentions_codecontext, resolve_user_path, to_posix_relative
from codebase_lens.core.redaction import redact_console_text
from codebase_lens.core.result import CblCommandResult, emit_result
from codebase_lens.git.discover import collect_git_info
from codebase_lens.reports.json import import_records_payload, symbol_records_payload, write_json_report
from codebase_lens.reports.manifest import build_manifest, copy_latest_to_run, prepare_output_layout, write_manifest_bundle
from codebase_lens.scanners.inventory import write_file_inventory
from codebase_lens.scanners.tree import write_tree_report
from codebase_lens.scanners.universe import discover_file_universe


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=None, help="Repository root override. Defaults to detected current repository.")
    parser.add_argument("--out", default=".codecontext", help="Output directory. Defaults to .codecontext.")
    parser.add_argument("--format", choices=("markdown", "json", "both"), default="both")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--absolute-paths", action="store_true")
    parser.add_argument("--allow-no-root", action="store_true")
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--quiet", action="store_true")


def _parent() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    _add_global_options(parser)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parent = _parent()
    parser = argparse.ArgumentParser(
        prog="cbl",
        description="Local Codebase Lens: local repository evidence engine for AI-assisted coding.",
        parents=[parent],
    )
    parser.add_argument("--version", action="version", version=f"codebase-lens {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    doctor = sub.add_parser("doctor", parents=[parent], help="Validate local tool and repository readiness.")
    doctor.set_defaults(handler=_run_doctor)

    snapshot = sub.add_parser("snapshot", parents=[parent], help="Write repository snapshot reports.")
    snapshot.add_argument("--changed", action="store_true")
    snapshot.set_defaults(handler=_run_partial)

    tree = sub.add_parser("tree", parents=[parent], help="Print or write a compact repository tree.")
    tree.add_argument("--depth", type=int, default=4)
    tree.add_argument("--show-skipped", action="store_true")
    tree.add_argument("--show-sizes", action="store_true")
    tree.add_argument("--changed-only", action="store_true")
    tree.set_defaults(handler=_run_tree)

    symbols = sub.add_parser("symbols", parents=[parent], help="List Python symbols.")
    symbols.add_argument("--kind", choices=("function", "class", "method", "all"), default="all")
    symbols.add_argument("--path")
    symbols.add_argument("--query")
    symbols.add_argument("--json", action="store_true")
    symbols.set_defaults(handler=_run_symbols)

    imports = sub.add_parser("imports", parents=[parent], help="Summarize import graph.")
    imports.add_argument("--path")
    imports.add_argument("--module")
    imports.add_argument("--reverse", action="store_true")
    imports.add_argument("--cycles", action="store_true")
    imports.set_defaults(handler=_run_imports)

    cli = sub.add_parser("cli", parents=[parent], help="Statically discover CLI commands.")
    cli.add_argument("--framework", choices=("typer", "click", "argparse", "all"), default="all")
    cli.add_argument("--path")
    cli.set_defaults(handler=_run_partial)

    routes = sub.add_parser("routes", parents=[parent], help="Statically discover web routes.")
    routes.add_argument("--framework", choices=("fastapi", "flask", "all"), default="all")
    routes.set_defaults(handler=_run_partial)

    tests = sub.add_parser("tests", parents=[parent], help="Inventory tests.")
    tests.add_argument("--target")
    tests.add_argument("--show-fixtures", action="store_true")
    tests.set_defaults(handler=_run_partial)

    diff = sub.add_parser("diff", parents=[parent], help="Summarize Git diffs.")
    diff.add_argument("--staged", action="store_true")
    diff.add_argument("--unstaged", action="store_true")
    diff.add_argument("--base")
    diff.add_argument("--symbols", action="store_true")
    diff.add_argument("--stat", action="store_true")
    diff.set_defaults(handler=_run_partial)

    changed = sub.add_parser("changed", parents=[parent], help="Summarize changed files and changed symbols.")
    changed.set_defaults(handler=_run_partial)

    file_cmd = sub.add_parser("file", parents=[parent], help="Emit a safe line-numbered excerpt from a file.")
    file_cmd.add_argument("path")
    file_cmd.add_argument("--lines")
    file_cmd.add_argument("--around", type=int)
    file_cmd.add_argument("--context", type=int, default=30)
    file_cmd.set_defaults(handler=_run_file)

    symbol = sub.add_parser("symbol", parents=[parent], help="Emit one or more symbol excerpts.")
    symbol.add_argument("symbol_name")
    symbol.add_argument("--context", type=int, default=20)
    symbol.add_argument("--path")
    symbol.add_argument("--first", action="store_true")
    symbol.set_defaults(handler=_run_symbol)

    callers = sub.add_parser("callers", parents=[parent], help="Find static call sites.")
    callers.add_argument("name")
    callers.set_defaults(handler=_run_partial)

    contract = sub.add_parser("contract", parents=[parent], help="Audit repository against an architecture contract.")
    contract.add_argument("--spec")
    contract.add_argument("--no-fail-exit", action="store_true")
    contract.set_defaults(handler=_run_partial)

    pack = sub.add_parser("pack", parents=[parent], help="Produce an AI handoff pack.")
    pack.add_argument("--changed", action="store_true")
    pack.add_argument("--issue")
    pack.add_argument("--spec")
    pack.set_defaults(handler=_run_partial)

    clean = sub.add_parser("clean", parents=[parent], help="Remove old .codecontext/runs archives.")
    clean.add_argument("--keep", type=int, default=10)
    clean.add_argument("--all", action="store_true")
    clean.set_defaults(handler=_run_partial)

    return parser


def _git_manifest_payload(git_info) -> dict[str, object]:
    return {
        "available": git_info.available,
        "is_repo": git_info.is_repo,
        "branch": git_info.branch,
        "head": git_info.head,
        "is_dirty": git_info.is_dirty,
        "staged_count": git_info.staged_count,
        "unstaged_count": git_info.unstaged_count,
        "untracked_count": git_info.untracked_count,
    }


def _detect_root(args: argparse.Namespace):
    return detect_repository_root(
        explicit_repo=args.repo,
        allow_no_root=args.allow_no_root,
    )


def _base_manifest_args(args: argparse.Namespace, repo_root: Path, subcommand: str, outputs: dict[str, str], file_universe=None, redaction=None) -> dict[str, object]:
    git_info = collect_git_info(repo_root)
    redaction_payload = redaction or {
        "enabled": True,
        "redacted_files_count": 0,
        "redacted_occurrences_count": 0,
        "patterns_hit": [],
    }

    return {
        "repo_root": repo_root,
        "repo_name": repo_root.name,
        "root_redacted_for_ai": True,
        "is_git_repo": git_info.is_repo,
        "git": _git_manifest_payload(git_info),
        "argv": ["cbl", *sys.argv[1:]],
        "subcommand": subcommand,
        "budget": args.budget,
        "focus": list(args.focus),
        "outputs": outputs,
        "redaction": redaction_payload,
        "file_universe": file_universe,
    }


def _python_files_for_analysis(args: argparse.Namespace, repo_root: Path) -> tuple[list[str], object | None]:
    if getattr(args, "path", None):
        target = resolve_user_path(repo_root, args.path, allow_absolute=False, allow_hard_excluded=False)
        relative = to_posix_relative(repo_root, target)
        if target.suffix.lower() not in {".py", ".pyw", ".pyi"}:
            raise ValueError(f"Not a Python source file: {relative}")
        return [relative], None

    universe = discover_file_universe(repo_root, max_file_bytes=args.max_file_bytes)
    python_files = [
        record.path
        for record in universe.included_files
        if Path(record.path).suffix.lower() in {".py", ".pyw", ".pyi"}
    ]
    return python_files, universe


def _syntax_errors_from_symbol_results(results) -> list[str]:
    errors: list[str] = []
    for result in results:
        errors.extend(result.syntax_errors)
    return errors


def _syntax_errors_from_import_results(results) -> list[str]:
    errors: list[str] = []
    for result in results:
        errors.extend(result.syntax_errors)
    return errors


def _run_doctor(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        git_info = collect_git_info(repo_root)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        warnings = list(root_info.warnings)
        warnings.extend(git_info.warnings)

        if not gitignore_mentions_codecontext(repo_root):
            warnings.append("WARNING: .codecontext/ is not ignored by Git. Add it to .gitignore.")

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "doctor",
                {"manifest_json": ".codecontext/latest/manifest.json"},
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not prepare CBL output directory: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL doctor: OK")
        print(f"Repository: {repo_root.name}")
        print(f"Root detection: {root_info.method}")
        print(f"Git available: {git_info.available}")
        print(f"Git repository: {git_info.is_repo}")
        if git_info.branch:
            print(f"Git branch: {git_info.branch}")
        print(f"Git dirty: {git_info.is_dirty}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        if layout.run_dir is not None:
            print(f"Archive run: {display_path(repo_root, layout.run_dir, absolute=args.absolute_paths)}")
        for warning in warnings:
            print(redact_console_text(warning))

    return 0


def _run_tree(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        universe = discover_file_universe(repo_root, max_file_bytes=args.max_file_bytes)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        inventory_path = write_file_inventory(layout, universe)
        tree_path = write_tree_report(
            layout,
            universe,
            max_depth=args.depth,
            show_sizes=args.show_sizes,
            show_skipped=args.show_skipped,
        )

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "tree",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "file_inventory_json": ".codecontext/latest/file_inventory.json",
                    "repo_tree_txt": ".codecontext/latest/repo_tree.txt",
                },
                file_universe=universe.manifest_counts(),
                redaction={
                    "enabled": True,
                    "redacted_files_count": universe.counts.get("redacted_file_count", 0),
                    "redacted_occurrences_count": universe.redaction.redacted_occurrences_count,
                    "patterns_hit": list(universe.redaction.patterns_hit),
                },
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not write tree report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL tree: OK")
        print(f"Repository: {repo_root.name}")
        print(f"Included files: {universe.counts.get('included_count', 0)}")
        print(f"Tracked included: {universe.counts.get('tracked_included_count', 0)}")
        print(f"Untracked included: {universe.counts.get('untracked_included_count', 0)}")
        print(f"Ignored count: {universe.counts.get('ignored_count', 0)}")
        print(f"Hard-excluded count: {universe.counts.get('hard_excluded_count', 0)}")
        print(f"Tree report: {display_path(repo_root, tree_path, absolute=args.absolute_paths)}")
        print(f"File inventory: {display_path(repo_root, inventory_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for warning in universe.warnings:
            print(redact_console_text(f"WARNING: {warning}"))

    return 0


def _run_file(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        target = resolve_user_path(
            repo_root,
            args.path,
            allow_absolute=False,
            allow_hard_excluded=False,
        )

        excerpt = build_file_excerpt(
            repo_root,
            target,
            line_selector=args.lines,
            around=args.around,
            context=args.context,
            max_file_bytes=min(args.max_file_bytes, DEFAULT_MAX_EXCERPT_BYTES),
        )

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        excerpt_path = layout.latest_dir / "file_excerpt.md"
        excerpt_markdown = render_excerpt_markdown(excerpt)
        excerpt_path.write_text(excerpt_markdown + "\n", encoding="utf-8", newline="\n")

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "file",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "file_excerpt_md": ".codecontext/latest/file_excerpt.md",
                },
                redaction={
                    "enabled": True,
                    "redacted_files_count": 1 if excerpt.redaction.redacted_occurrences_count else 0,
                    "redacted_occurrences_count": excerpt.redaction.redacted_occurrences_count,
                    "patterns_hit": list(excerpt.redaction.patterns_hit),
                },
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
        print(redact_console_text(f"ERROR: Could not read or write file excerpt: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print(excerpt_markdown)
        print(f"Excerpt report: {display_path(repo_root, excerpt_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")

    return 0


def _run_symbols(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)

        results = collect_python_symbols(repo_root, python_files)
        symbols = flatten_symbol_results(results)

        if args.kind != "all":
            symbols = tuple(record for record in symbols if record.kind == args.kind)

        if args.query:
            lowered = args.query.lower()
            symbols = tuple(
                record
                for record in symbols
                if lowered in record.name.lower() or lowered in record.qualified_name.lower()
            )

        syntax_errors = _syntax_errors_from_symbol_results(results)
        payload = symbol_records_payload(symbols, syntax_errors=syntax_errors)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        symbols_path = write_json_report(layout.latest_dir / "symbols.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "symbols",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "symbols_json": ".codecontext/latest/symbols.json",
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
        print(redact_console_text(f"ERROR: Could not write symbol report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    elif not args.quiet:
        print("CBL symbols: OK")
        print(f"Python files analyzed: {len(python_files)}")
        print(f"Symbols: {len(symbols)}")
        print(f"Classes: {payload['counts']['classes']}")
        print(f"Functions: {payload['counts']['functions']}")
        print(f"Methods: {payload['counts']['methods']}")
        print(f"Symbols report: {display_path(repo_root, symbols_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        if syntax_errors:
            print(f"Syntax errors: {len(syntax_errors)}")

    return 0


def _run_symbol(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)
        results = collect_python_symbols(repo_root, python_files)
        symbols = flatten_symbol_results(results)

        path_filter = None
        if args.path:
            target = resolve_user_path(repo_root, args.path, allow_absolute=False, allow_hard_excluded=False)
            path_filter = to_posix_relative(repo_root, target)

        matches = find_symbol_matches(symbols, args.symbol_name, path=path_filter)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        matches_payload = {
            "query": args.symbol_name,
            "matches": [asdict(record) for record in matches],
            "count": len(matches),
        }
        matches_path = write_json_report(layout.latest_dir / "symbol_matches.json", matches_payload)

        if not matches:
            manifest = build_manifest(
                **_base_manifest_args(
                    args,
                    repo_root,
                    "symbol",
                    {
                        "manifest_json": ".codecontext/latest/manifest.json",
                        "symbol_matches_json": ".codecontext/latest/symbol_matches.json",
                    },
                    file_universe=universe.manifest_counts() if universe is not None else None,
                )
            )
            write_manifest_bundle(layout, manifest)
            copy_latest_to_run(layout)
            print(redact_console_text(f"ERROR: No symbol matched query: {args.symbol_name}"))
            return EXIT_GENERAL_ERROR

        selected = matches[0]
        if len(matches) > 1 and not args.first and not args.path:
            manifest = build_manifest(
                **_base_manifest_args(
                    args,
                    repo_root,
                    "symbol",
                    {
                        "manifest_json": ".codecontext/latest/manifest.json",
                        "symbol_matches_json": ".codecontext/latest/symbol_matches.json",
                    },
                    file_universe=universe.manifest_counts() if universe is not None else None,
                )
            )
            write_manifest_bundle(layout, manifest)
            copy_latest_to_run(layout)
            print(f"ERROR: Ambiguous symbol query matched {len(matches)} symbols. Use --first or --path.")
            print(f"Symbol matches: {display_path(repo_root, matches_path, absolute=args.absolute_paths)}")
            return EXIT_GENERAL_ERROR

        target_path = repo_root / selected.path
        start = max(1, selected.start_line - args.context)
        end = selected.end_line + args.context
        excerpt = build_file_excerpt(
            repo_root,
            target_path,
            line_selector=f"{start}:{end}",
            context=args.context,
            max_file_bytes=min(args.max_file_bytes, DEFAULT_MAX_EXCERPT_BYTES),
        )

        excerpt_markdown = "\n".join(
            [
                "# CBL Symbol Excerpt",
                "",
                f"Symbol: {selected.qualified_name}",
                f"Kind: {selected.kind}",
                f"Definition: {selected.path}:L{selected.start_line}-L{selected.end_line}",
                "",
                render_excerpt_markdown(excerpt),
            ]
        )

        excerpt_path = layout.latest_dir / "symbol_excerpt.md"
        excerpt_path.write_text(excerpt_markdown + "\n", encoding="utf-8", newline="\n")

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "symbol",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "symbol_matches_json": ".codecontext/latest/symbol_matches.json",
                    "symbol_excerpt_md": ".codecontext/latest/symbol_excerpt.md",
                },
                file_universe=universe.manifest_counts() if universe is not None else None,
                redaction={
                    "enabled": True,
                    "redacted_files_count": 1 if excerpt.redaction.redacted_occurrences_count else 0,
                    "redacted_occurrences_count": excerpt.redaction.redacted_occurrences_count,
                    "patterns_hit": list(excerpt.redaction.patterns_hit),
                },
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
        print(redact_console_text(f"ERROR: Could not write symbol excerpt: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print(excerpt_markdown)
        print(f"Symbol matches: {display_path(repo_root, matches_path, absolute=args.absolute_paths)}")
        print(f"Symbol excerpt: {display_path(repo_root, excerpt_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")

    return 0


def _run_imports(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)

        results = collect_python_imports(repo_root, python_files)
        imports = flatten_import_results(results)
        imports = filter_imports_by_module(imports, args.module)
        syntax_errors = _syntax_errors_from_import_results(results)

        payload = import_records_payload(imports, syntax_errors=syntax_errors)
        payload["limitations"] = []
        if args.reverse:
            payload["limitations"].append("Reverse import grouping is not yet implemented; raw records include resolved_project_path for downstream grouping.")
        if args.cycles:
            payload["limitations"].append("Cycle detection is not yet implemented; this slice only emits direct static import records.")

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        imports_path = write_json_report(layout.latest_dir / "imports.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "imports",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "imports_json": ".codecontext/latest/imports.json",
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
        print(redact_console_text(f"ERROR: Could not write import report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL imports: OK")
        print(f"Python files analyzed: {len(python_files)}")
        print(f"Imports: {len(imports)}")
        print(f"Resolved project imports: {payload['counts']['resolved_project_imports']}")
        print(f"Imports report: {display_path(repo_root, imports_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for limitation in payload["limitations"]:
            print(f"WARNING: {limitation}")
        if syntax_errors:
            print(f"Syntax errors: {len(syntax_errors)}")

    return 0


def _run_partial(args: argparse.Namespace) -> int:
    result = CblCommandResult.partial(
        str(args.command),
        f"The '{args.command}' command is reserved by the command surface but is not implemented yet.",
    )
    emit_result(result, quiet=args.quiet)
    return result.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_INVALID_ARGUMENTS

    if args.command not in PUBLIC_COMMANDS:
        parser.error(f"Unknown command: {args.command}")

    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
''',

    "tests/test_python_evidence.py": r'''
from __future__ import annotations

from pathlib import Path

from codebase_lens.analyzers.imports import collect_imports_for_file, resolve_project_import
from codebase_lens.analyzers.python_ast import collect_symbols_for_file, find_symbol_matches


def test_collect_symbols_for_file_detects_classes_functions_methods_and_decorators(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source_dir = repo / "src" / "pkg"
    source_dir.mkdir(parents=True)
    source = source_dir / "module.py"
    source.write_text(
        "\n".join(
            [
                "def top_level(a: int) -> int:",
                "    return a + 1",
                "",
                "class Worker:",
                "    \"\"\"Worker docstring.\"\"\"",
                "    @classmethod",
                "    def build(cls):",
                "        return cls()",
                "",
                "    async def run(self):",
                "        return None",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = collect_symbols_for_file(repo, source)

    assert result.syntax_errors == ()
    names = {(record.kind, record.qualified_name) for record in result.symbols}
    assert ("function", "top_level") in names
    assert ("class", "Worker") in names
    assert ("method", "Worker.build") in names
    assert ("method", "Worker.run") in names

    build = [record for record in result.symbols if record.qualified_name == "Worker.build"][0]
    assert "classmethod" in build.decorators
    assert build.start_line == 7
    assert build.end_line == 8

    matches = find_symbol_matches(result.symbols, "build")
    assert len(matches) == 1
    assert matches[0].qualified_name == "Worker.build"


def test_collect_imports_resolves_project_imports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    package = repo / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helpers.py").write_text("VALUE = 1\n", encoding="utf-8")
    source = package / "module.py"
    source.write_text(
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                "from .helpers import VALUE",
                "from pkg import helpers",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = collect_imports_for_file(repo, source)

    assert result.syntax_errors == ()
    imports = result.imports
    assert any(record.module == "os" for record in imports)
    assert any(record.module == "pathlib" and record.name == "Path" for record in imports)
    assert any(record.module == "helpers" and record.name == "VALUE" and record.resolved_project_path == "src/pkg/helpers.py" for record in imports)
    assert any(record.module == "pkg" and record.name == "helpers" and record.resolved_project_path == "src/pkg/helpers.py" for record in imports)

    resolved = resolve_project_import(repo, source, module="pkg.helpers", name=None, level=0)
    assert resolved == "src/pkg/helpers.py"


def test_syntax_errors_are_reported_without_raising(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bad = repo / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")

    symbol_result = collect_symbols_for_file(repo, bad)
    import_result = collect_imports_for_file(repo, bad)

    assert symbol_result.symbols == ()
    assert import_result.imports == ()
    assert symbol_result.syntax_errors
    assert import_result.syntax_errors
''',

    "tests/test_python_evidence_cli.py": r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def test_symbols_command_writes_symbols_json() -> None:
    result = run_cbl("symbols", "--path", "src/codebase_lens/cli.py", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL symbols: OK" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    symbols_path = ROOT / ".codecontext" / "latest" / "symbols.json"
    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"

    assert symbols_path.is_file()
    assert manifest_path.is_file()

    payload = json.loads(symbols_path.read_text(encoding="utf-8"))
    names = {record["name"] for record in payload["symbols"]}
    assert "build_parser" in names
    assert "main" in names

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "symbols"
    assert manifest["outputs"]["symbols_json"] == ".codecontext/latest/symbols.json"


def test_symbols_command_can_print_json() -> None:
    result = run_cbl("symbols", "--path", "src/codebase_lens/cli.py", "--query", "build_parser", "--json", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["counts"]["total"] >= 1
    assert any(record["name"] == "build_parser" for record in payload["symbols"])


def test_symbol_command_writes_symbol_excerpt() -> None:
    result = run_cbl("symbol", "build_parser", "--path", "src/codebase_lens/cli.py", "--first", "--context", "2", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL Symbol Excerpt" in result.stdout
    assert "Symbol: build_parser" in result.stdout
    assert "Definition: src/codebase_lens/cli.py" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    excerpt_path = ROOT / ".codecontext" / "latest" / "symbol_excerpt.md"
    matches_path = ROOT / ".codecontext" / "latest" / "symbol_matches.json"

    assert excerpt_path.is_file()
    assert matches_path.is_file()

    matches = json.loads(matches_path.read_text(encoding="utf-8"))
    assert matches["count"] >= 1


def test_imports_command_writes_imports_json() -> None:
    result = run_cbl("imports", "--path", "src/codebase_lens/cli.py", "--module", "codebase_lens", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL imports: OK" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    imports_path = ROOT / ".codecontext" / "latest" / "imports.json"
    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"

    assert imports_path.is_file()
    assert manifest_path.is_file()

    payload = json.loads(imports_path.read_text(encoding="utf-8"))
    assert payload["counts"]["total"] >= 1
    assert any("codebase_lens" in (record["module"] or "") or "codebase_lens" in record["raw"] for record in payload["imports"])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "imports"
    assert manifest["outputs"]["imports_json"] == ".codecontext/latest/imports.json"
''',

    "scripts/dev/audits/audit_phase3_python_evidence.py": r'''
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/analyzers/python_ast.py": [
        "PythonAnalysisResult",
        "collect_symbols_for_file",
        "collect_python_symbols",
        "flatten_symbol_results",
        "find_symbol_matches",
    ],
    "src/codebase_lens/analyzers/imports.py": [
        "PythonImportAnalysisResult",
        "collect_imports_for_file",
        "collect_python_imports",
        "flatten_import_results",
        "filter_imports_by_module",
        "resolve_project_import",
    ],
    "src/codebase_lens/reports/json.py": [
        "write_json_report",
        "symbol_records_payload",
        "import_records_payload",
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


def main() -> int:
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    symbols = run_cbl("symbols", "--path", "src/codebase_lens/cli.py", "--no-archive")
    if symbols.returncode != 0:
        fail(f"cbl symbols failed:\nSTDOUT:\n{symbols.stdout}\nSTDERR:\n{symbols.stderr}")
    if "CBL symbols: OK" not in symbols.stdout:
        fail("cbl symbols did not report success.")
    if "C:\\Users\\" in symbols.stdout:
        fail("cbl symbols leaked an absolute Windows user path.")

    symbols_path = ROOT / ".codecontext" / "latest" / "symbols.json"
    if not symbols_path.is_file():
        fail("cbl symbols did not write symbols.json.")
    symbols_payload = json.loads(symbols_path.read_text(encoding="utf-8"))
    symbol_names = {record["name"] for record in symbols_payload["symbols"]}
    if "build_parser" not in symbol_names:
        fail("symbols.json does not include build_parser from cli.py.")

    symbol_json = run_cbl("symbols", "--path", "src/codebase_lens/cli.py", "--query", "build_parser", "--json", "--no-archive")
    if symbol_json.returncode != 0:
        fail("cbl symbols --json failed.")
    try:
        parsed_symbol_stdout = json.loads(symbol_json.stdout)
    except json.JSONDecodeError as exc:
        fail(f"cbl symbols --json did not emit valid JSON: {exc}")
    if not any(record["name"] == "build_parser" for record in parsed_symbol_stdout["symbols"]):
        fail("cbl symbols --json did not include build_parser.")

    symbol = run_cbl("symbol", "build_parser", "--path", "src/codebase_lens/cli.py", "--first", "--context", "2", "--no-archive")
    if symbol.returncode != 0:
        fail(f"cbl symbol failed:\nSTDOUT:\n{symbol.stdout}\nSTDERR:\n{symbol.stderr}")
    if "CBL Symbol Excerpt" not in symbol.stdout:
        fail("cbl symbol did not emit a symbol excerpt.")
    if "Definition: src/codebase_lens/cli.py" not in symbol.stdout:
        fail("cbl symbol did not emit a relative definition line.")
    if "C:\\Users\\" in symbol.stdout:
        fail("cbl symbol leaked an absolute Windows user path.")

    excerpt_path = ROOT / ".codecontext" / "latest" / "symbol_excerpt.md"
    matches_path = ROOT / ".codecontext" / "latest" / "symbol_matches.json"
    if not excerpt_path.is_file():
        fail("cbl symbol did not write symbol_excerpt.md.")
    if not matches_path.is_file():
        fail("cbl symbol did not write symbol_matches.json.")

    imports = run_cbl("imports", "--path", "src/codebase_lens/cli.py", "--module", "codebase_lens", "--no-archive")
    if imports.returncode != 0:
        fail(f"cbl imports failed:\nSTDOUT:\n{imports.stdout}\nSTDERR:\n{imports.stderr}")
    if "CBL imports: OK" not in imports.stdout:
        fail("cbl imports did not report success.")
    if "C:\\Users\\" in imports.stdout:
        fail("cbl imports leaked an absolute Windows user path.")

    imports_path = ROOT / ".codecontext" / "latest" / "imports.json"
    if not imports_path.is_file():
        fail("cbl imports did not write imports.json.")

    imports_payload = json.loads(imports_path.read_text(encoding="utf-8"))
    if imports_payload["counts"]["total"] < 1:
        fail("imports.json contains no imports for cli.py.")
    if not any("codebase_lens" in (record["module"] or "") or "codebase_lens" in record["raw"] for record in imports_payload["imports"]):
        fail("imports.json does not include codebase_lens imports.")

    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["command"]["subcommand"] != "imports":
        fail("manifest command.subcommand should be imports after cbl imports.")
    if manifest["outputs"].get("imports_json") != ".codecontext/latest/imports.json":
        fail("manifest does not declare imports_json output.")

    print("PASS: Phase 3 Python evidence audit passed.")
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


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    print("Slice 004 applied: Phase 3 Python evidence layer implemented.")
    print("Run the Phase 3 audit and pytest before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())