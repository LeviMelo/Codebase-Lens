from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    ".gitignore": """
.codecontext/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
*.egg-info/
build/
dist/
.vscode/
.idea/
.DS_Store
Thumbs.db
""",

    "pyproject.toml": """
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "codebase-lens"
version = "0.1.0"
description = "Local repository evidence engine for AI-assisted coding."
readme = "README.md"
requires-python = ">=3.10"
dependencies = ["PyYAML>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
cbl = "codebase_lens.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"
""",

    "README.md": """
# Local Codebase Lens

CBL is a local-only repository inspection and context-transfer tool for AI-assisted coding.

This repository is currently in Phase 0: scaffold and public command surface.

Canonical invocation:

    python -m codebase_lens --help

After editable install:

    cbl --help

Most commands intentionally return a partial-implementation message in Phase 0. Phase 1 will implement the safety foundation.
""",

    "src/codebase_lens/__init__.py": """
__version__ = "0.1.0"
SPEC_VERSION = "1.0"
TOOL_NAME = "Local Codebase Lens"
""",

    "src/codebase_lens/__main__.py": """
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
""",

    "src/codebase_lens/core/__init__.py": """
\"\"\"Core primitives for CBL.\"\"\"
""",

    "src/codebase_lens/core/constants.py": """
DEFAULT_BUDGET = 16000

PARTIAL_IMPLEMENTATION_MESSAGE = (
    "PARTIAL IMPLEMENTATION: this command exists but is not complete in the current milestone."
)

PUBLIC_COMMANDS = (
    "doctor",
    "snapshot",
    "tree",
    "symbols",
    "imports",
    "cli",
    "routes",
    "tests",
    "diff",
    "changed",
    "file",
    "symbol",
    "callers",
    "contract",
    "pack",
    "clean",
)

EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_INVALID_ARGUMENTS = 2
EXIT_ROOT_DETECTION_FAILURE = 3
EXIT_PATH_SAFETY_VIOLATION = 4
EXIT_CONTRACT_VIOLATION = 5
EXIT_UNSAFE_OPTION_REJECTED = 6
EXIT_OUTPUT_WRITE_FAILURE = 7
""",

    "src/codebase_lens/core/result.py": """
from __future__ import annotations

from dataclasses import dataclass

from .constants import EXIT_GENERAL_ERROR, EXIT_SUCCESS, PARTIAL_IMPLEMENTATION_MESSAGE


@dataclass(frozen=True)
class CblCommandResult:
    command: str
    status: str
    exit_code: int
    message: str
    detail: str | None = None

    @classmethod
    def success(cls, command: str, message: str, detail: str | None = None) -> "CblCommandResult":
        return cls(command, "success", EXIT_SUCCESS, message, detail)

    @classmethod
    def partial(cls, command: str, detail: str) -> "CblCommandResult":
        return cls(command, "partial", EXIT_GENERAL_ERROR, PARTIAL_IMPLEMENTATION_MESSAGE, detail)


def emit_result(result: CblCommandResult, *, quiet: bool = False) -> None:
    if quiet:
        return
    print(f"CBL command: {result.command}")
    print(f"Status: {result.status}")
    print(result.message)
    if result.detail:
        print(f"Detail: {result.detail}")
""",

    "src/codebase_lens/core/models.py": """
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileRecord:
    path: str
    absolute_path: str
    status: str
    git_status: str | None
    extension: str | None
    size_bytes: int
    sha256: str | None
    is_text: bool
    is_binary: bool
    is_large: bool
    is_included: bool
    skip_reason: str | None
    language: str | None
    line_count: int | None
    redacted: bool


@dataclass(frozen=True)
class SymbolRecord:
    id: str
    name: str
    qualified_name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    signature: str | None
    decorators: list[str]
    parent: str | None
    docstring_summary: str | None
    imports_used: list[str]
    is_exported: bool | None
    confidence: str


@dataclass(frozen=True)
class ImportRecord:
    path: str
    line: int
    module: str | None
    name: str | None
    alias: str | None
    level: int
    raw: str
    resolved_project_path: str | None
    confidence: str


@dataclass(frozen=True)
class CommandRecord:
    framework: str
    command_path: str
    function_name: str | None
    path: str
    start_line: int
    end_line: int
    decorators: list[str]
    help_text: str | None
    confidence: str
    limitations: list[str]


@dataclass(frozen=True)
class RouteRecord:
    framework: str
    method: str | None
    route_path: str | None
    function_name: str
    path: str
    start_line: int
    end_line: int
    decorators: list[str]
    confidence: str


@dataclass(frozen=True)
class TestRecord:
    path: str
    test_kind: str
    test_functions: list[str]
    test_classes: list[str]
    likely_targets: list[str]
    confidence: str


@dataclass(frozen=True)
class ContractFinding:
    rule_id: str
    severity: str
    status: str
    title: str
    message: str
    evidence: list[str]
    confidence: str
    remediation_hint: str | None


@dataclass(frozen=True)
class OmissionRecord:
    path: str
    reason: str
    size_bytes: int | None
    category: str | None
""",

    "src/codebase_lens/cli.py": """
from __future__ import annotations

import argparse
from collections.abc import Sequence

from codebase_lens import __version__
from codebase_lens.core.constants import DEFAULT_BUDGET, EXIT_INVALID_ARGUMENTS, PUBLIC_COMMANDS
from codebase_lens.core.result import CblCommandResult, emit_result


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="Repository root override. Defaults to current directory.")
    parser.add_argument("--out", default=".codecontext", help="Output directory. Defaults to .codecontext.")
    parser.add_argument("--format", choices=("markdown", "json", "both"), default="both")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--absolute-paths", action="store_true")
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
    tree.set_defaults(handler=_run_partial)

    symbols = sub.add_parser("symbols", parents=[parent], help="List Python symbols.")
    symbols.add_argument("--kind", choices=("function", "class", "method", "all"), default="all")
    symbols.add_argument("--path")
    symbols.add_argument("--query")
    symbols.add_argument("--json", action="store_true")
    symbols.set_defaults(handler=_run_partial)

    imports = sub.add_parser("imports", parents=[parent], help="Summarize import graph.")
    imports.add_argument("--path")
    imports.add_argument("--module")
    imports.add_argument("--reverse", action="store_true")
    imports.add_argument("--cycles", action="store_true")
    imports.set_defaults(handler=_run_partial)

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
    file_cmd.set_defaults(handler=_run_partial)

    symbol = sub.add_parser("symbol", parents=[parent], help="Emit one or more symbol excerpts.")
    symbol.add_argument("symbol_name")
    symbol.add_argument("--context", type=int, default=20)
    symbol.add_argument("--path")
    symbol.add_argument("--first", action="store_true")
    symbol.set_defaults(handler=_run_partial)

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


def _run_doctor(args: argparse.Namespace) -> int:
    result = CblCommandResult.partial(
        "doctor",
        "Phase 0 placeholder. Phase 1 must implement real root detection, path safety, redaction readiness, Git readiness, and output-directory checks.",
    )
    emit_result(result, quiet=args.quiet)
    return result.exit_code


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
""",

    "tests/conftest.py": """
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
""",

    "tests/test_phase0_cli.py": """
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from codebase_lens.core.constants import PARTIAL_IMPLEMENTATION_MESSAGE, PUBLIC_COMMANDS

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


def test_top_level_help_renders_command_surface() -> None:
    result = run_cbl("--help")
    assert result.returncode == 0
    for command in ("doctor", "pack", "contract", "changed", "callers"):
        assert command in result.stdout


def test_doctor_is_explicit_partial_implementation() -> None:
    result = run_cbl("doctor")
    assert result.returncode == 1
    assert "CBL command: doctor" in result.stdout
    assert PARTIAL_IMPLEMENTATION_MESSAGE in result.stdout


def test_all_public_commands_have_help() -> None:
    for command in PUBLIC_COMMANDS:
        result = run_cbl(command, "--help")
        assert result.returncode == 0, command
""",

    "scripts/dev/audits/audit_phase0_scaffold.py": """
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

PUBLIC_COMMANDS = (
    "doctor",
    "snapshot",
    "tree",
    "symbols",
    "imports",
    "cli",
    "routes",
    "tests",
    "diff",
    "changed",
    "file",
    "symbol",
    "callers",
    "contract",
    "pack",
    "clean",
)

REQUIRED_FILES = [
    "pyproject.toml",
    "README.md",
    ".gitignore",
    "src/codebase_lens/__init__.py",
    "src/codebase_lens/__main__.py",
    "src/codebase_lens/cli.py",
    "src/codebase_lens/core/constants.py",
    "src/codebase_lens/core/result.py",
    "src/codebase_lens/core/models.py",
    "tests/test_phase0_cli.py",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


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
    for file in REQUIRED_FILES:
        if not (ROOT / file).is_file():
            fail(f"Missing required file: {file}")

    help_result = run_cbl("--help")
    if help_result.returncode != 0:
        fail(help_result.stderr)

    for command in PUBLIC_COMMANDS:
        if command not in help_result.stdout:
            fail(f"Missing command in top-level help: {command}")

        command_help = run_cbl(command, "--help")
        if command_help.returncode != 0:
            fail(f"Help failed for command: {command}")

    doctor = run_cbl("doctor")
    if doctor.returncode != 1:
        fail(f"doctor should return 1 during Phase 0, got {doctor.returncode}")

    if "PARTIAL IMPLEMENTATION" not in doctor.stdout:
        fail("doctor did not report explicit partial implementation")

    print("PASS: Phase 0 scaffold audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
}

EMPTY_MODULES = [
    "src/codebase_lens/core/config.py",
    "src/codebase_lens/core/paths.py",
    "src/codebase_lens/core/budget.py",
    "src/codebase_lens/core/redaction.py",
    "src/codebase_lens/core/textio.py",
    "src/codebase_lens/core/hashing.py",
    "src/codebase_lens/core/rendering.py",
    "src/codebase_lens/git/__init__.py",
    "src/codebase_lens/git/discover.py",
    "src/codebase_lens/git/status.py",
    "src/codebase_lens/git/diff.py",
    "src/codebase_lens/git/ignore.py",
    "src/codebase_lens/scanners/__init__.py",
    "src/codebase_lens/scanners/universe.py",
    "src/codebase_lens/scanners/inventory.py",
    "src/codebase_lens/scanners/tree.py",
    "src/codebase_lens/scanners/text.py",
    "src/codebase_lens/scanners/binary.py",
    "src/codebase_lens/analyzers/__init__.py",
    "src/codebase_lens/analyzers/python_ast.py",
    "src/codebase_lens/analyzers/imports.py",
    "src/codebase_lens/analyzers/cli_static.py",
    "src/codebase_lens/analyzers/routes_static.py",
    "src/codebase_lens/analyzers/tests.py",
    "src/codebase_lens/analyzers/changed_symbols.py",
    "src/codebase_lens/analyzers/excerpts.py",
    "src/codebase_lens/analyzers/callers.py",
    "src/codebase_lens/analyzers/contracts.py",
    "src/codebase_lens/reports/__init__.py",
    "src/codebase_lens/reports/manifest.py",
    "src/codebase_lens/reports/markdown.py",
    "src/codebase_lens/reports/json.py",
    "src/codebase_lens/reports/snapshot.py",
    "src/codebase_lens/reports/handoff.py",
    "src/codebase_lens/reports/contract.py",
    "src/codebase_lens/reports/diff.py",
    "src/codebase_lens/contracts/__init__.py",
    "src/codebase_lens/contracts/schema.py",
    "src/codebase_lens/contracts/builtin_templates.py",
]

FIXTURE_DIRS = [
    "tests/fixtures/tiny_python_repo",
    "tests/fixtures/redaction_repo",
    "tests/fixtures/git_state_repo",
    "tests/fixtures/contract_repo",
    "tests/fixtures/typer_repo",
]


def write_file(relative_path: str, content: str) -> None:
    path = ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = dedent(content).strip("\n") + "\n"
    path.write_text(normalized.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    for relative_path in EMPTY_MODULES:
        write_file(relative_path, '"""Reserved module boundary for CBL. Implementation arrives in later slices."""\n')

    for directory in FIXTURE_DIRS:
        path = ROOT / directory
        path.mkdir(parents=True, exist_ok=True)
        write_file(str(Path(directory) / ".gitkeep"), "")

    print("Slice 001 applied: Phase 0 scaffold and command surface created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())