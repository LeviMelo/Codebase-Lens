from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from codebase_lens import __version__
from codebase_lens.analyzers.excerpts import build_file_excerpt, render_excerpt_markdown
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
from codebase_lens.core.paths import detect_repository_root, display_path, gitignore_mentions_codecontext, resolve_user_path
from codebase_lens.core.redaction import redact_console_text
from codebase_lens.core.result import CblCommandResult, emit_result
from codebase_lens.git.discover import collect_git_info
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
    file_cmd.set_defaults(handler=_run_file)

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
