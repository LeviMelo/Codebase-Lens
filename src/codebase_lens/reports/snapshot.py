from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
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
from codebase_lens.analyzers.symbol_graph import collect_symbol_graph
from codebase_lens.analyzers.evidence_graph import build_evidence_graph
from codebase_lens.reports.graph import write_evidence_graph_reports
from codebase_lens.reports.symbol_graph import write_symbol_graph_reports
from codebase_lens.reports.scanner_outputs import write_file_inventory, write_tree_report
from codebase_lens.scanners.universe import discover_file_universe


@dataclass(frozen=True)
class SnapshotBundleResult:
    outputs: dict[str, str]
    counts: dict[str, int]
    warnings: tuple[str, ...]
    changed_only: bool


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


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


def _write_payload_with_aliases(
    layout: OutputLayout,
    payload: dict[str, Any],
    *,
    canonical_name: str,
    alias_names: tuple[str, ...] = (),
) -> dict[str, str]:
    outputs: dict[str, str] = {}

    write_json_report(layout.latest_dir / canonical_name, payload)
    key = canonical_name.replace(".", "_")
    outputs[key] = f".codecontext/latest/{canonical_name}"

    for alias_name in alias_names:
        write_json_report(layout.latest_dir / alias_name, payload)
        alias_key = alias_name.replace(".", "_")
        outputs[alias_key] = f".codecontext/latest/{alias_name}"

    return outputs


def _focus_hits_for_path(path: str, focus_terms: tuple[str, ...]) -> int:
    if not focus_terms:
        return 0
    lowered = path.lower()
    return sum(1 for term in focus_terms if term.lower() in lowered)


def _write_omissions_report(layout: OutputLayout, universe, *, changed_only: bool) -> Path:
    payload = {
        "schema": {
            "name": "cbl.omissions",
            "version": 1,
        },
        "scope": "changed" if changed_only else "full",
        "omissions": [_jsonable(record) for record in getattr(universe, "omissions", ())],
        "warnings": list(getattr(universe, "warnings", ())),
        "counts": {
            "omissions": len(getattr(universe, "omissions", ())),
            "warnings": len(getattr(universe, "warnings", ())),
            "hard_excluded_count": getattr(universe, "counts", {}).get("hard_excluded_count", 0),
            "large_skipped_count": getattr(universe, "counts", {}).get("large_skipped_count", 0),
            "binary_skipped_count": getattr(universe, "counts", {}).get("binary_skipped_count", 0),
            "unsupported_extension_count": getattr(universe, "counts", {}).get("unsupported_extension_count", 0),
            "decode_failed_count": getattr(universe, "counts", {}).get("decode_failed_count", 0),
        },
    }
    return write_json_report(layout.latest_dir / "omissions.json", payload)


