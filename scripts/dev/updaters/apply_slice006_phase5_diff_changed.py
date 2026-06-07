from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/git/diff.py": r'''
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.paths import is_hard_excluded_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class ChangedHunk:
    path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    heading: str | None


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    origin: str
    additions: int | None
    deletions: int | None
    is_binary: bool
    old_path: str | None
    hunks: tuple[ChangedHunk, ...]


@dataclass(frozen=True)
class ChangedFileSet:
    repo_root: Path
    changed_files: tuple[ChangedFile, ...]
    counts: dict[str, int]
    warnings: tuple[str, ...]


HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<heading>.*)$")


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None


def _is_git_repo(repo_root: Path) -> bool:
    result = _run_git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    return result is not None and result.returncode == 0 and result.stdout.strip().lower() == "true"


def _parse_name_status(stdout: str) -> dict[str, tuple[str, str | None]]:
    parsed: dict[str, tuple[str, str | None]] = {}

    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status_token = parts[0]
        status = status_token[0]

        if status == "R" and len(parts) >= 3:
            old_path = parts[1].replace("\\", "/")
            path = parts[2].replace("\\", "/")
            parsed[path] = ("R", old_path)
        elif len(parts) >= 2:
            path = parts[1].replace("\\", "/")
            parsed[path] = (status, None)

    return parsed


def _parse_numstat(stdout: str) -> dict[str, tuple[int | None, int | None, bool]]:
    parsed: dict[str, tuple[int | None, int | None, bool]] = {}

    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue

        raw_additions, raw_deletions, raw_path = parts[0], parts[1], parts[-1]
        path = raw_path.replace("\\", "/")
        is_binary = raw_additions == "-" or raw_deletions == "-"

        additions = None if is_binary else int(raw_additions)
        deletions = None if is_binary else int(raw_deletions)
        parsed[path] = (additions, deletions, is_binary)

    return parsed


def _parse_hunks(stdout: str) -> dict[str, list[ChangedHunk]]:
    hunks_by_path: dict[str, list[ChangedHunk]] = {}
    current_path: str | None = None

    for line in stdout.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[len("+++ b/") :].replace("\\", "/")
            hunks_by_path.setdefault(current_path, [])
            continue

        match = HUNK_RE.match(line)
        if match is None or current_path is None:
            continue

        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        heading = match.group("heading").strip() or None

        hunks_by_path[current_path].append(
            ChangedHunk(
                path=current_path,
                old_start=int(match.group("old_start")),
                old_count=old_count,
                new_start=int(match.group("new_start")),
                new_count=new_count,
                heading=heading,
            )
        )

    return hunks_by_path


def _collect_diff_origin(repo_root: Path, *, origin: str, diff_prefix: list[str]) -> list[ChangedFile]:
    name_status_result = _run_git(repo_root, [*diff_prefix, "--name-status", "--find-renames", "--"])
    numstat_result = _run_git(repo_root, [*diff_prefix, "--numstat", "--find-renames", "--"])
    hunk_result = _run_git(repo_root, [*diff_prefix, "--unified=0", "--"])

    if name_status_result is None or name_status_result.returncode != 0:
        return []

    name_status = _parse_name_status(name_status_result.stdout)
    numstat = _parse_numstat(numstat_result.stdout if numstat_result and numstat_result.returncode == 0 else "")
    hunks_by_path = _parse_hunks(hunk_result.stdout if hunk_result and hunk_result.returncode == 0 else "")

    files: list[ChangedFile] = []
    for path, (status, old_path) in sorted(name_status.items()):
        if is_hard_excluded_relative(path):
            continue

        additions, deletions, is_binary = numstat.get(path, (0, 0, False))
        files.append(
            ChangedFile(
                path=path,
                status=status,
                origin=origin,
                additions=additions,
                deletions=deletions,
                is_binary=is_binary,
                old_path=old_path,
                hunks=tuple(hunks_by_path.get(path, [])),
            )
        )

    return files


