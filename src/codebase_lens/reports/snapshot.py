from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codebase_lens.analyzers.changed_symbols import changed_symbol_result_payload, map_changed_symbols
from codebase_lens.analyzers.cli_static import collect_cli_commands, flatten_cli_results
from codebase_lens.analyzers.imports import collect_python_imports, flatten_import_results
from codebase_lens.analyzers.python_ast import collect_python_symbols, flatten_symbol_results
from codebase_lens.analyzers.routes_static import collect_routes, flatten_route_results
from codebase_lens.analyzers.tests import collect_test_inventory
from codebase_lens.git.diff import collect_changed_files
from codebase_lens.reports.json import (
    changed_files_payload,
    command_records_payload,
    import_records_payload,
    route_records_payload,
    symbol_records_payload,
    test_inventory_payload,
    write_json_report,
)
from codebase_lens.reports.manifest import OutputLayout
from codebase_lens.reports.scanner_outputs import write_file_inventory, write_tree_report
from codebase_lens.scanners.universe import discover_file_universe


@dataclass(frozen=True)
class SnapshotBundleResult:
    outputs: dict[str, str]
    counts: dict[str, int]
    warnings: tuple[str, ...]
    changed_only: bool


def _python_files_from_universe(universe) -> list[str]:
    return [
        record.path
        for record in universe.included_files
        if Path(record.path).suffix.lower() in {".py", ".pyw", ".pyi"}
    ]


def _syntax_errors(results) -> list[str]:
    errors: list[str] = []
    for result in results:
        errors.extend(getattr(result, "syntax_errors", ()))
    return errors


def _limitations(results) -> list[str]:
    values: set[str] = set()
    for result in results:
        values.update(getattr(result, "limitations", ()))
    return sorted(values)


def _write_snapshot_index(
    layout: OutputLayout,
    *,
    outputs: dict[str, str],
    counts: dict[str, int],
    warnings: list[str],
    changed_only: bool,
) -> Path:
    payload: dict[str, Any] = {
        "schema": {
            "name": "cbl.snapshot_index",
            "version": 1,
        },
        "scope": "changed" if changed_only else "full",
        "outputs": outputs,
        "counts": counts,
        "warnings": warnings,
    }
    return write_json_report(layout.latest_dir / "snapshot_index.json", payload)


def write_snapshot_bundle(
    layout: OutputLayout,
    repo_root: str | Path,
    *,
    max_file_bytes: int,
    changed_only: bool = False,
    tree_depth: int = 5,
) -> SnapshotBundleResult:
    root = Path(repo_root).resolve()
    outputs: dict[str, str] = {}
    warnings: list[str] = []

    universe = discover_file_universe(root, max_file_bytes=max_file_bytes)
    warnings.extend(universe.warnings)

    inventory_path = write_file_inventory(layout, universe)
    tree_path = write_tree_report(layout, universe, max_depth=tree_depth, show_skipped=True)

    outputs["file_inventory_json"] = ".codecontext/latest/file_inventory.json"
    outputs["repo_tree_txt"] = ".codecontext/latest/repo_tree.txt"

    python_files = _python_files_from_universe(universe)

    changed_file_count = 0
    changed_symbol_count = 0

    if changed_only:
        diff_result = collect_changed_files(root, include_untracked=True)
        warnings.extend(diff_result.warnings)

        changed_payload = changed_files_payload(diff_result)
        write_json_report(layout.latest_dir / "changed_files.json", changed_payload)
        outputs["changed_files_json"] = ".codecontext/latest/changed_files.json"

        symbol_result = map_changed_symbols(root, diff_result.changed_files)
        changed_symbols_payload = changed_symbol_result_payload(symbol_result)
        write_json_report(layout.latest_dir / "changed_symbols.json", changed_symbols_payload)
        outputs["changed_symbols_json"] = ".codecontext/latest/changed_symbols.json"

        changed_file_count = diff_result.counts.get("changed_files_count", 0)
        changed_symbol_count = changed_symbols_payload["counts"]["total"]

        changed_python_paths = {
            record.path
            for record in diff_result.changed_files
            if Path(record.path).suffix.lower() in {".py", ".pyw", ".pyi"} and record.status != "D"
        }
        python_files = [path for path in python_files if path in changed_python_paths]

    symbol_results = collect_python_symbols(root, python_files)
    symbols = flatten_symbol_results(symbol_results)
    write_json_report(
        layout.latest_dir / "symbols.json",
        symbol_records_payload(symbols, syntax_errors=_syntax_errors(symbol_results)),
    )
    outputs["symbols_json"] = ".codecontext/latest/symbols.json"

    import_results = collect_python_imports(root, python_files)
    imports = flatten_import_results(import_results)
    write_json_report(
        layout.latest_dir / "imports.json",
        import_records_payload(imports, syntax_errors=_syntax_errors(import_results)),
    )
    outputs["imports_json"] = ".codecontext/latest/imports.json"

    cli_results = collect_cli_commands(root, python_files)
    commands = flatten_cli_results(cli_results)
    write_json_report(
        layout.latest_dir / "commands.json",
        command_records_payload(
            commands,
            syntax_errors=_syntax_errors(cli_results),
            limitations=_limitations(cli_results),
        ),
    )
    outputs["commands_json"] = ".codecontext/latest/commands.json"

    route_results = collect_routes(root, python_files)
    routes = flatten_route_results(route_results)
    write_json_report(
        layout.latest_dir / "routes.json",
        route_records_payload(
            routes,
            syntax_errors=_syntax_errors(route_results),
            limitations=_limitations(route_results),
        ),
    )
    outputs["routes_json"] = ".codecontext/latest/routes.json"

    test_inventory = collect_test_inventory(root, python_files, include_fixtures=True)
    write_json_report(
        layout.latest_dir / "tests_inventory.json",
        test_inventory_payload(test_inventory),
    )
    outputs["tests_inventory_json"] = ".codecontext/latest/tests_inventory.json"

    counts = {
        "included_files": universe.counts.get("included_count", 0),
        "python_files_analyzed": len(python_files),
        "symbols": len(symbols),
        "imports": len(imports),
        "commands": len(commands),
        "routes": len(routes),
        "test_files": len(test_inventory.tests),
        "test_functions": sum(len(record.test_functions) for record in test_inventory.tests),
        "fixtures": len(test_inventory.fixtures),
        "changed_files": changed_file_count,
        "changed_symbols": changed_symbol_count,
    }

    _write_snapshot_index(
        layout,
        outputs=outputs,
        counts=counts,
        warnings=warnings,
        changed_only=changed_only,
    )
    outputs["snapshot_index_json"] = ".codecontext/latest/snapshot_index.json"

    return SnapshotBundleResult(
        outputs=outputs,
        counts=counts,
        warnings=tuple(warnings),
        changed_only=changed_only,
    )