def _write_budget_report(
    layout: OutputLayout,
    universe,
    *,
    budget: int,
    focus_terms: tuple[str, ...],
    changed_only: bool,
    python_files: list[str],
) -> Path:
    included_files = list(getattr(universe, "included_files", ()))

    ranked_files = []
    for record in included_files:
        path = getattr(record, "path", "")
        size_bytes = int(getattr(record, "size_bytes", 0) or 0)
        estimated_tokens = max(1, size_bytes // 4) if size_bytes else 1
        focus_hits = _focus_hits_for_path(path, focus_terms)
        ranked_files.append(
            {
                "path": path,
                "size_bytes": size_bytes,
                "estimated_tokens": estimated_tokens,
                "focus_hits": focus_hits,
                "priority_score": focus_hits * 1000 + max(0, 100000 - size_bytes),
            }
        )

    ranked_files.sort(key=lambda item: (-int(item["priority_score"]), str(item["path"])))

    total_estimated_tokens = sum(int(item["estimated_tokens"]) for item in ranked_files)
    payload = {
        "schema": {
            "name": "cbl.budget_report",
            "version": 1,
        },
        "scope": "changed" if changed_only else "full",
        "requested_budget_tokens": budget,
        "focus_terms": list(focus_terms),
        "estimation_method": "heuristic: max(1, file_size_bytes // 4)",
        "total_estimated_file_tokens": total_estimated_tokens,
        "budget_pressure": "over_budget" if total_estimated_tokens > budget else "within_budget",
        "python_files_analyzed": python_files,
        "ranked_files": ranked_files[:250],
        "counts": {
            "ranked_files": len(ranked_files),
            "python_files_analyzed": len(python_files),
            "focus_terms": len(focus_terms),
        },
    }
    return write_json_report(layout.latest_dir / "budget_report.json", payload)


def _write_snapshot_index(
    layout: OutputLayout,
    *,
    outputs: dict[str, str],
    counts: dict[str, int],
    warnings: list[str],
    changed_only: bool,
    budget: int,
    focus_terms: tuple[str, ...],
) -> Path:
    payload: dict[str, Any] = {
        "schema": {
            "name": "cbl.snapshot_index",
            "version": 1,
        },
        "scope": "changed" if changed_only else "full",
        "budget": budget,
        "focus_terms": list(focus_terms),
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
    budget: int = 16000,
    focus_terms: tuple[str, ...] = (),
) -> SnapshotBundleResult:
    root = Path(repo_root).resolve()
    outputs: dict[str, str] = {}
    warnings: list[str] = []

    universe = discover_file_universe(root, max_file_bytes=max_file_bytes)
    warnings.extend(universe.warnings)

    write_file_inventory(layout, universe)
    write_tree_report(layout, universe, max_depth=tree_depth, show_skipped=True)

    outputs["file_inventory_json"] = ".codecontext/latest/file_inventory.json"
    outputs["repo_tree_txt"] = ".codecontext/latest/repo_tree.txt"

    omissions_path = _write_omissions_report(layout, universe, changed_only=changed_only)
    outputs["omissions_json"] = ".codecontext/latest/omissions.json"

    all_python_files = _python_files_from_universe(universe)
    python_files = list(all_python_files)

    changed_file_count = 0
    changed_symbol_count = 0
    changed_files_for_graph = ()
    changed_symbols_for_graph = ()

    if changed_only:
        diff_result = collect_changed_files(root, include_untracked=True)
        warnings.extend(diff_result.warnings)

        changed_files_for_graph = diff_result.changed_files

        changed_payload = changed_files_payload(diff_result)
        write_json_report(layout.latest_dir / "changed_files.json", changed_payload)
        outputs["changed_files_json"] = ".codecontext/latest/changed_files.json"

        symbol_result = map_changed_symbols(root, diff_result.changed_files)
        changed_symbols_for_graph = symbol_result.changed_symbols
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

    budget_path = _write_budget_report(
        layout,
        universe,
        budget=budget,
        focus_terms=focus_terms,
        changed_only=changed_only,
        python_files=python_files,
    )
    outputs["budget_report_json"] = ".codecontext/latest/budget_report.json"

    symbol_results = collect_python_symbols(root, python_files)
    symbols = flatten_symbol_results(symbol_results)
    symbols_payload = symbol_records_payload(symbols, syntax_errors=_syntax_errors(symbol_results))
    outputs.update(
        _write_payload_with_aliases(
            layout,
            symbols_payload,
            canonical_name="symbols.json",
            alias_names=("symbol_index.json",),
        )
    )

    import_results = collect_python_imports(root, python_files)
    imports = flatten_import_results(import_results)
    imports_payload = import_records_payload(imports, syntax_errors=_syntax_errors(import_results))
    outputs.update(
        _write_payload_with_aliases(
            layout,
            imports_payload,
            canonical_name="imports.json",
            alias_names=("import_graph.json",),
        )
    )

    cli_results = collect_cli_commands(root, python_files)
    commands = flatten_cli_results(cli_results)
    commands_payload = command_records_payload(
        commands,
        syntax_errors=_syntax_errors(cli_results),
        limitations=_limitations(cli_results),
    )
    outputs.update(
        _write_payload_with_aliases(
            layout,
            commands_payload,
            canonical_name="commands.json",
            alias_names=("cli_inventory.json",),
        )
    )

    route_results = collect_routes(root, python_files)
    routes = flatten_route_results(route_results)
    routes_payload = route_records_payload(
        routes,
        syntax_errors=_syntax_errors(route_results),
        limitations=_limitations(route_results),
    )
    outputs.update(
        _write_payload_with_aliases(
            layout,
            routes_payload,
            canonical_name="routes.json",
            alias_names=("route_inventory.json",),
        )
    )

    test_inventory = collect_test_inventory(root, python_files, include_fixtures=True)
    tests_payload = test_inventory_payload(test_inventory)
    outputs.update(
        _write_payload_with_aliases(
            layout,
            tests_payload,
            canonical_name="tests_inventory.json",
            alias_names=("test_inventory.json",),
        )
    )

    graph_result = collect_symbol_graph(
        root,
        all_python_files,
        focus_paths=set(python_files) if changed_only else set(),
        focus_terms=focus_terms,
    )
    warnings.extend(graph_result.warnings)
    outputs.update(write_symbol_graph_reports(layout, graph_result))

    evidence_graph = build_evidence_graph(
        root,
        universe=universe,
        symbol_graph=graph_result,
        import_records=imports,
        command_records=commands,
        route_records=routes,
        test_inventory=test_inventory,
        changed_files=changed_files_for_graph,
        changed_symbols=changed_symbols_for_graph,
    )
    warnings.extend(evidence_graph.warnings)
    outputs.update(write_evidence_graph_reports(layout, evidence_graph))

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
        "omissions": len(getattr(universe, "omissions", ())),
        "symbol_graph_nodes": graph_result.counts.get("nodes", 0),
        "symbol_graph_call_edges": graph_result.counts.get("call_edges", 0),
        "symbol_graph_caller_edges": graph_result.counts.get("caller_edges", 0),
        "evidence_graph_nodes": evidence_graph.counts.get("nodes", 0),
        "evidence_graph_edges": evidence_graph.counts.get("edges", 0),
        "evidence_graph_unresolved_edges": evidence_graph.counts.get("unresolved_edges", 0),
    }

    _write_snapshot_index(
        layout,
        outputs=outputs,
        counts=counts,
        warnings=warnings,
        changed_only=changed_only,
        budget=budget,
        focus_terms=focus_terms,
    )
    outputs["snapshot_index_json"] = ".codecontext/latest/snapshot_index.json"

    return SnapshotBundleResult(
        outputs=outputs,
        counts=counts,
        warnings=tuple(warnings),
        changed_only=changed_only,
    )
