from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/reports/snapshot.py": r'''
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


def _write_pack_index(
    layout: OutputLayout,
    *,
    issue: str | None,
    changed_only: bool,
    outputs: dict[str, str],
    counts: dict[str, int],
    warnings: tuple[str, ...],
) -> Path:
    payload = {
        "schema": {
            "name": "cbl.pack_index",
            "version": 1,
        },
        "issue": issue,
        "scope": "changed" if changed_only else "full",
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
) -> HandoffPackResult:
    root = Path(repo_root).resolve()

    snapshot = write_snapshot_bundle(
        layout,
        root,
        max_file_bytes=max_file_bytes,
        changed_only=changed_only,
        tree_depth=5,
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
    )
    outputs["pack_index_json"] = ".codecontext/latest/pack_index.json"

    return HandoffPackResult(
        outputs=outputs,
        counts=counts,
        warnings=tuple(warnings),
    )
''',

    "tests/test_snapshot_pack_integration.py": r'''
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


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "snapshot_pack_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'snapshot-pack-repo'\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".codecontext/\n", encoding="utf-8")

    (package / "app.py").write_text(
        "\n".join(
            [
                "import argparse",
                "",
                "def target(value):",
                "    return value + 1",
                "",
                "def build_parser():",
                "    parser = argparse.ArgumentParser()",
                "    sub = parser.add_subparsers(dest='command')",
                "    run = sub.add_parser('run')",
                "    run.set_defaults(handler=target)",
                "    return parser",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_app.py").write_text(
        "\n".join(
            [
                "from demo.app import target",
                "",
                "def test_target():",
                "    assert target(1) == 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_snapshot_and_pack_generate_coherent_handoff_outputs(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    snapshot = run_cbl("snapshot", "--repo", str(repo), "--no-archive")
    assert snapshot.returncode == 0, snapshot.stdout + snapshot.stderr
    assert "CBL snapshot: OK" in snapshot.stdout
    assert "C:\\Users\\" not in snapshot.stdout

    latest = repo / ".codecontext" / "latest"
    expected_snapshot = {
        "file_inventory.json",
        "repo_tree.txt",
        "symbols.json",
        "imports.json",
        "commands.json",
        "routes.json",
        "tests_inventory.json",
        "snapshot_index.json",
        "manifest.json",
    }
    assert expected_snapshot <= {item.name for item in latest.iterdir()}

    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))
    assert snapshot_index["counts"]["symbols"] >= 2
    assert snapshot_index["counts"]["commands"] >= 1
    assert snapshot_index["counts"]["test_functions"] >= 1

    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "snapshot"
    assert manifest["repo"]["root"] == "<redacted>"
    assert manifest["outputs"]["snapshot_index_json"] == ".codecontext/latest/snapshot_index.json"

    pack = run_cbl("pack", "--repo", str(repo), "--issue", "exercise handoff", "--no-archive")
    assert pack.returncode == 0, pack.stdout + pack.stderr
    assert "CBL pack: OK" in pack.stdout
    assert "C:\\Users\\" not in pack.stdout

    expected_pack = {
        "ai_handoff.md",
        "pack_index.json",
        "snapshot_index.json",
        "symbols.json",
        "imports.json",
        "commands.json",
        "tests_inventory.json",
        "manifest.json",
    }
    assert expected_pack <= {item.name for item in latest.iterdir()}

    handoff = (latest / "ai_handoff.md").read_text(encoding="utf-8")
    assert "# CBL AI Handoff Pack" in handoff
    assert "exercise handoff" in handoff
    assert "C:\\Users\\" not in handoff

    pack_index = json.loads((latest / "pack_index.json").read_text(encoding="utf-8"))
    assert pack_index["issue"] == "exercise handoff"
    assert pack_index["outputs"]["ai_handoff_md"] == ".codecontext/latest/ai_handoff.md"

    pack_manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    assert pack_manifest["command"]["subcommand"] == "pack"
    assert pack_manifest["outputs"]["pack_index_json"] == ".codecontext/latest/pack_index.json"
''',

    "scripts/dev/audits/audit_phase8_snapshot_pack.py": r'''
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/reports/snapshot.py": [
        "SnapshotBundleResult",
        "write_snapshot_bundle",
    ],
    "src/codebase_lens/reports/handoff.py": [
        "HandoffPackResult",
        "write_handoff_pack",
    ],
    "src/codebase_lens/cli.py": [
        "_run_snapshot",
        "_run_pack",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


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
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    snapshot = run_cbl("snapshot", "--no-archive")
    if snapshot.returncode != 0:
        fail(f"cbl snapshot failed:\nSTDOUT:\n{snapshot.stdout}\nSTDERR:\n{snapshot.stderr}")
    if "CBL snapshot: OK" not in snapshot.stdout:
        fail("cbl snapshot did not report success.")
    if "C:\\Users\\" in snapshot.stdout:
        fail("cbl snapshot leaked an absolute Windows user path.")

    latest = ROOT / ".codecontext" / "latest"
    snapshot_required = {
        "file_inventory.json",
        "repo_tree.txt",
        "symbols.json",
        "imports.json",
        "commands.json",
        "routes.json",
        "tests_inventory.json",
        "snapshot_index.json",
        "manifest.json",
    }
    existing = {item.name for item in latest.iterdir()}
    missing_snapshot = snapshot_required - existing
    if missing_snapshot:
        fail(f"snapshot missing outputs: {sorted(missing_snapshot)}")

    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))
    if snapshot_index["counts"]["included_files"] < 1:
        fail("snapshot_index included_files count is invalid.")
    if snapshot_index["counts"]["python_files_analyzed"] < 1:
        fail("snapshot_index python_files_analyzed count is invalid.")

    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    if manifest["command"]["subcommand"] != "snapshot":
        fail("manifest command.subcommand is not snapshot.")
    if manifest["repo"]["root"] != "<redacted>":
        fail("manifest repo.root is not redacted.")
    if manifest["outputs"].get("snapshot_index_json") != ".codecontext/latest/snapshot_index.json":
        fail("manifest does not declare snapshot_index_json.")

    pack = run_cbl("pack", "--changed", "--issue", "phase 8 audit handoff", "--no-archive")
    if pack.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")
    if "CBL pack: OK" not in pack.stdout:
        fail("cbl pack did not report success.")
    if "C:\\Users\\" in pack.stdout:
        fail("cbl pack leaked an absolute Windows user path.")

    pack_required = {
        "ai_handoff.md",
        "pack_index.json",
        "snapshot_index.json",
        "manifest.json",
    }
    existing = {item.name for item in latest.iterdir()}
    missing_pack = pack_required - existing
    if missing_pack:
        fail(f"pack missing outputs: {sorted(missing_pack)}")

    handoff = (latest / "ai_handoff.md").read_text(encoding="utf-8")
    if "# CBL AI Handoff Pack" not in handoff:
        fail("ai_handoff.md missing title.")
    if "phase 8 audit handoff" not in handoff:
        fail("ai_handoff.md missing issue context.")
    if "C:\\Users\\" in handoff:
        fail("ai_handoff.md leaked an absolute Windows user path.")

    pack_index = json.loads((latest / "pack_index.json").read_text(encoding="utf-8"))
    if pack_index["outputs"].get("ai_handoff_md") != ".codecontext/latest/ai_handoff.md":
        fail("pack_index does not declare ai_handoff_md.")
    if pack_index["scope"] != "changed":
        fail("pack_index scope should be changed for --changed pack.")

    pack_manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    if pack_manifest["command"]["subcommand"] != "pack":
        fail("manifest command.subcommand is not pack.")
    if pack_manifest["outputs"].get("pack_index_json") != ".codecontext/latest/pack_index.json":
        fail("manifest does not declare pack_index_json.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed after snapshot/pack slice:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 8 snapshot/pack audit passed.")
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

    replacements = [
        (
            "from codebase_lens.reports.manifest import build_manifest, copy_latest_to_run, prepare_output_layout, write_manifest_bundle\n",
            "from codebase_lens.reports.handoff import write_handoff_pack\n"
            "from codebase_lens.reports.manifest import build_manifest, copy_latest_to_run, prepare_output_layout, write_manifest_bundle\n"
            "from codebase_lens.reports.snapshot import write_snapshot_bundle\n",
        ),
        (
            "    snapshot.set_defaults(handler=_run_partial)\n",
            "    snapshot.set_defaults(handler=_run_snapshot)\n",
        ),
        (
            "    pack.set_defaults(handler=_run_partial)\n",
            "    pack.set_defaults(handler=_run_pack)\n",
        ),
    ]

    for old, new in replacements:
        if old not in text:
            if new in text:
                continue
            raise RuntimeError(f"Could not patch cli.py; missing expected marker:\n{old}")
        text = text.replace(old, new, 1)

    insert_before = "\ndef _run_contract(args: argparse.Namespace) -> int:\n"
    if insert_before not in text:
        raise RuntimeError("Could not patch cli.py: _run_contract insertion marker not found.")

    if "def _run_snapshot(args: argparse.Namespace)" not in text:
        inserted = r'''

def _run_snapshot(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        result = write_snapshot_bundle(
            layout,
            repo_root,
            max_file_bytes=args.max_file_bytes,
            changed_only=args.changed,
        )

        outputs = {
            "manifest_json": ".codecontext/latest/manifest.json",
            **result.outputs,
        }

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "snapshot",
                outputs,
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not write snapshot bundle: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL snapshot: OK")
        print(f"Scope: {'changed' if args.changed else 'full'}")
        print(f"Included files: {result.counts.get('included_files', 0)}")
        print(f"Python files analyzed: {result.counts.get('python_files_analyzed', 0)}")
        print(f"Symbols: {result.counts.get('symbols', 0)}")
        print(f"Imports: {result.counts.get('imports', 0)}")
        print(f"Commands: {result.counts.get('commands', 0)}")
        print(f"Routes: {result.counts.get('routes', 0)}")
        print(f"Test functions: {result.counts.get('test_functions', 0)}")
        print("Snapshot index: .codecontext/latest/snapshot_index.json")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for warning in result.warnings:
            print(f"WARNING: {redact_console_text(warning)}")

    return 0


def _run_pack(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        result = write_handoff_pack(
            layout,
            repo_root,
            max_file_bytes=args.max_file_bytes,
            changed_only=args.changed,
            issue=args.issue,
            spec_path=args.spec,
        )

        outputs = {
            "manifest_json": ".codecontext/latest/manifest.json",
            **result.outputs,
        }

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "pack",
                outputs,
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
        print(redact_console_text(f"ERROR: Could not write handoff pack: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL pack: OK")
        print(f"Scope: {'changed' if args.changed else 'full'}")
        print(f"Issue/context: {args.issue if args.issue else '(none provided)'}")
        print(f"Included files: {result.counts.get('included_files', 0)}")
        print(f"Python files analyzed: {result.counts.get('python_files_analyzed', 0)}")
        print(f"Changed files: {result.counts.get('changed_files', 0)}")
        print(f"Changed symbols: {result.counts.get('changed_symbols', 0)}")
        print("AI handoff: .codecontext/latest/ai_handoff.md")
        print("Pack index: .codecontext/latest/pack_index.json")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for warning in result.warnings:
            print(f"WARNING: {redact_console_text(warning)}")

    return 0

'''
        text = text.replace(insert_before, inserted + insert_before, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_contract() -> None:
    path = ROOT / "src/codebase_lens/contracts/architecture.py"
    text = path.read_text(encoding="utf-8")

    required_file_marker = '            "src/codebase_lens/reports/scanner_outputs.py",\n'
    required_file_addition = (
        '            "src/codebase_lens/reports/snapshot.py",\n'
        '            "src/codebase_lens/reports/handoff.py",\n'
    )

    if required_file_addition not in text:
        if required_file_marker not in text:
            raise RuntimeError("Could not patch architecture.py: scanner_outputs required-file marker not found.")
        text = text.replace(required_file_marker, required_file_marker + required_file_addition, 1)

    symbol_marker = '                    "_run_doctor",\n'
    symbol_addition = (
        '                    "_run_snapshot",\n'
        '                    "_run_pack",\n'
    )

    if symbol_addition not in text:
        if symbol_marker not in text:
            raise RuntimeError("Could not patch architecture.py: _run_doctor symbol marker not found.")
        text = text.replace(symbol_marker, symbol_marker + symbol_addition, 1)

    extra_required = '''            {
                "path": "src/codebase_lens/reports/snapshot.py",
                "symbols": [
                    "SnapshotBundleResult",
                    "write_snapshot_bundle",
                ],
            },
            {
                "path": "src/codebase_lens/reports/handoff.py",
                "symbols": [
                    "HandoffPackResult",
                    "write_handoff_pack",
                ],
            },
'''

    insertion_marker = '''            {
                "path": "src/codebase_lens/contracts/architecture.py",
'''
    if extra_required not in text:
        if insertion_marker not in text:
            raise RuntimeError("Could not patch architecture.py: contracts required-symbol marker not found.")
        text = text.replace(insertion_marker, extra_required + insertion_marker, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_cli()
    patch_contract()

    print("Slice 009 applied: Phase 8 snapshot and AI handoff pack implemented.")
    print("Run the Phase 8 audit, contract, pytest, and git diff --check before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())