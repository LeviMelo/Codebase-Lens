from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/reports/snapshot.py": r'''
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
''',

    "src/codebase_lens/reports/handoff.py": r'''
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codebase_lens.contracts.architecture import evaluate_contract, load_contract_spec
from codebase_lens.reports.json import contract_result_payload, write_json_report
from codebase_lens.reports.manifest import OutputLayout
from codebase_lens.reports.snapshot import SnapshotBundleResult, write_snapshot_bundle


@dataclass(frozen=True)
class HandoffPackResult:
    outputs: dict[str, str]
    counts: dict[str, int]
    warnings: tuple[str, ...]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_tree_excerpt(path: Path, *, max_lines: int = 160) -> list[str]:
    if not path.is_file():
        return ["(repo_tree.txt was not generated)"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= max_lines:
        return lines
    return [*lines[:max_lines], f"... ({len(lines) - max_lines} additional tree lines omitted)"]


def _format_output_list(outputs: dict[str, str]) -> list[str]:
    return [f"- `{key}` → `{value}`" for key, value in sorted(outputs.items())]


def _format_changed_files(layout: OutputLayout, *, max_items: int = 60) -> list[str]:
    payload = _read_json(layout.latest_dir / "changed_files.json")
    records = payload.get("changed_files", [])
    if not isinstance(records, list) or not records:
        return ["- No changed files were captured in this pack."]

    lines: list[str] = []
    for record in records[:max_items]:
        if not isinstance(record, dict):
            continue
        path = record.get("path", "<unknown>")
        origin = record.get("origin", "<unknown>")
        status = record.get("status", "?")
        additions = record.get("additions")
        deletions = record.get("deletions")
        lines.append(f"- `{path}` [{status}, {origin}, +{additions}/-{deletions}]")

    if len(records) > max_items:
        lines.append(f"- ... {len(records) - max_items} additional changed files omitted.")

    return lines


def _format_changed_symbols(layout: OutputLayout, *, max_items: int = 80) -> list[str]:
    payload = _read_json(layout.latest_dir / "changed_symbols.json")
    records = payload.get("changed_symbols", [])
    if not isinstance(records, list) or not records:
        return ["- No changed Python symbols were captured in this pack."]

    lines: list[str] = []
    for record in records[:max_items]:
        if not isinstance(record, dict):
            continue
        path = record.get("path", "<unknown>")
        name = record.get("qualified_name", "<unknown>")
        start = record.get("start_line", "?")
        end = record.get("end_line", "?")
        lines.append(f"- `{name}` → `{path}:L{start}-L{end}`")

    if len(records) > max_items:
        lines.append(f"- ... {len(records) - max_items} additional changed symbols omitted.")

    return lines


def _format_omissions(layout: OutputLayout, *, max_items: int = 60) -> list[str]:
    payload = _read_json(layout.latest_dir / "omissions.json")
    records = payload.get("omissions", [])
    if not isinstance(records, list) or not records:
        return ["- No omitted files were reported by the scanner."]

    lines: list[str] = []
    for record in records[:max_items]:
        if not isinstance(record, dict):
            continue
        path = record.get("path", "<unknown>")
        reason = record.get("reason", "<unknown>")
        evidence = record.get("evidence")
        suffix = f" — {evidence}" if evidence else ""
        lines.append(f"- `{path}` → {reason}{suffix}")

    if len(records) > max_items:
        lines.append(f"- ... {len(records) - max_items} additional omissions omitted from markdown; see `omissions.json`.")

    return lines


def _format_budget(layout: OutputLayout) -> list[str]:
    payload = _read_json(layout.latest_dir / "budget_report.json")
    if not payload:
        return ["- `budget_report.json` was not generated."]

    return [
        f"- Requested budget tokens: {payload.get('requested_budget_tokens')}",
        f"- Budget pressure: {payload.get('budget_pressure')}",
        f"- Focus terms: {payload.get('focus_terms', [])}",
        f"- Estimation method: {payload.get('estimation_method')}",
    ]


def _write_pack_index(
    layout: OutputLayout,
    *,
    issue: str | None,
    changed_only: bool,
    outputs: dict[str, str],
    counts: dict[str, int],
    warnings: tuple[str, ...],
    budget: int,
    focus_terms: tuple[str, ...],
) -> Path:
    payload = {
        "schema": {
            "name": "cbl.pack_index",
            "version": 1,
        },
        "issue": issue,
        "scope": "changed" if changed_only else "full",
        "budget": budget,
        "focus_terms": list(focus_terms),
        "outputs": outputs,
        "counts": counts,
        "warnings": list(warnings),
    }
    return write_json_report(layout.latest_dir / "pack_index.json", payload)


def write_handoff_pack(
    layout: OutputLayout,
    repo_root: str | Path,
    *,
    max_file_bytes: int,
    changed_only: bool = False,
    issue: str | None = None,
    spec_path: str | Path | None = None,
    budget: int = 16000,
    focus_terms: tuple[str, ...] = (),
) -> HandoffPackResult:
    root = Path(repo_root).resolve()

    snapshot = write_snapshot_bundle(
        layout,
        root,
        max_file_bytes=max_file_bytes,
        changed_only=changed_only,
        tree_depth=5,
        budget=budget,
        focus_terms=focus_terms,
    )

    outputs = dict(snapshot.outputs)
    warnings = list(snapshot.warnings)
    counts = dict(snapshot.counts)

    if spec_path is not None:
        spec = load_contract_spec(root, spec_path)
        contract_result = evaluate_contract(root, spec)
        write_json_report(layout.latest_dir / "contract_report.json", contract_result_payload(contract_result))
        outputs["contract_report_json"] = ".codecontext/latest/contract_report.json"
        counts["contract_errors"] = contract_result.counts.get("errors", 0)
        counts["contract_violations"] = contract_result.counts.get("violations", 0)

    tree_excerpt = _read_tree_excerpt(layout.latest_dir / "repo_tree.txt")
    output_lines = _format_output_list(outputs)
    changed_files = _format_changed_files(layout)
    changed_symbols = _format_changed_symbols(layout)
    omissions = _format_omissions(layout)
    budget_lines = _format_budget(layout)

    markdown_lines = [
        "# CBL AI Handoff Pack",
        "",
        f"Repository: `{root.name}`",
        f"Scope: `{'changed' if changed_only else 'full'}`",
        f"Issue/context: {issue if issue else '(none provided)'}",
        "",
        "## Counts",
        "",
        f"- Included files: {counts.get('included_files', 0)}",
        f"- Python files analyzed: {counts.get('python_files_analyzed', 0)}",
        f"- Symbols: {counts.get('symbols', 0)}",
        f"- Imports: {counts.get('imports', 0)}",
        f"- CLI commands: {counts.get('commands', 0)}",
        f"- Routes: {counts.get('routes', 0)}",
        f"- Test files: {counts.get('test_files', 0)}",
        f"- Test functions: {counts.get('test_functions', 0)}",
        f"- Fixtures: {counts.get('fixtures', 0)}",
        f"- Changed files: {counts.get('changed_files', 0)}",
        f"- Changed symbols: {counts.get('changed_symbols', 0)}",
        f"- Omissions: {counts.get('omissions', 0)}",
        "",
        "## Budget and Focus",
        "",
        *budget_lines,
        "",
        "## Generated Outputs",
        "",
        *output_lines,
        "",
        "## Changed Files",
        "",
        *changed_files,
        "",
        "## Changed Python Symbols",
        "",
        *changed_symbols,
        "",
        "## Omissions",
        "",
        *omissions,
        "",
        "## Repository Tree Excerpt",
        "",
        "```text",
        *tree_excerpt,
        "```",
        "",
        "## Safety Notes",
        "",
        "- Paths in this pack are repository-relative unless explicitly stated otherwise.",
        "- `.codecontext/`, private environment files, common build outputs, caches, and binary artifacts are excluded by scanner policy.",
        "- Secret-like assignments are redacted before AI-facing report generation.",
    ]

    if warnings:
        markdown_lines.extend(["", "## Warnings", ""])
        markdown_lines.extend(f"- {warning}" for warning in warnings)

    handoff_path = layout.latest_dir / "ai_handoff.md"
    handoff_path.write_text("\n".join(markdown_lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    outputs["ai_handoff_md"] = ".codecontext/latest/ai_handoff.md"

    _write_pack_index(
        layout,
        issue=issue,
        changed_only=changed_only,
        outputs=outputs,
        counts=counts,
        warnings=tuple(warnings),
        budget=budget,
        focus_terms=focus_terms,
    )
    outputs["pack_index_json"] = ".codecontext/latest/pack_index.json"

    return HandoffPackResult(
        outputs=outputs,
        counts=counts,
        warnings=tuple(warnings),
    )
''',

    "scripts/dev/audits/audit_v01_readiness.py": r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

COMMANDS = [
    "doctor",
    "tree",
    "file",
    "symbols",
    "symbol",
    "imports",
    "cli",
    "routes",
    "tests",
    "diff",
    "changed",
    "callers",
    "contract",
    "snapshot",
    "pack",
    "clean",
]

SNAPSHOT_REQUIRED = {
    "file_inventory.json",
    "repo_tree.txt",
    "symbols.json",
    "symbol_index.json",
    "imports.json",
    "import_graph.json",
    "commands.json",
    "cli_inventory.json",
    "routes.json",
    "route_inventory.json",
    "tests_inventory.json",
    "test_inventory.json",
    "omissions.json",
    "budget_report.json",
    "snapshot_index.json",
    "manifest.json",
}

PACK_REQUIRED = {
    "ai_handoff.md",
    "pack_index.json",
    "snapshot_index.json",
    "omissions.json",
    "budget_report.json",
    "manifest.json",
}


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


def assert_no_windows_path(text: str, context: str) -> None:
    if "C:\\Users\\" in text:
        fail(f"{context} leaked an absolute Windows user path.")


def main() -> int:
    help_result = run_cbl("--help")
    if help_result.returncode != 0:
        fail("cbl --help failed.")

    for command in COMMANDS:
        if command not in help_result.stdout:
            fail(f"cbl --help does not mention command: {command}")

    snapshot = run_cbl("snapshot", "--budget", "24000", "--focus", "contract", "--focus", "pack", "--no-archive")
    if snapshot.returncode != 0:
        fail(f"cbl snapshot failed:\nSTDOUT:\n{snapshot.stdout}\nSTDERR:\n{snapshot.stderr}")
    if "CBL snapshot: OK" not in snapshot.stdout:
        fail("snapshot did not report success.")
    assert_no_windows_path(snapshot.stdout, "snapshot stdout")

    latest = ROOT / ".codecontext" / "latest"
    existing = {item.name for item in latest.iterdir()}
    missing_snapshot = SNAPSHOT_REQUIRED - existing
    if missing_snapshot:
        fail(f"snapshot missing required outputs: {sorted(missing_snapshot)}")

    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))
    if snapshot_index.get("budget") != 24000:
        fail("snapshot_index did not preserve requested budget.")
    if snapshot_index.get("focus_terms") != ["contract", "pack"]:
        fail("snapshot_index did not preserve focus terms.")

    budget = json.loads((latest / "budget_report.json").read_text(encoding="utf-8"))
    if budget.get("requested_budget_tokens") != 24000:
        fail("budget_report did not preserve requested budget.")
    if budget.get("focus_terms") != ["contract", "pack"]:
        fail("budget_report did not preserve focus terms.")
    if "ranked_files" not in budget:
        fail("budget_report missing ranked_files.")

    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    if manifest["repo"]["root"] != "<redacted>":
        fail("snapshot manifest repo.root is not redacted.")
    if manifest["command"]["subcommand"] != "snapshot":
        fail("snapshot manifest subcommand is wrong.")
    if manifest["outputs"].get("symbol_index_json") != ".codecontext/latest/symbol_index.json":
        fail("snapshot manifest missing symbol_index_json alias.")
    if manifest["outputs"].get("omissions_json") != ".codecontext/latest/omissions.json":
        fail("snapshot manifest missing omissions_json.")

    pack = run_cbl(
        "pack",
        "--changed",
        "--budget",
        "12000",
        "--focus",
        "diff",
        "--issue",
        "v0.1 readiness audit",
        "--no-archive",
    )
    if pack.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")
    if "CBL pack: OK" not in pack.stdout:
        fail("pack did not report success.")
    assert_no_windows_path(pack.stdout, "pack stdout")

    existing = {item.name for item in latest.iterdir()}
    missing_pack = PACK_REQUIRED - existing
    if missing_pack:
        fail(f"pack missing required outputs: {sorted(missing_pack)}")

    handoff = (latest / "ai_handoff.md").read_text(encoding="utf-8")
    assert_no_windows_path(handoff, "ai_handoff.md")
    for marker in ["# CBL AI Handoff Pack", "## Budget and Focus", "## Omissions", "v0.1 readiness audit"]:
        if marker not in handoff:
            fail(f"ai_handoff.md missing marker: {marker}")

    pack_index = json.loads((latest / "pack_index.json").read_text(encoding="utf-8"))
    if pack_index.get("scope") != "changed":
        fail("pack_index scope is not changed.")
    if pack_index.get("budget") != 12000:
        fail("pack_index did not preserve requested budget.")
    if pack_index.get("focus_terms") != ["diff"]:
        fail("pack_index did not preserve focus terms.")
    if pack_index["outputs"].get("ai_handoff_md") != ".codecontext/latest/ai_handoff.md":
        fail("pack_index missing ai_handoff_md output.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    clean = run_cbl("clean", "--keep", "999")
    if clean.returncode != 0:
        fail(f"cbl clean failed:\nSTDOUT:\n{clean.stdout}\nSTDERR:\n{clean.stderr}")
    if "CBL clean: OK" not in clean.stdout:
        fail("clean did not report success.")
    assert_no_windows_path(clean.stdout, "clean stdout")

    print("PASS: v0.1 readiness audit passed.")
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


def patch_cli() -> None:
    path = ROOT / "src/codebase_lens/cli.py"
    text = path.read_text(encoding="utf-8")

    old_snapshot = '''        result = write_snapshot_bundle(
            layout,
            repo_root,
            max_file_bytes=args.max_file_bytes,
            changed_only=args.changed,
        )
'''
    new_snapshot = '''        result = write_snapshot_bundle(
            layout,
            repo_root,
            max_file_bytes=args.max_file_bytes,
            changed_only=args.changed,
            budget=args.budget,
            focus_terms=tuple(args.focus),
        )
'''

    old_pack = '''        result = write_handoff_pack(
            layout,
            repo_root,
            max_file_bytes=args.max_file_bytes,
            changed_only=args.changed,
            issue=args.issue,
            spec_path=args.spec,
        )
'''
    new_pack = '''        result = write_handoff_pack(
            layout,
            repo_root,
            max_file_bytes=args.max_file_bytes,
            changed_only=args.changed,
            issue=args.issue,
            spec_path=args.spec,
            budget=args.budget,
            focus_terms=tuple(args.focus),
        )
'''

    for old, new in [(old_snapshot, new_snapshot), (old_pack, new_pack)]:
        if old not in text:
            if new in text:
                continue
            raise RuntimeError(f"Could not patch cli.py; missing expected call block:\n{old}")
        text = text.replace(old, new, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_contract() -> None:
    path = ROOT / "src/codebase_lens/contracts/architecture.py"
    text = path.read_text(encoding="utf-8")

    # Required symbols already target snapshot/handoff. This patch only ensures
    # the final readiness audit script is structurally visible to the built-in
    # contract through required_files.
    marker = '            "src/codebase_lens/reports/handoff.py",\n'
    addition = '            "scripts/dev/audits/audit_v01_readiness.py",\n'

    if addition not in text:
        if marker not in text:
            raise RuntimeError("Could not patch architecture.py: handoff required-file marker not found.")
        text = text.replace(marker, marker + addition, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_phase8_audit() -> None:
    path = ROOT / "scripts/dev/audits/audit_phase8_snapshot_pack.py"
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8")

    old_snapshot_required = '''        "snapshot_index.json",
        "manifest.json",
'''
    new_snapshot_required = '''        "snapshot_index.json",
        "symbol_index.json",
        "import_graph.json",
        "cli_inventory.json",
        "route_inventory.json",
        "test_inventory.json",
        "omissions.json",
        "budget_report.json",
        "manifest.json",
'''

    if old_snapshot_required in text and new_snapshot_required not in text:
        text = text.replace(old_snapshot_required, new_snapshot_required, 1)

    old_pack_required = '''        "pack_index.json",
        "snapshot_index.json",
        "manifest.json",
'''
    new_pack_required = '''        "pack_index.json",
        "snapshot_index.json",
        "omissions.json",
        "budget_report.json",
        "manifest.json",
'''

    if old_pack_required in text and new_pack_required not in text:
        text = text.replace(old_pack_required, new_pack_required, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_cli()
    patch_contract()
    patch_phase8_audit()

    print("Slice 011 applied: v0.1 compliance hardening implemented.")
    print("Run v0.1 readiness audit, Phase 8 audit, contract, pytest, and git diff --check before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())