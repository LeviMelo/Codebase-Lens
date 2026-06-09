from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from codebase_lens.core.paths import is_hard_excluded_relative, resolve_user_path, to_posix_relative
from codebase_lens.core.textio import read_text_with_policy
from codebase_lens.scanners.universe import discover_file_universe


@dataclass(frozen=True)
class ContractViolation:
    rule_id: str
    severity: str
    message: str
    path: str | None
    line: int | None
    evidence: str | None


@dataclass(frozen=True)
class ContractResult:
    contract_id: str
    name: str
    violations: tuple[ContractViolation, ...]
    warnings: tuple[str, ...]
    counts: dict[str, int]


def builtin_cbl_contract() -> dict[str, Any]:
    return {
        "id": "cbl-monolithic-scaffold-v1",
        "name": "CBL Monolithic Scaffolding Contract",
        "required_files": [
            "pyproject.toml",
            "src/codebase_lens/__init__.py",
            "src/codebase_lens/__main__.py",
            "src/codebase_lens/cli.py",
            "src/codebase_lens/core/constants.py",
            "src/codebase_lens/core/errors.py",
            "src/codebase_lens/core/paths.py",
            "src/codebase_lens/core/redaction.py",
            "src/codebase_lens/core/textio.py",
            "src/codebase_lens/git/discover.py",
            "src/codebase_lens/git/status.py",
            "src/codebase_lens/git/diff.py",
            "src/codebase_lens/scanners/universe.py",
            "src/codebase_lens/scanners/inventory.py",
            "src/codebase_lens/scanners/tree.py",
            "src/codebase_lens/analyzers/python_ast.py",
            "src/codebase_lens/analyzers/imports.py",
            "src/codebase_lens/analyzers/excerpts.py",
            "src/codebase_lens/analyzers/cli_static.py",
            "src/codebase_lens/analyzers/routes_static.py",
            "src/codebase_lens/analyzers/changed_symbols.py",
            "src/codebase_lens/analyzers/tests.py",
            "src/codebase_lens/analyzers/symbol_graph.py",
            "src/codebase_lens/reports/symbol_graph.py",
            "scripts/dev/audits/audit_phase10_symbol_graph.py",
            "src/codebase_lens/analyzers/callers.py",
            "src/codebase_lens/reports/manifest.py",
            "src/codebase_lens/reports/json.py",
            "src/codebase_lens/reports/scanner_outputs.py",
            "src/codebase_lens/reports/cleanup.py",
            "src/codebase_lens/reports/snapshot.py",
            "src/codebase_lens/reports/handoff.py",
            "scripts/dev/audits/audit_v01_readiness.py",
            "src/codebase_lens/contracts/architecture.py",
                    "src/codebase_lens/core/graph.py",
            "src/codebase_lens/analyzers/evidence_graph.py",
            "src/codebase_lens/reports/graph.py",
            "scripts/dev/audits/audit_phase11_evidence_graph.py",
            "src/codebase_lens/analyzers/graph_query.py",
            "src/codebase_lens/reports/graph_query.py",
            "scripts/dev/audits/audit_phase12_graph_query.py",
            "src/codebase_lens/reports/handoff_projection.py",
            "scripts/dev/audits/audit_phase13_handoff_projection_sidecar.py",
            "scripts/dev/audits/audit_phase14_projection_relevance.py",
            "scripts/dev/audits/audit_phase15_projection_semantics.py",
            "scripts/dev/audits/audit_phase16_projection_generality.py",
            "scripts/dev/audits/audit_phase17_projection_noise.py",
            "scripts/dev/audits/audit_phase18_projection_dedup.py",
            "scripts/dev/audits/audit_phase19_projection_roles_imports.py",
            "src/codebase_lens/contracts/command_surface.py",
            "scripts/dev/audits/audit_phase20_public_command_stability.py",
            "src/codebase_lens/contracts/fixture_matrix.py",
            "scripts/dev/audits/audit_phase21_release_fixture_matrix.py",
            "src/codebase_lens/core/audit_artifacts.py",
            "src/codebase_lens/contracts/release_safety.py",
            "scripts/dev/audits/audit_phase22_release_safety.py",
            "scripts/dev/audits/audit_phase23_audit_report_sanitization.py",
            "README.md",
            "docs/LOCAL_WORKFLOW.md",
            "docs/AI_HANDOFF_WORKFLOW.md",
            "docs/RELEASE_CHECKLIST.md",
            "scripts/dev/audits/audit_phase24_documentation_workflow.py",
            "src/codebase_lens/core/budget.py",
            "src/codebase_lens/reports/diff.py",
            "src/codebase_lens/reports/contract.py",
            "scripts/dev/audits/audit_phase25_report_contract_parity.py",
            "docs/V0_1_RELEASE_STATUS.md",
            "scripts/dev/audits/audit_phase26_v01_release_closure.py",
            "scripts/dev/audits/audit_phase27_reliability_corrections.py",
            "scripts/dev/audits/audit_phase28_manifest_consistency.py",
],
        "required_symbols": [
            {
                "path": "src/codebase_lens/cli.py",
                "symbols": [
                    "build_parser",
                    "main",
                    "_run_doctor",
                    "_run_snapshot",
                    "_run_pack",
                    "_run_clean",
                    "_run_graph",
                    "_run_tree",
                    "_run_file",
                    "_run_symbols",
                    "_run_imports",
                    "_run_cli_static",
                    "_run_routes_static",
                    "_run_diff",
                    "_run_changed",
                    "_run_tests_inventory",
                    "_run_callers",
                    "_run_contract",
                ],
            },
            {
                "path": "src/codebase_lens/analyzers/symbol_graph.py",
                "symbols": [
                    "SymbolGraphNode",
                    "SymbolGraphResult",
                    "collect_symbol_graph",
                    "symbol_graph_payload",
                    "render_symbol_graph_markdown",
                ],
            },
            {
                "path": "src/codebase_lens/reports/symbol_graph.py",
                "symbols": [
                    "write_symbol_graph_reports",
                ],
            },
            {
                "path": "src/codebase_lens/reports/cleanup.py",
                "symbols": [
                    "CleanedRunRecord",
                    "CleanResult",
                    "clean_archives",
                    "clean_result_payload",
                    "write_clean_report",
                ],
            },
            {
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
            {
                "path": "src/codebase_lens/contracts/architecture.py",
                "symbols": [
                    "ContractViolation",
                    "ContractResult",
                    "builtin_cbl_contract",
                    "load_contract_spec",
                    "evaluate_contract",
                ],
            },
                    {
                "path": "src/codebase_lens/core/graph.py",
                "symbols": [
                    "GraphNode",
                    "GraphEdge",
                    "EvidenceGraph",
                    "evidence_graph_payload",
                    "graph_slice_payload",
                ],
            },
            {
                "path": "src/codebase_lens/analyzers/evidence_graph.py",
                "symbols": [
                    "build_evidence_graph",
                ],
            },
            {
                "path": "src/codebase_lens/reports/graph.py",
                "symbols": [
                    "write_evidence_graph_reports",
                    "render_graph_summary",
                ],
            },
            {
                "path": "src/codebase_lens/analyzers/graph_query.py",
                "symbols": [
                    "GraphQueryResult",
                    "query_evidence_graph_payload",
                    "graph_query_payload",
                ],
            },
            {
                "path": "src/codebase_lens/reports/graph_query.py",
                "symbols": [
                    "write_graph_query_reports",
                    "render_graph_query_markdown",
                ],
            },
            {
                "path": "src/codebase_lens/reports/handoff_projection.py",
                "symbols": [
                    "HandoffProjectionResult",
                    "write_handoff_projection_reports",
                ],
            },
            {
                "path": "src/codebase_lens/core/budget.py",
                "symbols": [
                    "estimate_tokens_for_bytes",
                    "estimate_tokens_for_text",
                    "ranked_budget_file_records",
                    "build_budget_report_payload",
                ],
            },
            {
                "path": "src/codebase_lens/reports/diff.py",
                "symbols": [
                    "render_diff_summary_markdown",
                    "write_diff_reports",
                ],
            },
            {
                "path": "src/codebase_lens/reports/contract.py",
                "symbols": [
                    "render_contract_audit_markdown",
                    "write_contract_audit_reports",
                ],
            },
            {
                "path": "src/codebase_lens/core/redaction.py",
                "symbols": [
                    "redact_jsonable",
                    "redact_string",
                ],
            },
            {
                "path": "src/codebase_lens/analyzers/tests.py",
                "symbols": [
                    "classify_test_path",
                    "TestLikeSymbolRecord",
                ],
            },
            {
                "path": "scripts/dev/audits/audit_phase28_manifest_consistency.py",
                "symbols": [
                    "ManifestConsistencyIssue",
                    "ManifestConsistencyResult",
                    "run_manifest_consistency_audit",
                    "main",
                ],
            },
],
        "forbidden_imports": [
            {
                "id": "core-no-upward-imports",
                "from": "src/codebase_lens/core/**/*.py",
                "disallow": [
                    "codebase_lens.analyzers",
                    "codebase_lens.scanners",
                    "codebase_lens.reports",
                    "codebase_lens.git",
                    "codebase_lens.contracts",
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "git-no-upward-imports",
                "from": "src/codebase_lens/git/**/*.py",
                "disallow": [
                    "codebase_lens.analyzers",
                    "codebase_lens.scanners",
                    "codebase_lens.reports",
                    "codebase_lens.contracts",
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "scanners-no-analyzer-report-imports",
                "from": "src/codebase_lens/scanners/**/*.py",
                "disallow": [
                    "codebase_lens.analyzers",
                    "codebase_lens.reports",
                    "codebase_lens.contracts",
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "analyzers-no-report-or-cli-imports",
                "from": "src/codebase_lens/analyzers/**/*.py",
                "disallow": [
                    "codebase_lens.reports",
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "reports-no-cli-imports",
                "from": "src/codebase_lens/reports/**/*.py",
                "disallow": [
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "contracts-no-cli-imports",
                "from": "src/codebase_lens/contracts/**/*.py",
                "disallow": [
                    "codebase_lens.cli",
                ],
            },
        ],
    }


def _load_yaml_if_available(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise ValueError(
            "YAML contract files require PyYAML. Use JSON for dependency-free contract specs."
        ) from exc

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Contract spec must parse to an object.")
    return payload


def load_contract_spec(repo_root: str | Path, spec_path: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()

    if spec_path is None:
        return builtin_cbl_contract()

    target = resolve_user_path(root, spec_path, allow_absolute=True, allow_hard_excluded=False)
    if not target.is_file():
        raise ValueError(f"Contract spec does not exist: {spec_path}")

    suffix = target.suffix.lower()
    if suffix == ".json":
        payload = json.loads(target.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        payload = _load_yaml_if_available(target)
    else:
        raise ValueError("Contract spec must be .json, .yaml, or .yml.")

    if not isinstance(payload, dict):
        raise ValueError("Contract spec must be a JSON/YAML object.")

    return payload


def _path_matches(pattern: str, path: str) -> bool:
    normalized_pattern = pattern.replace("\\", "/").strip("/")
    normalized_path = path.replace("\\", "/").strip("/")

    if normalized_pattern.endswith("/**/*.py"):
        prefix = normalized_pattern[: -len("/**/*.py")]
        return normalized_path.startswith(prefix + "/") and normalized_path.endswith(".py")

    if normalized_pattern.endswith("/**"):
        prefix = normalized_pattern[: -len("/**")]
        return normalized_path.startswith(prefix + "/")

    return fnmatch(normalized_path, normalized_pattern)


def _normalize_imported_name(module: str | None, name: str | None) -> str:
    if module and name:
        return f"{module}.{name}"
    if module:
        return module
    if name:
        return name
    return ""


def _import_edges_for_file(repo_root: Path, relative_path: str) -> tuple[tuple[int, str, str], ...]:
    target = repo_root / relative_path
    read_result = read_text_with_policy(target)

    if read_result.skipped_reason or read_result.text is None:
        return ()

    try:
        tree = ast.parse(read_result.text, filename=relative_path)
    except SyntaxError:
        return ()

    edges: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = _normalize_imported_name(alias.name, None)
                edges.append((int(getattr(node, "lineno", 1)), imported, f"import {alias.name}"))

        elif isinstance(node, ast.ImportFrom):
            module = node.module
            for alias in node.names:
                imported = _normalize_imported_name(module, alias.name)
                raw = f"from {module or ''} import {alias.name}"
                edges.append((int(getattr(node, "lineno", 1)), imported, raw))

    return tuple(edges)


def _top_level_symbols(repo_root: Path, relative_path: str) -> tuple[str, ...]:
    target = repo_root / relative_path
    read_result = read_text_with_policy(target)

    if read_result.skipped_reason or read_result.text is None:
        return ()

    try:
        tree = ast.parse(read_result.text, filename=relative_path)
    except SyntaxError:
        return ()

    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
    return tuple(symbols)


def _required_files_violations(repo_root: Path, spec: dict[str, Any]) -> list[ContractViolation]:
    violations: list[ContractViolation] = []

    for raw_path in spec.get("required_files", []) or []:
        if not isinstance(raw_path, str):
            violations.append(
                ContractViolation(
                    rule_id="required-file-invalid",
                    severity="error",
                    message="required_files entries must be strings.",
                    path=None,
                    line=None,
                    evidence=repr(raw_path),
                )
            )
            continue

        normalized = raw_path.replace("\\", "/").strip("/")
        if is_hard_excluded_relative(normalized):
            violations.append(
                ContractViolation(
                    rule_id="required-file-hard-excluded",
                    severity="error",
                    message=f"Required file points to a hard-excluded path: {normalized}",
                    path=normalized,
                    line=None,
                    evidence=normalized,
                )
            )
            continue

        if not (repo_root / normalized).is_file():
            violations.append(
                ContractViolation(
                    rule_id="required-file-missing",
                    severity="error",
                    message=f"Required file is missing: {normalized}",
                    path=normalized,
                    line=None,
                    evidence=normalized,
                )
            )

    return violations


def _required_symbols_violations(repo_root: Path, spec: dict[str, Any]) -> list[ContractViolation]:
    violations: list[ContractViolation] = []

    for entry in spec.get("required_symbols", []) or []:
        if not isinstance(entry, dict):
            violations.append(
                ContractViolation(
                    rule_id="required-symbol-entry-invalid",
                    severity="error",
                    message="required_symbols entries must be objects.",
                    path=None,
                    line=None,
                    evidence=repr(entry),
                )
            )
            continue

        raw_path = entry.get("path")
        raw_symbols = entry.get("symbols", [])

        if not isinstance(raw_path, str) or not isinstance(raw_symbols, list):
            violations.append(
                ContractViolation(
                    rule_id="required-symbol-entry-invalid",
                    severity="error",
                    message="required_symbols entries need string path and list symbols.",
                    path=raw_path if isinstance(raw_path, str) else None,
                    line=None,
                    evidence=repr(entry),
                )
            )
            continue

        relative_path = raw_path.replace("\\", "/").strip("/")
        available = set(_top_level_symbols(repo_root, relative_path))

        for symbol in raw_symbols:
            if not isinstance(symbol, str):
                violations.append(
                    ContractViolation(
                        rule_id="required-symbol-invalid",
                        severity="error",
                        message="Required symbol names must be strings.",
                        path=relative_path,
                        line=None,
                        evidence=repr(symbol),
                    )
                )
                continue

            if symbol not in available:
                violations.append(
                    ContractViolation(
                        rule_id="required-symbol-missing",
                        severity="error",
                        message=f"Required symbol is missing: {symbol}",
                        path=relative_path,
                        line=None,
                        evidence=symbol,
                    )
                )

    return violations


def _forbidden_import_violations(repo_root: Path, spec: dict[str, Any]) -> tuple[list[ContractViolation], int]:
    violations: list[ContractViolation] = []
    rules = spec.get("forbidden_imports", []) or []

    universe = discover_file_universe(repo_root)
    python_paths = [
        record.path
        for record in universe.included_files
        if Path(record.path).suffix.lower() in {".py", ".pyw", ".pyi"}
    ]

    for rule in rules:
        if not isinstance(rule, dict):
            violations.append(
                ContractViolation(
                    rule_id="forbidden-import-rule-invalid",
                    severity="error",
                    message="forbidden_imports entries must be objects.",
                    path=None,
                    line=None,
                    evidence=repr(rule),
                )
            )
            continue

        rule_id = str(rule.get("id") or "forbidden-import")
        from_pattern = rule.get("from")
        disallow = rule.get("disallow", [])

        if not isinstance(from_pattern, str) or not isinstance(disallow, list):
            violations.append(
                ContractViolation(
                    rule_id=rule_id,
                    severity="error",
                    message="Forbidden import rule needs string 'from' and list 'disallow'.",
                    path=None,
                    line=None,
                    evidence=repr(rule),
                )
            )
            continue

        disallowed_prefixes = [item for item in disallow if isinstance(item, str)]

        for path in python_paths:
            if not _path_matches(from_pattern, path):
                continue

            for line, imported, raw in _import_edges_for_file(repo_root, path):
                for prefix in disallowed_prefixes:
                    if imported == prefix or imported.startswith(prefix + "."):
                        violations.append(
                            ContractViolation(
                                rule_id=rule_id,
                                severity="error",
                                message=f"Forbidden import from {path}: {imported}",
                                path=path,
                                line=line,
                                evidence=raw,
                            )
                        )

    return violations, len(python_paths)


def evaluate_contract(repo_root: str | Path, spec: dict[str, Any] | None = None) -> ContractResult:
    root = Path(repo_root).resolve()
    payload = spec or builtin_cbl_contract()

    contract_id = str(payload.get("id") or "unnamed-contract")
    name = str(payload.get("name") or contract_id)

    violations: list[ContractViolation] = []
    warnings: list[str] = []

    violations.extend(_required_files_violations(root, payload))
    violations.extend(_required_symbols_violations(root, payload))
    import_violations, python_files_checked = _forbidden_import_violations(root, payload)
    violations.extend(import_violations)

    required_files_count = len(payload.get("required_files", []) or [])
    required_symbols_count = sum(
        len(entry.get("symbols", []))
        for entry in payload.get("required_symbols", []) or []
        if isinstance(entry, dict) and isinstance(entry.get("symbols", []), list)
    )
    forbidden_import_rules_count = len(payload.get("forbidden_imports", []) or [])

    error_count = sum(1 for item in violations if item.severity == "error")
    warning_count = sum(1 for item in violations if item.severity == "warning") + len(warnings)

    return ContractResult(
        contract_id=contract_id,
        name=name,
        violations=tuple(sorted(violations, key=lambda item: (item.severity, item.rule_id, item.path or "", item.line or 0))),
        warnings=tuple(warnings),
        counts={
            "violations": len(violations),
            "errors": error_count,
            "warnings": warning_count,
            "required_files_checked": required_files_count,
            "required_symbols_checked": required_symbols_count,
            "forbidden_import_rules_checked": forbidden_import_rules_count,
            "python_files_checked": python_files_checked,
        },
    )
