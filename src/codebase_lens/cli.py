from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from codebase_lens import __version__
from codebase_lens.analyzers.changed_symbols import changed_symbol_result_payload, map_changed_symbols
from codebase_lens.analyzers.callers import collect_callers
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
from codebase_lens.analyzers.tests import collect_test_inventory
from codebase_lens.contracts.architecture import evaluate_contract, load_contract_spec
from codebase_lens.core.constants import (
    DEFAULT_BUDGET,
    DEFAULT_MAX_EXCERPT_BYTES,
    DEFAULT_MAX_FILE_BYTES,
    EXIT_CONTRACT_FAILURE,
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
    caller_records_payload,
    changed_files_payload,
    contract_result_payload,
    command_records_payload,
    import_records_payload,
    route_records_payload,
    symbol_records_payload,
    test_inventory_payload,
    write_json_report,
)
from codebase_lens.reports.manifest import build_manifest, copy_latest_to_run, prepare_output_layout, write_manifest_bundle
from codebase_lens.reports.scanner_outputs import write_file_inventory, write_tree_report
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
    tests.set_defaults(handler=_run_tests_inventory)

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
    callers.add_argument("--path")
    callers.set_defaults(handler=_run_callers)

    contract = sub.add_parser("contract", parents=[parent], help="Audit repository against an architecture contract.")
    contract.add_argument("--spec")
    contract.add_argument("--no-fail-exit", action="store_true")
    contract.set_defaults(handler=_run_contract)

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




def _run_contract(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        spec = load_contract_spec(repo_root, args.spec)
        result = evaluate_contract(repo_root, spec)
        payload = contract_result_payload(result)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        contract_path = write_json_report(layout.latest_dir / "contract_report.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "contract",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "contract_report_json": ".codecontext/latest/contract_report.json",
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
        print(redact_console_text(f"ERROR: Could not write contract report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        status = "OK" if result.counts["errors"] == 0 else "VIOLATIONS"
        print(f"CBL contract: {status}")
        print(f"Contract: {result.name}")
        print(f"Violations: {result.counts['violations']}")
        print(f"Errors: {result.counts['errors']}")
        print(f"Warnings: {result.counts['warnings']}")
        print(f"Python files checked: {result.counts['python_files_checked']}")
        print(f"Contract report: {display_path(repo_root, contract_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")

    if result.counts["errors"] and not args.no_fail_exit:
        return EXIT_CONTRACT_FAILURE

    return 0


def _run_tests_inventory(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)

        inventory = collect_test_inventory(
            repo_root,
            python_files,
            target=args.target,
            include_fixtures=args.show_fixtures,
        )
        payload = test_inventory_payload(inventory)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        tests_path = write_json_report(layout.latest_dir / "tests_inventory.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "tests",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "tests_inventory_json": ".codecontext/latest/tests_inventory.json",
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
        print(redact_console_text(f"ERROR: Could not write test inventory report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL tests: OK")
        print(f"Python files analyzed: {len(python_files)}")
        print(f"Test files: {payload['counts']['test_files']}")
        print(f"Test functions: {payload['counts']['test_functions']}")
        print(f"Test classes: {payload['counts']['test_classes']}")
        print(f"Fixtures: {payload['counts']['fixtures']}")
        print(f"Tests inventory: {display_path(repo_root, tests_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        if inventory.syntax_errors:
            print(f"Syntax errors: {len(inventory.syntax_errors)}")

    return 0


def _run_callers(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        python_files, universe = _python_files_for_analysis(args, repo_root)

        result = collect_callers(repo_root, python_files, args.name)
        payload = caller_records_payload(result)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        callers_path = write_json_report(layout.latest_dir / "callers.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "callers",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "callers_json": ".codecontext/latest/callers.json",
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
        print(redact_console_text(f"ERROR: Could not write caller report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL callers: OK")
        print(f"Python files analyzed: {len(python_files)}")
        print(f"Query: {args.name}")
        print(f"Call sites: {payload['counts']['total']}")
        print(f"Files with call sites: {payload['counts']['files']}")
        print(f"Callers report: {display_path(repo_root, callers_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        if result.syntax_errors:
            print(f"Syntax errors: {len(result.syntax_errors)}")

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
