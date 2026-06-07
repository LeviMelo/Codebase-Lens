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
