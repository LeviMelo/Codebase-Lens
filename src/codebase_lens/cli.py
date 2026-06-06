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