def _collect_untracked(repo_root: Path) -> list[ChangedFile]:
    result = _run_git(repo_root, ["ls-files", "--others", "--exclude-standard"])
    if result is None or result.returncode != 0:
        return []

    files: list[ChangedFile] = []
    for raw_path in sorted(line.strip() for line in result.stdout.splitlines() if line.strip()):
        path = raw_path.replace("\\", "/")
        if is_hard_excluded_relative(path):
            continue

        target = repo_root / path
        if not target.is_file():
            continue

        read_result = read_text_with_policy(target)
        is_binary = read_result.is_binary or read_result.skipped_reason == "binary_skipped"

        additions: int | None
        hunks: tuple[ChangedHunk, ...]
        if read_result.text is not None:
            line_count = max(1, len(read_result.text.splitlines()))
            additions = line_count
            hunks = (
                ChangedHunk(
                    path=path,
                    old_start=0,
                    old_count=0,
                    new_start=1,
                    new_count=line_count,
                    heading="untracked file",
                ),
            )
        else:
            additions = None if is_binary else 0
            hunks = ()

        files.append(
            ChangedFile(
                path=path,
                status="A",
                origin="untracked",
                additions=additions,
                deletions=0 if additions is not None else None,
                is_binary=is_binary,
                old_path=None,
                hunks=hunks,
            )
        )

    return files


def _merge_changed_files(files: list[ChangedFile]) -> tuple[ChangedFile, ...]:
    merged: dict[str, ChangedFile] = {}

    for item in files:
        existing = merged.get(item.path)
        if existing is None:
            merged[item.path] = item
            continue

        origins = sorted(set(existing.origin.split("+")) | set(item.origin.split("+")))
        additions = None if existing.additions is None or item.additions is None else existing.additions + item.additions
        deletions = None if existing.deletions is None or item.deletions is None else existing.deletions + item.deletions

        merged[item.path] = ChangedFile(
            path=item.path,
            status=item.status if item.status != existing.status else existing.status,
            origin="+".join(origins),
            additions=additions,
            deletions=deletions,
            is_binary=existing.is_binary or item.is_binary,
            old_path=existing.old_path or item.old_path,
            hunks=tuple([*existing.hunks, *item.hunks]),
        )

    return tuple(sorted(merged.values(), key=lambda record: record.path))


def _counts(files: tuple[ChangedFile, ...]) -> dict[str, int]:
    return {
        "changed_files_count": len(files),
        "modified_count": sum(1 for item in files if item.status == "M"),
        "added_count": sum(1 for item in files if item.status == "A"),
        "deleted_count": sum(1 for item in files if item.status == "D"),
        "renamed_count": sum(1 for item in files if item.status == "R"),
        "binary_count": sum(1 for item in files if item.is_binary),
        "staged_count": sum(1 for item in files if "staged" in item.origin),
        "unstaged_count": sum(1 for item in files if "unstaged" in item.origin),
        "untracked_count": sum(1 for item in files if "untracked" in item.origin),
        "hunk_count": sum(len(item.hunks) for item in files),
    }


def collect_changed_files(
    repo_root: str | Path,
    *,
    staged: bool = False,
    unstaged: bool = False,
    base: str | None = None,
    include_untracked: bool = True,
) -> ChangedFileSet:
    root = Path(repo_root).resolve()

    if not _is_git_repo(root):
        return ChangedFileSet(
            repo_root=root,
            changed_files=(),
            counts=_counts(()),
            warnings=("Changed-file analysis requires a Git work tree.",),
        )

    files: list[ChangedFile] = []
    warnings: list[str] = []

    if base:
        files.extend(_collect_diff_origin(root, origin=f"base:{base}", diff_prefix=["diff", base]))
    else:
        if staged or not unstaged:
            files.extend(_collect_diff_origin(root, origin="staged", diff_prefix=["diff", "--cached"]))

        if unstaged or not staged:
            files.extend(_collect_diff_origin(root, origin="unstaged", diff_prefix=["diff"]))

        if include_untracked and (unstaged or (not staged and not unstaged)):
            files.extend(_collect_untracked(root))

    changed = _merge_changed_files(files)

    return ChangedFileSet(
        repo_root=root,
        changed_files=changed,
        counts=_counts(changed),
        warnings=tuple(warnings),
    )
