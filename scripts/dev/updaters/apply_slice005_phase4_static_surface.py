from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/core/paths.py": r'''
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from .constants import HARD_EXCLUDED_DIR_NAMES, HARD_EXCLUDED_FILE_PATTERNS, STRONG_PROJECT_MARKERS
from .errors import PathSafetyError, RootDetectionError


@dataclass(frozen=True)
class RootInfo:
    root: Path
    method: str
    is_git_repo: bool
    git_root: Path | None
    warnings: tuple[str, ...] = ()


def _run_git_show_toplevel(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None

    value = result.stdout.strip()
    if not value:
        return None

    candidate = Path(value).resolve()
    if candidate.is_dir():
        return candidate
    return None


def _walk_upwards(start: Path) -> list[Path]:
    start = start.resolve()
    if start.is_file():
        start = start.parent
    return [start, *start.parents]


def detect_repository_root(
    start: str | Path | None = None,
    explicit_repo: str | Path | None = None,
    *,
    allow_no_root: bool = False,
) -> RootInfo:
    """Detect the repository root according to the CBL precedence contract."""

    if explicit_repo is not None:
        root = Path(explicit_repo).expanduser().resolve()
        if not root.exists():
            raise RootDetectionError(f"Repository override does not exist: {explicit_repo}")
        if not root.is_dir():
            raise RootDetectionError(f"Repository override is not a directory: {explicit_repo}")

        git_root = _run_git_show_toplevel(root)
        is_exact_git_root = git_root is not None and git_root == root
        is_dot_git_root = (root / ".git").exists()

        warnings: list[str] = []
        if git_root is not None and git_root != root:
            warnings.append(
                "Explicit --repo is inside a larger Git work tree; CBL is honoring the explicit directory as analysis root."
            )

        return RootInfo(
            root=root,
            method="explicit",
            is_git_repo=is_exact_git_root or is_dot_git_root,
            git_root=root if is_exact_git_root or is_dot_git_root else None,
            warnings=tuple(warnings),
        )

    start_path = Path.cwd() if start is None else Path(start).expanduser()
    start_path = start_path.resolve()
    if start_path.is_file():
        start_path = start_path.parent

    git_root = _run_git_show_toplevel(start_path)
    if git_root is not None:
        return RootInfo(root=git_root, method="git", is_git_repo=True, git_root=git_root)

    for candidate in _walk_upwards(start_path):
        if (candidate / ".git").exists():
            return RootInfo(root=candidate, method="dot-git", is_git_repo=True, git_root=candidate)

    for candidate in _walk_upwards(start_path):
        for marker in STRONG_PROJECT_MARKERS:
            if (candidate / marker).exists():
                return RootInfo(root=candidate, method=f"marker:{marker}", is_git_repo=False, git_root=None)

    if allow_no_root:
        return RootInfo(
            root=start_path,
            method="allow-no-root",
            is_git_repo=False,
            git_root=None,
            warnings=("No Git or project marker was found; using current directory because --allow-no-root was supplied.",),
        )

    raise RootDetectionError(
        "Could not detect repository root. Run from inside a Git/project directory or pass --repo."
    )


def to_posix_relative(repo_root: Path, path: Path) -> str:
    resolved_root = repo_root.resolve()
    resolved_path = path.resolve(strict=False)
    try:
        rel = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise PathSafetyError(f"Path is outside repository root: {path}") from exc
    return rel.as_posix()


def is_network_path(raw_path: str) -> bool:
    return raw_path.startswith("\\\\") or raw_path.startswith("//")


def has_windows_drive_prefix(raw_path: str) -> bool:
    return re.match(r"^[A-Za-z]:[\\/]", raw_path) is not None


def is_hard_excluded_relative(relative_posix_path: str) -> bool:
    normalized = relative_posix_path.strip("/").replace("\\", "/")
    if not normalized:
        return False

    parts = tuple(part for part in normalized.split("/") if part)
    for part in parts:
        if part in HARD_EXCLUDED_DIR_NAMES:
            return True

    name = parts[-1]
    pure = PurePosixPath(normalized)
    for pattern in HARD_EXCLUDED_FILE_PATTERNS:
        if fnmatch(name, pattern) or pure.match(pattern):
            return True

    if ".dvc/cache" in normalized:
        return True

    return False


def resolve_user_path(
    repo_root: str | Path,
    user_path: str | Path,
    *,
    allow_absolute: bool = False,
    allow_hard_excluded: bool = False,
) -> Path:
    """Resolve a user-supplied path with containment and hard-exclusion checks."""

    root = Path(repo_root).resolve()
    raw = str(user_path)

    if is_network_path(raw):
        raise PathSafetyError("Network paths are not allowed by default.")

    candidate = Path(user_path).expanduser()

    if candidate.is_absolute() or has_windows_drive_prefix(raw):
        if not allow_absolute:
            raise PathSafetyError("Absolute user-supplied paths are not allowed by default.")
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (root / candidate).resolve(strict=False)

    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise PathSafetyError(f"Path resolves outside repository root: {user_path}") from exc

    relative_posix = relative.as_posix()
    if not allow_hard_excluded and is_hard_excluded_relative(relative_posix):
        raise PathSafetyError(f"Path is hard-excluded by default: {relative_posix}")

    return resolved


def display_path(repo_root: Path, path: Path, *, absolute: bool = False) -> str:
    if absolute:
        return str(path.resolve())
    try:
        return to_posix_relative(repo_root, path)
    except PathSafetyError:
        return path.name


def gitignore_mentions_codecontext(repo_root: Path) -> bool:
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        return False

    try:
        text = gitignore.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = gitignore.read_text(encoding="utf-8", errors="replace")

    lines = [line.strip() for line in text.splitlines()]
    return ".codecontext/" in lines or ".codecontext" in lines
''',

    "src/codebase_lens/analyzers/cli_static.py": r'''
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.models import CommandRecord
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class CliStaticAnalysisResult:
    path: str
    commands: tuple[CommandRecord, ...]
    syntax_errors: tuple[str, ...]
    limitations: tuple[str, ...]


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _call_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"


def _function_name_from_keyword(call: ast.Call, keyword_name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg != keyword_name:
            continue
        if isinstance(keyword.value, ast.Name):
            return keyword.value.id
        if isinstance(keyword.value, ast.Attribute):
            return _call_name(keyword.value)
        return _safe_unparse(keyword.value)
    return None


def _command_name_from_call(call: ast.Call, fallback: str) -> str:
    if call.args:
        first = _literal_string(call.args[0])
        if first:
            return first
    for keyword in call.keywords:
        if keyword.arg in {"name", "help"}:
            value = _literal_string(keyword.value)
            if value and keyword.arg == "name":
                return value
    return fallback.replace("_", "-")


def _decorator_framework(full_name: str) -> str | None:
    lowered = full_name.lower()
    if lowered.startswith("click.") or ".click." in lowered:
        return "click"
    if lowered.endswith(".command") or lowered.endswith(".callback"):
        return "typer"
    if lowered.endswith(".group"):
        return "click"
    return None


def _decorator_is_cli_command(full_name: str) -> bool:
    lowered = full_name.lower()
    return (
        lowered.endswith(".command")
        or lowered.endswith(".callback")
        or lowered.endswith(".group")
        or lowered == "click.command"
        or lowered == "click.group"
    )


def _extract_argparse_commands(repo_root: Path, file_path: Path, tree: ast.AST) -> list[CommandRecord]:
    relative = to_posix_relative(repo_root, file_path)
    by_variable: dict[str, dict[str, object]] = {}
    records_without_variable: list[dict[str, object]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            func = call.func
            if isinstance(func, ast.Attribute) and func.attr == "add_parser":
                command_name = _command_name_from_call(call, fallback="unknown")
                target_name = None
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        target_name = target.id
                        break

                payload: dict[str, object] = {
                    "framework": "argparse",
                    "command_path": command_name,
                    "function_name": None,
                    "path": relative,
                    "start_line": int(getattr(node, "lineno", 1)),
                    "end_line": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                    "decorators": [],
                    "help_text": _function_name_from_keyword(call, "help"),
                    "confidence": "medium",
                    "limitations": ["argparse detection is static and recognizes add_parser/set_defaults patterns only."],
                }

                if target_name:
                    by_variable[target_name] = payload
                else:
                    records_without_variable.append(payload)

        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            func = call.func
            if isinstance(func, ast.Attribute) and func.attr == "set_defaults":
                owner = func.value
                if isinstance(owner, ast.Name) and owner.id in by_variable:
                    handler = _function_name_from_keyword(call, "handler") or _function_name_from_keyword(call, "func")
                    if handler:
                        by_variable[owner.id]["function_name"] = handler
                        by_variable[owner.id]["confidence"] = "high"

    records = [CommandRecord(**payload) for payload in by_variable.values()]
    records.extend(CommandRecord(**payload) for payload in records_without_variable)
    return records


def _extract_decorator_commands(repo_root: Path, file_path: Path, tree: ast.AST) -> list[CommandRecord]:
    relative = to_posix_relative(repo_root, file_path)
    records: list[CommandRecord] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            call: ast.Call | None = decorator if isinstance(decorator, ast.Call) else None
            func = call.func if call else decorator
            full_name = _call_name(func)

            if not _decorator_is_cli_command(full_name):
                continue

            framework = _decorator_framework(full_name) or "unknown"
            command_name = _command_name_from_call(call, node.name) if call else node.name.replace("_", "-")

            records.append(
                CommandRecord(
                    framework=framework,
                    command_path=command_name,
                    function_name=node.name,
                    path=relative,
                    start_line=int(getattr(node, "lineno", 1)),
                    end_line=int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                    decorators=[_safe_unparse(decorator)],
                    help_text=None,
                    confidence="medium" if framework == "unknown" else "high",
                    limitations=["Decorator-based CLI detection is static and does not import target modules."],
                )
            )

    return records


def collect_cli_commands_for_file(repo_root: str | Path, file_path: str | Path) -> CliStaticAnalysisResult:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return CliStaticAnalysisResult(
            path=relative,
            commands=(),
            syntax_errors=(f"{relative}: skipped: {read_result.skipped_reason}",),
            limitations=(),
        )

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return CliStaticAnalysisResult(path=relative, commands=(), syntax_errors=(message,), limitations=())

    records = []
    records.extend(_extract_argparse_commands(root, target, tree))
    records.extend(_extract_decorator_commands(root, target, tree))

    unique: dict[tuple[str, str, str, int], CommandRecord] = {}
    for record in records:
        unique[(record.framework, record.command_path, record.path, record.start_line)] = record

    return CliStaticAnalysisResult(
        path=relative,
        commands=tuple(sorted(unique.values(), key=lambda item: (item.path, item.framework, item.command_path, item.start_line))),
        syntax_errors=(),
        limitations=("Static CLI analysis does not execute or import target application modules.",),
    )


def collect_cli_commands(repo_root: str | Path, python_files: list[str | Path], *, framework: str = "all") -> tuple[CliStaticAnalysisResult, ...]:
    root = Path(repo_root).resolve()
    results: list[CliStaticAnalysisResult] = []

    for path in python_files:
        result = collect_cli_commands_for_file(root, root / Path(path))
        if framework != "all":
            filtered = tuple(record for record in result.commands if record.framework == framework)
            result = CliStaticAnalysisResult(
                path=result.path,
                commands=filtered,
                syntax_errors=result.syntax_errors,
                limitations=result.limitations,
            )
        results.append(result)

    return tuple(results)


def flatten_cli_results(results: tuple[CliStaticAnalysisResult, ...]) -> tuple[CommandRecord, ...]:
    records: list[CommandRecord] = []
    for result in results:
        records.extend(result.commands)
    return tuple(sorted(records, key=lambda item: (item.path, item.framework, item.command_path, item.start_line)))
''',

    "src/codebase_lens/analyzers/routes_static.py": r'''
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.models import RouteRecord
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class RouteStaticAnalysisResult:
    path: str
    routes: tuple[RouteRecord, ...]
    syntax_errors: tuple[str, ...]
    limitations: tuple[str, ...]


HTTP_METHOD_DECORATORS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "options": "OPTIONS",
    "head": "HEAD",
    "websocket": "WEBSOCKET",
}


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_methods(node: ast.AST | None) -> list[str]:
    if isinstance(node, ast.List) or isinstance(node, ast.Tuple) or isinstance(node, ast.Set):
        values: list[str] = []
        for item in node.elts:
            literal = _literal_string(item)
            if literal:
                values.append(literal.upper())
        return values
    literal = _literal_string(node)
    if literal:
        return [literal.upper()]
    return []


def _call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _call_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"


def _route_path_from_call(call: ast.Call) -> str | None:
    if call.args:
        value = _literal_string(call.args[0])
        if value:
            return value
    for keyword in call.keywords:
        if keyword.arg in {"path", "rule"}:
            value = _literal_string(keyword.value)
            if value:
                return value
    return None


def _methods_from_route_call(call: ast.Call, decorator_attr: str) -> list[str | None]:
    if decorator_attr in HTTP_METHOD_DECORATORS:
        return [HTTP_METHOD_DECORATORS[decorator_attr]]

    for keyword in call.keywords:
        if keyword.arg == "methods":
            methods = _literal_methods(keyword.value)
            if methods:
                return methods

    if decorator_attr == "route":
        return ["GET"]

    return [None]


def _framework_for_decorator(full_name: str, decorator_attr: str) -> str:
    lowered = full_name.lower()
    if decorator_attr == "route":
        return "flask"
    if decorator_attr in HTTP_METHOD_DECORATORS:
        return "fastapi"
    if "flask" in lowered:
        return "flask"
    if "router" in lowered or "app" in lowered:
        return "fastapi"
    return "unknown"


def collect_routes_for_file(repo_root: str | Path, file_path: str | Path) -> RouteStaticAnalysisResult:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return RouteStaticAnalysisResult(
            path=relative,
            routes=(),
            syntax_errors=(f"{relative}: skipped: {read_result.skipped_reason}",),
            limitations=(),
        )

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return RouteStaticAnalysisResult(path=relative, routes=(), syntax_errors=(message,), limitations=())

    records: list[RouteRecord] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue

            attr = decorator.func.attr.lower()
            if attr not in HTTP_METHOD_DECORATORS and attr != "route":
                continue

            route_path = _route_path_from_call(decorator)
            methods = _methods_from_route_call(decorator, attr)
            framework = _framework_for_decorator(_call_name(decorator.func), attr)

            for method in methods:
                records.append(
                    RouteRecord(
                        framework=framework,
                        method=method,
                        route_path=route_path,
                        function_name=node.name,
                        path=relative,
                        start_line=int(getattr(node, "lineno", 1)),
                        end_line=int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                        decorators=[_safe_unparse(decorator)],
                        confidence="high" if route_path else "medium",
                    )
                )

    return RouteStaticAnalysisResult(
        path=relative,
        routes=tuple(sorted(records, key=lambda item: (item.path, item.route_path or "", item.method or "", item.function_name))),
        syntax_errors=(),
        limitations=("Static route analysis does not import FastAPI or Flask applications.",),
    )


def collect_routes(repo_root: str | Path, python_files: list[str | Path], *, framework: str = "all") -> tuple[RouteStaticAnalysisResult, ...]:
    root = Path(repo_root).resolve()
    results: list[RouteStaticAnalysisResult] = []

    for path in python_files:
        result = collect_routes_for_file(root, root / Path(path))
        if framework != "all":
            filtered = tuple(record for record in result.routes if record.framework == framework)
            result = RouteStaticAnalysisResult(
                path=result.path,
                routes=filtered,
                syntax_errors=result.syntax_errors,
                limitations=result.limitations,
            )
        results.append(result)

    return tuple(results)


def flatten_route_results(results: tuple[RouteStaticAnalysisResult, ...]) -> tuple[RouteRecord, ...]:
    records: list[RouteRecord] = []
    for result in results:
        records.extend(result.routes)
    return tuple(sorted(records, key=lambda item: (item.path, item.route_path or "", item.method or "", item.function_name)))
''',

    "src/codebase_lens/reports/json.py": r'''
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from codebase_lens.core.models import CommandRecord, ImportRecord, RouteRecord, SymbolRecord
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
from codebase_lens.analyzers.cli_static import collect_cli_commands, flatten_cli_results
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
from codebase_lens.analyzers.routes_static import collect_routes, flatten_route_results
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
from codebase_lens.reports.json import (
    command_records_payload,
    import_records_payload,
    route_records_payload,
    symbol_records_payload,
    write_json_report,
)
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
    cli.set_defaults(handler=_run_cli_static)

    routes = sub.add_parser("routes", parents=[parent], help="Statically discover web routes.")
    routes.add_argument("--framework", choices=("fastapi", "flask", "all"), default="all")
    routes.add_argument("--path")
    routes.set_defaults(handler=_run_routes_static)

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


def _syntax_errors_from_results(results) -> list[str]:
    errors: list[str] = []
    for result in results:
        errors.extend(result.syntax_errors)
    return errors


def _limitations_from_results(results) -> list[str]:
    limitations: set[str] = set()
    for result in results:
        limitations.update(result.limitations)
    return sorted(limitations)


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

        syntax_errors = _syntax_errors_from_results(results)
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
        syntax_errors = _syntax_errors_from_results(results)

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


def _run_cli_static(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)

        results = collect_cli_commands(repo_root, python_files, framework=args.framework)
        commands = flatten_cli_results(results)
        syntax_errors = _syntax_errors_from_results(results)
        limitations = _limitations_from_results(results)

        payload = command_records_payload(commands, syntax_errors=syntax_errors, limitations=limitations)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        commands_path = write_json_report(layout.latest_dir / "commands.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "cli",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "commands_json": ".codecontext/latest/commands.json",
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
        print(redact_console_text(f"ERROR: Could not write CLI command report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL cli: OK")
        print(f"Python files analyzed: {len(python_files)}")
        print(f"Commands: {len(commands)}")
        print(f"Argparse commands: {payload['counts']['argparse']}")
        print(f"Click commands: {payload['counts']['click']}")
        print(f"Typer commands: {payload['counts']['typer']}")
        print(f"Commands report: {display_path(repo_root, commands_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for limitation in limitations:
            print(f"WARNING: {limitation}")
        if syntax_errors:
            print(f"Syntax errors: {len(syntax_errors)}")

    return 0


def _run_routes_static(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)

        results = collect_routes(repo_root, python_files, framework=args.framework)
        routes = flatten_route_results(results)
        syntax_errors = _syntax_errors_from_results(results)
        limitations = _limitations_from_results(results)

        payload = route_records_payload(routes, syntax_errors=syntax_errors, limitations=limitations)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        routes_path = write_json_report(layout.latest_dir / "routes.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "routes",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "routes_json": ".codecontext/latest/routes.json",
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
        print(redact_console_text(f"ERROR: Could not write route report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL routes: OK")
        print(f"Python files analyzed: {len(python_files)}")
        print(f"Routes: {len(routes)}")
        print(f"FastAPI routes: {payload['counts']['fastapi']}")
        print(f"Flask routes: {payload['counts']['flask']}")
        print(f"Routes report: {display_path(repo_root, routes_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for limitation in limitations:
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

    "tests/test_static_surface_integration.py": r'''
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


def make_static_surface_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "surface_repo"
    app = repo / "src" / "demo"
    app.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'surface-repo'\n", encoding="utf-8")

    (app / "commands.py").write_text(
        "\n".join(
            [
                "import argparse",
                "import click",
                "import typer",
                "",
                "typer_app = typer.Typer()",
                "",
                "@typer_app.command('serve')",
                "def serve_app(port: int = 8000):",
                "    return port",
                "",
                "@click.command(name='sync')",
                "def sync_command():",
                "    return None",
                "",
                "def build_parser():",
                "    parser = argparse.ArgumentParser()",
                "    sub = parser.add_subparsers(dest='command')",
                "    doctor = sub.add_parser('doctor', help='check readiness')",
                "    doctor.set_defaults(handler=run_doctor)",
                "    return parser",
                "",
                "def run_doctor(args):",
                "    return 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (app / "routes.py").write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "from flask import Flask",
                "",
                "router = APIRouter()",
                "app = Flask(__name__)",
                "",
                "@router.get('/health')",
                "def health():",
                "    return {'ok': True}",
                "",
                "@router.post('/items')",
                "def create_item():",
                "    return {'id': 1}",
                "",
                "@app.route('/legacy', methods=['GET', 'POST'])",
                "def legacy():",
                "    return 'legacy'",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_static_surface_commands_integrate_scanner_analyzers_reports_and_manifest(tmp_path: Path) -> None:
    repo = make_static_surface_repo(tmp_path)

    cli_result = run_cbl("cli", "--repo", str(repo), "--no-archive")
    assert cli_result.returncode == 0, cli_result.stdout + cli_result.stderr
    assert "CBL cli: OK" in cli_result.stdout
    assert "C:\\Users\\" not in cli_result.stdout

    commands_path = repo / ".codecontext" / "latest" / "commands.json"
    manifest_path = repo / ".codecontext" / "latest" / "manifest.json"
    assert commands_path.is_file()
    assert manifest_path.is_file()

    commands_payload = json.loads(commands_path.read_text(encoding="utf-8"))
    command_paths = {record["command_path"] for record in commands_payload["commands"]}

    assert {"serve", "sync", "doctor"} <= command_paths
    assert commands_payload["counts"]["typer"] >= 1
    assert commands_payload["counts"]["click"] >= 1
    assert commands_payload["counts"]["argparse"] >= 1

    cli_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert cli_manifest["command"]["subcommand"] == "cli"
    assert cli_manifest["outputs"]["commands_json"] == ".codecontext/latest/commands.json"

    routes_result = run_cbl("routes", "--repo", str(repo), "--no-archive")
    assert routes_result.returncode == 0, routes_result.stdout + routes_result.stderr
    assert "CBL routes: OK" in routes_result.stdout
    assert "C:\\Users\\" not in routes_result.stdout

    routes_path = repo / ".codecontext" / "latest" / "routes.json"
    assert routes_path.is_file()

    routes_payload = json.loads(routes_path.read_text(encoding="utf-8"))
    route_keys = {(record["method"], record["route_path"]) for record in routes_payload["routes"]}

    assert ("GET", "/health") in route_keys
    assert ("POST", "/items") in route_keys
    assert ("GET", "/legacy") in route_keys
    assert ("POST", "/legacy") in route_keys

    routes_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert routes_manifest["command"]["subcommand"] == "routes"
    assert routes_manifest["outputs"]["routes_json"] == ".codecontext/latest/routes.json"


def test_explicit_repo_inside_larger_git_tree_is_honored(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)

    subprocess.run(["git", "init"], cwd=outer, text=True, capture_output=True, check=False)

    (inner / "pyproject.toml").write_text("[project]\nname = 'inner'\n", encoding="utf-8")
    (inner / "app.py").write_text("print('inner')\n", encoding="utf-8")

    result = run_cbl("tree", "--repo", str(inner), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repository: inner" in result.stdout
    assert (inner / ".codecontext" / "latest" / "repo_tree.txt").is_file()
''',

    "scripts/dev/audits/audit_phase4_static_surface.py": r'''
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
    "src/codebase_lens/analyzers/cli_static.py": [
        "CliStaticAnalysisResult",
        "collect_cli_commands_for_file",
        "collect_cli_commands",
        "flatten_cli_results",
    ],
    "src/codebase_lens/analyzers/routes_static.py": [
        "RouteStaticAnalysisResult",
        "collect_routes_for_file",
        "collect_routes",
        "flatten_route_results",
    ],
    "src/codebase_lens/reports/json.py": [
        "command_records_payload",
        "route_records_payload",
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


def make_surface_repo(base: Path) -> Path:
    repo = base / "surface_repo"
    package = repo / "src" / "demo"
    package.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'surface-repo'\n", encoding="utf-8")
    (package / "commands.py").write_text(
        "\n".join(
            [
                "import argparse",
                "import click",
                "import typer",
                "",
                "app = typer.Typer()",
                "",
                "@app.command('serve')",
                "def serve():",
                "    pass",
                "",
                "@click.command(name='sync')",
                "def sync_command():",
                "    pass",
                "",
                "def build_parser():",
                "    parser = argparse.ArgumentParser()",
                "    sub = parser.add_subparsers(dest='command')",
                "    doctor = sub.add_parser('doctor', help='check readiness')",
                "    doctor.set_defaults(handler=run_doctor)",
                "    return parser",
                "",
                "def run_doctor(args):",
                "    return 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (package / "routes.py").write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "from flask import Flask",
                "",
                "router = APIRouter()",
                "app = Flask(__name__)",
                "",
                "@router.get('/health')",
                "def health():",
                "    return {'ok': True}",
                "",
                "@router.post('/items')",
                "def create_item():",
                "    return {'id': 1}",
                "",
                "@app.route('/legacy', methods=['GET', 'POST'])",
                "def legacy():",
                "    return 'legacy'",
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

    project_cli = run_cbl("cli", "--path", "src/codebase_lens/cli.py", "--no-archive")
    if project_cli.returncode != 0:
        fail(f"cbl cli on project cli.py failed:\nSTDOUT:\n{project_cli.stdout}\nSTDERR:\n{project_cli.stderr}")
    if "CBL cli: OK" not in project_cli.stdout:
        fail("cbl cli did not report success.")
    if "C:\\Users\\" in project_cli.stdout:
        fail("cbl cli leaked an absolute Windows user path.")

    commands_path = ROOT / ".codecontext" / "latest" / "commands.json"
    if not commands_path.is_file():
        fail("cbl cli did not write commands.json.")

    commands_payload = json.loads(commands_path.read_text(encoding="utf-8"))
    project_commands = {record["command_path"] for record in commands_payload["commands"]}
    required_project_commands = {"doctor", "tree", "symbols", "imports", "cli", "routes", "pack"}
    if not required_project_commands <= project_commands:
        fail(f"commands.json is missing project commands: {sorted(required_project_commands - project_commands)}")

    with tempfile.TemporaryDirectory() as tmp:
        repo = make_surface_repo(Path(tmp))

        cli_result = run_cbl("cli", "--repo", str(repo), "--no-archive")
        if cli_result.returncode != 0:
            fail(f"fixture cbl cli failed:\nSTDOUT:\n{cli_result.stdout}\nSTDERR:\n{cli_result.stderr}")
        if "C:\\Users\\" in cli_result.stdout:
            fail("fixture cbl cli leaked an absolute Windows user path.")

        fixture_commands = json.loads((repo / ".codecontext" / "latest" / "commands.json").read_text(encoding="utf-8"))
        command_paths = {record["command_path"] for record in fixture_commands["commands"]}
        if not {"serve", "sync", "doctor"} <= command_paths:
            fail(f"fixture commands missing expected commands: {sorted({'serve', 'sync', 'doctor'} - command_paths)}")
        if fixture_commands["counts"]["typer"] < 1 or fixture_commands["counts"]["click"] < 1 or fixture_commands["counts"]["argparse"] < 1:
            fail("fixture command framework counts are invalid.")

        routes_result = run_cbl("routes", "--repo", str(repo), "--no-archive")
        if routes_result.returncode != 0:
            fail(f"fixture cbl routes failed:\nSTDOUT:\n{routes_result.stdout}\nSTDERR:\n{routes_result.stderr}")
        if "C:\\Users\\" in routes_result.stdout:
            fail("fixture cbl routes leaked an absolute Windows user path.")

        routes_payload = json.loads((repo / ".codecontext" / "latest" / "routes.json").read_text(encoding="utf-8"))
        route_keys = {(record["method"], record["route_path"]) for record in routes_payload["routes"]}
        required_routes = {("GET", "/health"), ("POST", "/items"), ("GET", "/legacy"), ("POST", "/legacy")}
        if not required_routes <= route_keys:
            fail(f"fixture routes missing expected routes: {sorted(required_routes - route_keys)}")

        manifest = json.loads((repo / ".codecontext" / "latest" / "manifest.json").read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "routes":
            fail("manifest command.subcommand is not routes after cbl routes.")
        if manifest["outputs"].get("routes_json") != ".codecontext/latest/routes.json":
            fail("manifest does not declare routes_json.")

    print("PASS: Phase 4 static surface audit passed.")
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

    print("Slice 005 applied: Phase 4 static command and route discovery implemented.")
    print("Run the Phase 4 audit and integration tests before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())