''',

    "src/codebase_lens/analyzers/changed_symbols.py": r'''
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from codebase_lens.analyzers.python_ast import collect_symbols_for_file
from codebase_lens.core.models import SymbolRecord
from codebase_lens.git.diff import ChangedFile, ChangedHunk


@dataclass(frozen=True)
class ChangedSymbolRecord:
    path: str
    qualified_name: str
    name: str
    kind: str
    start_line: int
    end_line: int
    change_origin: str
    change_status: str
    touched_hunks: tuple[ChangedHunk, ...]
    confidence: str


@dataclass(frozen=True)
class ChangedSymbolResult:
    changed_symbols: tuple[ChangedSymbolRecord, ...]
    syntax_errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _is_python_path(path: str) -> bool:
    return Path(path).suffix.lower() in {".py", ".pyw", ".pyi"}


def _hunk_touches_symbol(hunk: ChangedHunk, symbol: SymbolRecord) -> bool:
    if hunk.new_count == 0:
        return False

    hunk_start = hunk.new_start
    hunk_end = hunk.new_start + max(hunk.new_count - 1, 0)

    return not (hunk_end < symbol.start_line or hunk_start > symbol.end_line)


def _touched_hunks(changed_file: ChangedFile, symbol: SymbolRecord) -> tuple[ChangedHunk, ...]:
    if changed_file.origin == "untracked":
        return changed_file.hunks

    return tuple(hunk for hunk in changed_file.hunks if _hunk_touches_symbol(hunk, symbol))


def map_changed_symbols(repo_root: str | Path, changed_files: tuple[ChangedFile, ...]) -> ChangedSymbolResult:
    root = Path(repo_root).resolve()
    records: list[ChangedSymbolRecord] = []
    syntax_errors: list[str] = []
    warnings: list[str] = []

    for changed_file in changed_files:
        if not _is_python_path(changed_file.path):
            continue
        if changed_file.status == "D":
            warnings.append(f"Deleted Python file skipped for symbol mapping: {changed_file.path}")
            continue

        target = root / changed_file.path
        if not target.is_file():
            warnings.append(f"Changed Python file does not exist in working tree: {changed_file.path}")
            continue

        analysis = collect_symbols_for_file(root, target)
        syntax_errors.extend(analysis.syntax_errors)

        for symbol in analysis.symbols:
            touched = _touched_hunks(changed_file, symbol)
            if changed_file.origin != "untracked" and not touched:
                continue

            records.append(
                ChangedSymbolRecord(
                    path=symbol.path,
                    qualified_name=symbol.qualified_name,
                    name=symbol.name,
                    kind=symbol.kind,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    change_origin=changed_file.origin,
                    change_status=changed_file.status,
                    touched_hunks=touched,
                    confidence="medium" if changed_file.origin == "untracked" else "high",
                )
            )

    records = sorted(records, key=lambda item: (item.path, item.start_line, item.qualified_name))

    return ChangedSymbolResult(
        changed_symbols=tuple(records),
        syntax_errors=tuple(syntax_errors),
        warnings=tuple(warnings),
    )


def changed_symbol_result_payload(result: ChangedSymbolResult) -> dict[str, object]:
    return {
        "changed_symbols": [asdict(record) for record in result.changed_symbols],
        "syntax_errors": list(result.syntax_errors),
        "warnings": list(result.warnings),
        "counts": {
            "total": len(result.changed_symbols),
            "classes": sum(1 for record in result.changed_symbols if record.kind == "class"),
            "functions": sum(1 for record in result.changed_symbols if record.kind == "function"),
            "methods": sum(1 for record in result.changed_symbols if record.kind == "method"),
        },
    }
''',

    "src/codebase_lens/reports/json.py": r'''
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

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
from codebase_lens.analyzers.changed_symbols import changed_symbol_result_payload, map_changed_symbols
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
from codebase_lens.git.diff import collect_changed_files
from codebase_lens.git.discover import collect_git_info
from codebase_lens.reports.json import (
    changed_files_payload,
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
    diff.set_defaults(handler=_run_diff)

    changed = sub.add_parser("changed", parents=[parent], help="Summarize changed files and changed symbols.")
    changed.add_argument("--staged", action="store_true")
    changed.add_argument("--unstaged", action="store_true")
    changed.add_argument("--base")
    changed.set_defaults(handler=_run_changed)

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


def _run_diff(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        diff_result = collect_changed_files(
            repo_root,
            staged=args.staged,
            unstaged=args.unstaged,
            base=args.base,
            include_untracked=True,
        )

        payload = changed_files_payload(diff_result)

        if args.symbols:
            symbol_result = map_changed_symbols(repo_root, diff_result.changed_files)
            payload["changed_symbols"] = changed_symbol_result_payload(symbol_result)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        diff_path = write_json_report(layout.latest_dir / "diff.json", payload)

        outputs = {
            "manifest_json": ".codecontext/latest/manifest.json",
            "diff_json": ".codecontext/latest/diff.json",
        }

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "diff",
                outputs,
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not write diff report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL diff: OK")
        print(f"Changed files: {diff_result.counts['changed_files_count']}")
        print(f"Staged files: {diff_result.counts['staged_count']}")
        print(f"Unstaged files: {diff_result.counts['unstaged_count']}")
        print(f"Untracked files: {diff_result.counts['untracked_count']}")
        print(f"Hunks: {diff_result.counts['hunk_count']}")
        print(f"Diff report: {display_path(repo_root, diff_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for warning in diff_result.warnings:
            print(f"WARNING: {redact_console_text(warning)}")

    return 0


def _run_changed(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        diff_result = collect_changed_files(
            repo_root,
            staged=args.staged,
            unstaged=args.unstaged,
            base=args.base,
            include_untracked=True,
        )
        symbol_result = map_changed_symbols(repo_root, diff_result.changed_files)

        changed_payload = changed_files_payload(diff_result)
        symbols_payload = changed_symbol_result_payload(symbol_result)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        changed_path = write_json_report(layout.latest_dir / "changed_files.json", changed_payload)
        symbols_path = write_json_report(layout.latest_dir / "changed_symbols.json", symbols_payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "changed",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "changed_files_json": ".codecontext/latest/changed_files.json",
                    "changed_symbols_json": ".codecontext/latest/changed_symbols.json",
                },
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not write changed report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL changed: OK")
        print(f"Changed files: {diff_result.counts['changed_files_count']}")
        print(f"Changed Python symbols: {symbols_payload['counts']['total']}")
        print(f"Changed files report: {display_path(repo_root, changed_path, absolute=args.absolute_paths)}")
        print(f"Changed symbols report: {display_path(repo_root, symbols_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for warning in [*diff_result.warnings, *symbol_result.warnings]:
            print(f"WARNING: {redact_console_text(warning)}")

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

    "tests/test_diff_changed_integration.py": r'''
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def make_changed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "changed_repo"
    repo.mkdir()

    run_git(repo, "init")
    run_git(repo, "config", "user.email", "cbl@example.invalid")
    run_git(repo, "config", "user.name", "CBL Test")

    (repo / ".gitignore").write_text(".codecontext/\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'changed-repo'\n", encoding="utf-8")
    (repo / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    return 1",
                "",
                "def beta():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    run_git(repo, "add", ".")
    commit = run_git(repo, "commit", "-m", "initial")
    assert commit.returncode == 0, commit.stdout + commit.stderr

    (repo / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    value = 10",
                "    return value",
                "",
                "def beta():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "new_module.py").write_text(
        "\n".join(
            [
                "def gamma():",
                "    return 3",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable is not available")
def test_diff_and_changed_commands_integrate_git_hunks_symbols_reports_and_manifest(tmp_path: Path) -> None:
    repo = make_changed_repo(tmp_path)

    diff_result = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
    assert diff_result.returncode == 0, diff_result.stdout + diff_result.stderr
    assert "CBL diff: OK" in diff_result.stdout
    assert "C:\\Users\\" not in diff_result.stdout

    diff_path = repo / ".codecontext" / "latest" / "diff.json"
    manifest_path = repo / ".codecontext" / "latest" / "manifest.json"
    assert diff_path.is_file()
    assert manifest_path.is_file()

    diff_payload = json.loads(diff_path.read_text(encoding="utf-8"))
    changed_paths = {record["path"] for record in diff_payload["changed_files"]}
    assert "module.py" in changed_paths
    assert "new_module.py" in changed_paths
    assert diff_payload["counts"]["changed_files_count"] >= 2
    assert diff_payload["changed_symbols"]["counts"]["total"] >= 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "diff"
    assert manifest["outputs"]["diff_json"] == ".codecontext/latest/diff.json"

    changed_result = run_cbl("changed", "--repo", str(repo), "--no-archive")
    assert changed_result.returncode == 0, changed_result.stdout + changed_result.stderr
    assert "CBL changed: OK" in changed_result.stdout
    assert "C:\\Users\\" not in changed_result.stdout

    changed_files_path = repo / ".codecontext" / "latest" / "changed_files.json"
    changed_symbols_path = repo / ".codecontext" / "latest" / "changed_symbols.json"

    assert changed_files_path.is_file()
    assert changed_symbols_path.is_file()

    changed_files = json.loads(changed_files_path.read_text(encoding="utf-8"))
    changed_symbols = json.loads(changed_symbols_path.read_text(encoding="utf-8"))

    assert {"module.py", "new_module.py"} <= {record["path"] for record in changed_files["changed_files"]}

    symbol_names = {record["qualified_name"] for record in changed_symbols["changed_symbols"]}
    assert "alpha" in symbol_names
    assert "gamma" in symbol_names

    changed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert changed_manifest["command"]["subcommand"] == "changed"
    assert changed_manifest["outputs"]["changed_files_json"] == ".codecontext/latest/changed_files.json"
    assert changed_manifest["outputs"]["changed_symbols_json"] == ".codecontext/latest/changed_symbols.json"
''',

    "scripts/dev/audits/audit_phase5_diff_changed.py": r'''
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/git/diff.py": [
        "ChangedHunk",
        "ChangedFile",
        "ChangedFileSet",
        "collect_changed_files",
    ],
    "src/codebase_lens/analyzers/changed_symbols.py": [
        "ChangedSymbolRecord",
        "ChangedSymbolResult",
        "map_changed_symbols",
        "changed_symbol_result_payload",
    ],
    "src/codebase_lens/reports/json.py": [
        "changed_files_payload",
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


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def make_changed_repo(base: Path) -> Path:
    repo = base / "changed_repo"
    repo.mkdir()

    init = run_git(repo, "init")
    if init.returncode != 0:
        fail(init.stderr)

    run_git(repo, "config", "user.email", "cbl@example.invalid")
    run_git(repo, "config", "user.name", "CBL Test")

    (repo / ".gitignore").write_text(".codecontext/\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'changed-repo'\n", encoding="utf-8")
    (repo / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    return 1",
                "",
                "def beta():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    run_git(repo, "add", ".")
    commit = run_git(repo, "commit", "-m", "initial")
    if commit.returncode != 0:
        fail(commit.stdout + commit.stderr)

    (repo / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    value = 10",
                "    return value",
                "",
                "def beta():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "new_module.py").write_text(
        "\n".join(
            [
                "def gamma():",
                "    return 3",
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

    if shutil.which("git") is None:
        fail("Git executable is required for Phase 5 audit.")

    with tempfile.TemporaryDirectory() as tmp:
        repo = make_changed_repo(Path(tmp))

        diff_result = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
        if diff_result.returncode != 0:
            fail(f"cbl diff failed:\nSTDOUT:\n{diff_result.stdout}\nSTDERR:\n{diff_result.stderr}")
        if "CBL diff: OK" not in diff_result.stdout:
            fail("cbl diff did not report success.")
        if "C:\\Users\\" in diff_result.stdout:
            fail("cbl diff leaked an absolute Windows user path.")

        diff_path = repo / ".codecontext" / "latest" / "diff.json"
        manifest_path = repo / ".codecontext" / "latest" / "manifest.json"
        if not diff_path.is_file():
            fail("cbl diff did not write diff.json.")

        diff_payload = json.loads(diff_path.read_text(encoding="utf-8"))
        changed_paths = {record["path"] for record in diff_payload["changed_files"]}
        if not {"module.py", "new_module.py"} <= changed_paths:
            fail(f"diff.json missing expected changed paths: {sorted({'module.py', 'new_module.py'} - changed_paths)}")
        if diff_payload["counts"]["changed_files_count"] < 2:
            fail("diff.json changed file count is invalid.")
        if diff_payload.get("changed_symbols", {}).get("counts", {}).get("total", 0) < 2:
            fail("diff --symbols did not include expected changed symbols.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "diff":
            fail("manifest command.subcommand is not diff after cbl diff.")
        if manifest["outputs"].get("diff_json") != ".codecontext/latest/diff.json":
            fail("manifest does not declare diff_json.")

        changed_result = run_cbl("changed", "--repo", str(repo), "--no-archive")
        if changed_result.returncode != 0:
            fail(f"cbl changed failed:\nSTDOUT:\n{changed_result.stdout}\nSTDERR:\n{changed_result.stderr}")
        if "CBL changed: OK" not in changed_result.stdout:
            fail("cbl changed did not report success.")
        if "C:\\Users\\" in changed_result.stdout:
            fail("cbl changed leaked an absolute Windows user path.")

        changed_files_path = repo / ".codecontext" / "latest" / "changed_files.json"
        changed_symbols_path = repo / ".codecontext" / "latest" / "changed_symbols.json"

        if not changed_files_path.is_file():
            fail("cbl changed did not write changed_files.json.")
        if not changed_symbols_path.is_file():
            fail("cbl changed did not write changed_symbols.json.")

        changed_files = json.loads(changed_files_path.read_text(encoding="utf-8"))
        changed_symbols = json.loads(changed_symbols_path.read_text(encoding="utf-8"))

        changed_file_paths = {record["path"] for record in changed_files["changed_files"]}
        if not {"module.py", "new_module.py"} <= changed_file_paths:
            fail("changed_files.json missing modified or untracked Python file.")

        symbol_names = {record["qualified_name"] for record in changed_symbols["changed_symbols"]}
        if "alpha" not in symbol_names:
            fail("changed_symbols.json missing modified function alpha.")
        if "gamma" not in symbol_names:
            fail("changed_symbols.json missing untracked function gamma.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "changed":
            fail("manifest command.subcommand is not changed after cbl changed.")
        if manifest["outputs"].get("changed_files_json") != ".codecontext/latest/changed_files.json":
            fail("manifest does not declare changed_files_json.")
        if manifest["outputs"].get("changed_symbols_json") != ".codecontext/latest/changed_symbols.json":
            fail("manifest does not declare changed_symbols_json.")

    print("PASS: Phase 5 diff/changed audit passed.")
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

    print("Slice 006 applied: Phase 5 diff and changed-symbol intelligence implemented.")
    print("Run the Phase 5 audit and integration tests before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())