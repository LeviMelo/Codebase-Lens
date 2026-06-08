from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()
PROJECTION = ROOT / "src" / "codebase_lens" / "reports" / "handoff_projection.py"


SYMBOL_ROLE = r'''
def _is_cli_handler_label(label: str) -> bool:
    return label.startswith("_run_")


def _is_cli_entrypoint_label(label: str) -> bool:
    return label in {"main", "build_parser", "create_parser", "make_parser"}


def _is_cli_support_label(label: str) -> bool:
    if label.startswith((
        "_base_",
        "_add_",
        "_common_",
        "_parser_",
        "_parse_",
        "_coerce_",
        "_resolve_",
        "_print_",
        "_format_",
        "_build_",
    )):
        return True

    lowered = label.lower()
    return any(term in lowered for term in {"arg", "option", "manifest", "namespace", "parser"})


def _symbol_role(node: dict[str, Any] | None, profile: ProjectProfile) -> str:
    if not isinstance(node, dict):
        return "unknown"

    path = _node_path(node)
    label = _node_label(node)
    kind = _node_kind(node)
    data = _node_data(node)

    if kind == "cli_command":
        return "cli_command"

    if path in profile.cli_paths:
        if kind == "file":
            return "cli_surface"
        if _is_cli_handler_label(label):
            return "cli_handler"
        if _is_cli_entrypoint_label(label):
            return "cli_entrypoint"
        if _is_cli_support_label(label):
            return "cli_support"
        if label.startswith("_"):
            return "cli_support"
        return "cli_support"

    blob = " ".join([path, label, str(data.get("signature", ""))]).lower()
    path_role = _path_role(path, profile)

    if _contains_any(blob, REPORTING_NAME_TERMS):
        return "reporting"
    if _contains_any(blob, ANALYSIS_NAME_TERMS):
        return "analysis"
    if _contains_any(blob, CORE_NAME_TERMS):
        return "model_or_core"
    if _contains_any(blob, IO_NAME_TERMS):
        return "io_or_safety"
    return path_role
'''


EDGE_FAMILY = r'''
def _edge_family(edge: dict[str, Any], source: dict[str, Any] | None, target: dict[str, Any] | None, profile: ProjectProfile) -> str:
    kind = str(edge.get("kind") or "")
    source_role = _symbol_role(source, profile) if isinstance(source, dict) else "unknown"
    target_role = _symbol_role(target, profile) if isinstance(target, dict) else "unknown"
    target_kind = _node_kind(target)
    target_path = _node_path(target)

    if kind == "file_declares_cli_command" or target_kind == "cli_command":
        return "cli_to_handler"

    if kind in {"file_imports_module", "module_resolves_to_file", "internal_import_dependency"}:
        if target_path and _is_product_path(target_path, profile):
            return "import_dependency"
        return "external_import_dependency"

    if source_role == "cli_entrypoint" and target_role in {"cli_handler", "cli_support", "cli_command"}:
        return "cli_entrypoint_to_handler"

    if source_role == "cli_handler" and target_role in {"analysis", "model_or_core", "io_or_safety", "product", "reporting"}:
        return "cli_handler_to_analysis"

    if source_role == "cli_support" and target_role in {"io_or_safety", "model_or_core", "reporting"}:
        return "cli_support_to_io_or_config"

    if source_role == "cli_support" and target_role in {"analysis", "product"}:
        return "cli_support_to_analysis"

    if source_role in {"analysis", "product"} and target_role == "reporting":
        return "analysis_to_report"
    if source_role == "reporting" and target_role == "reporting":
        return "report_to_output_writer"
    if source_role == "analysis" and target_role == "model_or_core":
        return "analysis_to_model"
    if source_role in {"io_or_safety", "analysis"} and target_role == "io_or_safety":
        return "scanner_or_io_flow"
    if kind == "file_contains_symbol":
        return "declaration_context"
    return "other_product_flow"
'''


EDGE_SELECTION_REASON = r'''
def _edge_selection_reason(edge: dict[str, Any], family: str) -> str:
    kind = str(edge.get("kind") or "")

    if family == "cli_to_handler":
        return "connects command or route declaration to executable surface"
    if family == "cli_entrypoint_to_handler":
        return "connects CLI parser/entrypoint wiring to command handler surface"
    if family == "cli_handler_to_analysis":
        return "connects a concrete command handler to analysis or product logic"
    if family == "cli_support_to_analysis":
        return "connects CLI support/configuration helper to analysis logic"
    if family == "cli_support_to_io_or_config":
        return "connects CLI support/configuration helper to I/O, Git, or report configuration"
    if family == "analysis_to_report":
        return "connects analysis logic to report generation"
    if family == "report_to_output_writer":
        return "connects reporting layer to output writer or renderer"
    if family == "import_dependency":
        return "shows resolved internal project import dependency"
    if family == "external_import_dependency":
        return "shows external import dependency; normally omitted unless no internal alternatives exist"
    if family == "analysis_to_model":
        return "connects analysis logic to model or core structures"
    if family == "scanner_or_io_flow":
        return "connects filesystem, scanner, safety, Git, or I/O flow"
    if kind == "file_contains_symbol":
        return "fallback declaration context for a product symbol"
    return "high-scoring product dependency edge"
'''


EDGE_RELEVANCE_SCORE = r'''
def _edge_relevance_score(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]], profile: ProjectProfile) -> float:
    kind = str(edge.get("kind") or "")
    source = _source_node(edge, nodes_by_id)
    target = _target_node(edge, nodes_by_id)
    source_path = _node_path(source)
    target_path = _node_path(target)
    source_label = _node_label(source) if source else ""
    target_label = _node_label(target) if target else str(edge.get("target_text") or "")
    source_role = _symbol_role(source, profile) if isinstance(source, dict) else "unknown"
    target_role = _symbol_role(target, profile) if isinstance(target, dict) else "unknown"
    family = _edge_family(edge, source, target, profile)

    score = 0.0

    if _is_product_path(source_path, profile):
        score += 100.0
    if _is_product_path(target_path, profile):
        score += 100.0
    if _is_low_value_path(source_path) or _is_low_value_path(target_path):
        score -= 300.0

    if kind == "symbol_calls_symbol":
        score += 150.0
    elif kind == "internal_import_dependency":
        score += 130.0
    elif kind == "file_declares_cli_command":
        score += 120.0
    elif kind == "file_imports_module":
        score += 95.0
    elif kind == "module_resolves_to_file":
        score += 80.0
    elif kind == "file_contains_symbol":
        score += 10.0

    family_bonus = {
        "cli_handler_to_analysis": 105.0,
        "handler_to_analysis": 95.0,
        "analysis_to_report": 90.0,
        "analysis_to_model": 80.0,
        "scanner_or_io_flow": 75.0,
        "cli_support_to_io_or_config": 65.0,
        "cli_support_to_analysis": 60.0,
        "cli_entrypoint_to_handler": 60.0,
        "cli_to_handler": 55.0,
        "import_dependency": 70.0,
        "report_to_output_writer": 35.0,
        "other_product_flow": 20.0,
        "declaration_context": 0.0,
        "external_import_dependency": -120.0,
    }
    score += family_bonus.get(family, 0.0)

    if source_role in {"analysis", "reporting", "cli_handler", "cli_entrypoint"}:
        score += 35.0
    if source_role == "cli_support":
        score += 10.0
    if target_role in {"analysis", "reporting", "model_or_core", "io_or_safety"}:
        score += 35.0

    if source_label in LOW_VALUE_HELPER_NAMES or target_label in LOW_VALUE_HELPER_NAMES:
        score -= 120.0

    if source_label.startswith(("write_", "build_", "collect_", "query_", "render_", "parse_", "scan_", "analyze_")):
        score += 35.0
    if target_label.startswith(("write_", "build_", "collect_", "query_", "render_", "parse_", "scan_", "analyze_")):
        score += 35.0

    if source_role == "cli_support" and family in {"cli_handler_to_analysis", "handler_to_analysis"}:
        score -= 150.0

    return score
'''


EDGE_PAYLOAD = r'''
def _edge_payload(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]], profile: ProjectProfile) -> dict[str, Any]:
    source = _source_node(edge, nodes_by_id)
    target = _target_node(edge, nodes_by_id)
    family = _edge_family(edge, source, target, profile)
    score = _edge_relevance_score(edge, nodes_by_id, profile)

    return {
        "kind": edge.get("kind"),
        "source": _display_node(source, fallback=str(edge.get("source") or "")),
        "target": _display_node(target, fallback=str(edge.get("target") or edge.get("target_text") or "<unresolved>")),
        "source_path": _node_path(source),
        "target_path": _node_path(target),
        "source_role": _symbol_role(source, profile) if isinstance(source, dict) else "unknown",
        "target_role": _symbol_role(target, profile) if isinstance(target, dict) else "unknown",
        "confidence": edge.get("confidence"),
        "evidence": _edge_evidence(edge),
        "edge_family": family,
        "selection_reason": _edge_selection_reason(edge, family),
        "relevance_score": round(score, 3),
    }
'''


REPRESENTATIVE_AND_IMPORT_HELPERS = r'''
def _module_name_from_source_path(path: str, profile: ProjectProfile) -> str:
    normalized = path.replace("\\", "/")
    if not normalized.endswith(".py"):
        return ""

    for prefix in profile.source_prefixes:
        if normalized.startswith(prefix):
            relative = normalized[len(prefix):]
            prefix_parts = _path_parts(prefix.rstrip("/"))
            package = prefix_parts[-1] if prefix_parts else ""
            module_parts = list(_path_parts(relative))
            if not module_parts:
                return package
            leaf = module_parts[-1]
            if leaf == "__init__.py":
                module_parts = module_parts[:-1]
            elif leaf.endswith(".py"):
                module_parts[-1] = leaf[:-3]
            if package:
                return ".".join([package, *module_parts])
            return ".".join(module_parts)

    return ""


def _file_node_for_path(path: str, nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for node in nodes:
        if isinstance(node, dict) and node.get("kind") == "file" and _node_path(node) == path:
            return node
    return None


def _import_record_source_path(record: dict[str, Any]) -> str:
    for key in ("path", "file_path", "source_path", "source_file", "file"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _import_record_module(record: dict[str, Any]) -> str:
    for key in ("module", "imported_module", "target_module", "name", "qualified_name", "module_name"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _import_record_line(record: dict[str, Any]) -> int | None:
    for key in ("line", "lineno", "line_number", "start_line"):
        value = record.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _import_record_evidence(record: dict[str, Any], source_path: str) -> str:
    evidence = record.get("evidence")
    if isinstance(evidence, str) and evidence:
        return evidence
    line = _import_record_line(record)
    if line is not None:
        return f"{source_path}:L{line}-L{line}"
    return source_path


def _import_record_resolved_path(record: dict[str, Any]) -> str:
    for key in ("resolved_path", "resolved_file", "resolved_module_path", "target_path", "target_file", "path_resolved"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _extract_import_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    for key in ("imports", "records", "import_records", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(value)

    if not candidates:
        graph = payload.get("graph")
        if isinstance(graph, dict):
            for key in ("imports", "records", "import_records", "items"):
                value = graph.get(key)
                if isinstance(value, list):
                    candidates.extend(value)

    return [item for item in candidates if isinstance(item, dict)]


def _read_import_records(layout: OutputLayout) -> list[dict[str, Any]]:
    payload = _read_json(layout.latest_dir / "import_graph.json")
    return _extract_import_records(payload)


def _module_file_lookup(nodes: list[dict[str, Any]], profile: ProjectProfile) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict) or node.get("kind") != "file":
            continue
        path = _node_path(node)
        if not _is_product_path(path, profile):
            continue
        module = _module_name_from_source_path(path, profile)
        if module:
            lookup[module] = node
    return lookup


def _resolved_internal_import_payloads(
    *,
    layout: OutputLayout,
    nodes: list[dict[str, Any]],
    profile: ProjectProfile,
) -> list[dict[str, Any]]:
    module_lookup = _module_file_lookup(nodes, profile)
    file_lookup = {_node_path(node): node for node in nodes if isinstance(node, dict) and node.get("kind") == "file"}
    records = _read_import_records(layout)

    payloads: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for record in records:
        source_path = _import_record_source_path(record)
        module = _import_record_module(record)
        resolved_path = _import_record_resolved_path(record)

        if not source_path or not _is_product_path(source_path, profile):
            continue

        target_node: dict[str, Any] | None = None
        if resolved_path and _is_product_path(resolved_path, profile):
            target_node = file_lookup.get(resolved_path) or {"kind": "file", "path": resolved_path, "label": resolved_path}
        elif module in module_lookup:
            target_node = module_lookup[module]
        elif module:
            # Try longest-prefix resolution for imports of symbols from modules.
            parts = module.split(".")
            for end in range(len(parts), 0, -1):
                candidate = ".".join(parts[:end])
                if candidate in module_lookup:
                    target_node = module_lookup[candidate]
                    break

        if not target_node:
            continue

        target_path = _node_path(target_node)
        if not target_path or target_path == source_path or not _is_product_path(target_path, profile):
            continue

        key = (source_path, module, target_path)
        if key in seen:
            continue
        seen.add(key)

        source_node = file_lookup.get(source_path) or {"kind": "file", "path": source_path, "label": source_path}
        evidence = _import_record_evidence(record, source_path)

        payloads.append(
            {
                "kind": "internal_import_dependency",
                "source": _display_node(source_node, fallback=source_path),
                "target": _display_node(target_node, fallback=target_path),
                "source_path": source_path,
                "target_path": target_path,
                "source_role": _path_role(source_path, profile),
                "target_role": _path_role(target_path, profile),
                "confidence": record.get("confidence") or "exact_import_statement",
                "evidence": evidence,
                "edge_family": "import_dependency",
                "selection_reason": "shows resolved internal project import dependency",
                "relevance_score": 505.0,
                "imported_module": module,
            }
        )

    return payloads


def _representative_edge_key(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(payload.get("kind") or ""),
        str(payload.get("source") or ""),
        str(payload.get("target") or ""),
        str(payload.get("edge_family") or ""),
    )


def _collapse_representative_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for payload in payloads:
        key = _representative_edge_key(payload)
        evidence = str(payload.get("evidence") or "")
        score = float(payload.get("relevance_score") or 0.0)

        if key not in groups:
            groups[key] = {
                "payload": dict(payload),
                "best_score": score,
                "evidence_count": 0,
                "sample_evidence": [],
            }

        group = groups[key]
        group["evidence_count"] = int(group["evidence_count"]) + 1

        samples = group["sample_evidence"]
        if evidence and evidence not in samples:
            samples.append(evidence)

        if score > float(group["best_score"]):
            group["payload"] = dict(payload)
            group["best_score"] = score

    collapsed: list[dict[str, Any]] = []
    for group in groups.values():
        payload = dict(group["payload"])
        samples = list(group["sample_evidence"])[:5]
        payload["evidence_count"] = int(group["evidence_count"])
        payload["sample_evidence"] = samples
        if samples:
            payload["evidence"] = samples[0]
        collapsed.append(payload)

    return sorted(
        collapsed,
        key=lambda item: (
            -float(item.get("relevance_score") or 0.0),
            -int(item.get("evidence_count") or 0),
            str(item.get("edge_family") or ""),
            str(item.get("source") or ""),
            str(item.get("target") or ""),
        ),
    )


def _representative_edges(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    profile: ProjectProfile,
    *,
    limit: int,
    layout: OutputLayout | None = None,
) -> list[dict[str, Any]]:
    nodes_by_id = _node_by_id(nodes)

    allowed = {
        "symbol_calls_symbol",
        "file_declares_cli_command",
        "module_resolves_to_file",
        "file_contains_symbol",
    }

    payload_candidates: list[dict[str, Any]] = []
    fallback_external_imports: list[dict[str, Any]] = []

    for edge in edges:
        if not isinstance(edge, dict):
            continue

        kind = str(edge.get("kind") or "")
        if kind == "file_imports_module":
            source = _source_node(edge, nodes_by_id)
            target = _target_node(edge, nodes_by_id)
            source_path = _node_path(source)
            target_path = _node_path(target)
            if _is_product_path(source_path, profile) and target_path and _is_product_path(target_path, profile):
                payload_candidates.append(_edge_payload(edge, nodes_by_id, profile))
            elif _is_product_path(source_path, profile):
                fallback_external_imports.append(_edge_payload(edge, nodes_by_id, profile))
            continue

        if kind not in allowed:
            continue

        source = _source_node(edge, nodes_by_id)
        target = _target_node(edge, nodes_by_id)
        source_path = _node_path(source)
        target_path = _node_path(target)

        if not (_is_product_path(source_path, profile) or _is_product_path(target_path, profile)):
            continue

        if kind in {"module_resolves_to_file"}:
            if not target_path or not _is_product_path(target_path, profile):
                fallback_external_imports.append(_edge_payload(edge, nodes_by_id, profile))
                continue

        if kind == "file_contains_symbol" and not _is_product_path(source_path, profile):
            continue

        payload_candidates.append(_edge_payload(edge, nodes_by_id, profile))

    if layout is not None:
        payload_candidates.extend(
            _resolved_internal_import_payloads(
                layout=layout,
                nodes=nodes,
                profile=profile,
            )
        )

    if not payload_candidates:
        payload_candidates = fallback_external_imports

    ranked = _collapse_representative_payloads(payload_candidates)

    family_caps = {
        "cli_entrypoint_to_handler": 2,
        "cli_handler_to_analysis": 4,
        "cli_support_to_analysis": 2,
        "cli_support_to_io_or_config": 2,
        "handler_to_analysis": 2,
        "cli_to_handler": 2,
        "analysis_to_model": 3,
        "scanner_or_io_flow": 3,
        "analysis_to_report": 3,
        "report_to_output_writer": 2,
        "import_dependency": 3,
        "external_import_dependency": 1,
        "declaration_context": 1,
        "other_product_flow": 3,
    }

    coverage_order = [
        "cli_handler_to_analysis",
        "cli_support_to_analysis",
        "cli_support_to_io_or_config",
        "analysis_to_model",
        "scanner_or_io_flow",
        "analysis_to_report",
        "report_to_output_writer",
        "cli_entrypoint_to_handler",
        "cli_to_handler",
        "import_dependency",
        "other_product_flow",
        "declaration_context",
        "external_import_dependency",
    ]

    selected_edges: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str, str]] = set()
    family_counts: Counter[str] = Counter()

    def add(payload: dict[str, Any]) -> bool:
        key = _representative_edge_key(payload)
        if key in selected_keys:
            return False

        family = str(payload.get("edge_family") or "")
        if family_counts[family] >= family_caps.get(family, 2):
            return False

        selected_edges.append(payload)
        selected_keys.add(key)
        family_counts[family] += 1
        return True

    for family in coverage_order:
        for payload in ranked:
            if payload.get("edge_family") == family:
                add(payload)
                break
        if len(selected_edges) >= limit:
            break

    for payload in ranked:
        if len(selected_edges) >= limit:
            break
        add(payload)

    return selected_edges[:limit]
'''


PROJECTION_PAYLOAD = r'''
def _projection_payload(
    layout: OutputLayout,
    *,
    issue: str | None,
    changed_only: bool,
    budget: int,
    focus_terms: tuple[str, ...],
    counts: dict[str, int],
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    graph = _read_json(layout.latest_dir / "evidence_graph.json")
    graph_counts = _as_dict(graph.get("counts"))
    nodes = [node for node in _as_list(graph.get("nodes")) if isinstance(node, dict)]
    edges = [edge for edge in _as_list(graph.get("edges")) if isinstance(edge, dict)]
    profile = _infer_project_profile(nodes)
    budget_report = _read_json(layout.latest_dir / "budget_report.json")
    changed_files, changed_symbols = _changed_records(layout, limit=20)

    node_kinds = Counter(str(node.get("kind")) for node in nodes)
    edge_kinds = Counter(str(edge.get("kind")) for edge in edges)
    unresolved_groups = _unresolved_call_groups(nodes, edges, profile, limit=16)

    return {
        "schema": {
            "name": "cbl.handoff_projection",
            "version": 5,
        },
        "issue": issue,
        "scope": "changed" if changed_only else "full",
        "project_profile": {
            "source_prefixes": list(profile.source_prefixes),
            "cli_paths": list(profile.cli_paths),
        },
        "budget": {
            "requested_budget_tokens": budget,
            "budget_pressure": budget_report.get("budget_pressure"),
            "focus_terms": list(focus_terms),
            "estimation_method": budget_report.get("estimation_method"),
        },
        "counts": {
            **counts,
            "evidence_graph_nodes": graph_counts.get("nodes", counts.get("evidence_graph_nodes", 0)),
            "evidence_graph_edges": graph_counts.get("edges", counts.get("evidence_graph_edges", 0)),
            "evidence_graph_unresolved_edges": graph_counts.get("unresolved_edges", counts.get("evidence_graph_unresolved_edges", 0)),
        },
        "graph": {
            "node_kinds": dict(sorted(node_kinds.items())),
            "edge_kinds": dict(sorted(edge_kinds.items())),
            "high_connectivity_product_symbols": [
                {
                    "label": node.get("label"),
                    "kind": node.get("kind"),
                    "location": _node_location(node),
                    "display": _display_node(node),
                    "role": _symbol_role(node, profile),
                    "signature": _node_data(node).get("signature"),
                }
                for node in _rank_product_symbols(nodes, edges, profile, limit=12, focus_terms=focus_terms)
            ],
            "entrypoints": [
                {
                    "label": node.get("label"),
                    "kind": node.get("kind"),
                    "location": _node_location(node),
                    "display": _display_node(node),
                    "data": _node_data(node),
                }
                for node in _entrypoints(nodes, limit=18)
            ],
            "representative_edges": _representative_edges(nodes, edges, profile, limit=20, layout=layout),
            "unresolved_static_calls": unresolved_groups["dynamic_or_dispatch_calls"],
            **unresolved_groups,
        },
        "changed_scope": {
            "changed_only": changed_only,
            "changed_files": changed_files,
            "changed_symbols": changed_symbols,
            "empty_changed_scope": bool(changed_only and not changed_files and not changed_symbols),
        },
        "sidecar_artifacts": {
            "legacy_ai_handoff_md": ".codecontext/latest/ai_handoff.md",
            "handoff_projection_md": ".codecontext/latest/handoff_projection.md",
            "handoff_projection_json": ".codecontext/latest/handoff_projection.json",
            "evidence_graph_json": ".codecontext/latest/evidence_graph.json",
            "graph_summary_md": ".codecontext/latest/graph_summary.md",
            "symbol_graph_json": ".codecontext/latest/symbol_graph.json",
            "symbol_graph_md": ".codecontext/latest/symbol_graph.md",
            "call_graph_json": ".codecontext/latest/call_graph.json",
            "module_graph_json": ".codecontext/latest/module_graph.json",
        },
        "warnings": list(warnings),
    }
'''


AUDIT = r'''
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


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


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def main() -> int:
    for relative in [
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 19 projection role/import audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    if payload.get("schema", {}).get("version") != 5:
        fail("handoff_projection schema version was not advanced to 5.")

    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])
    symbols = graph.get("high_connectivity_product_symbols", [])

    if not edges:
        fail("No representative edges emitted.")

    base_manifest_edges = [
        edge
        for edge in edges
        if "_base_manifest_args" in str(edge.get("source"))
    ]
    for edge in base_manifest_edges:
        if edge.get("source_role") == "cli_handler":
            fail(f"_base_manifest_args incorrectly classified as cli_handler: {edge}")
        if edge.get("edge_family") in {"handler_to_analysis", "cli_handler_to_analysis"}:
            fail(f"_base_manifest_args incorrectly emitted as handler edge: {edge}")

    if base_manifest_edges and not any(
        edge.get("edge_family") in {"cli_support_to_analysis", "cli_support_to_io_or_config"}
        for edge in base_manifest_edges
    ):
        fail(f"_base_manifest_args did not receive a CLI support family: {base_manifest_edges}")

    handler_edges = [
        edge
        for edge in edges
        if str(edge.get("source")).split("::")[-1].startswith("_run_")
    ]
    if not handler_edges:
        fail("No _run_* CLI handler edge was selected.")
    for edge in handler_edges:
        if edge.get("source_role") != "cli_handler":
            fail(f"_run_* source not classified as cli_handler: {edge}")
        if edge.get("edge_family") not in {"cli_handler_to_analysis", "report_to_output_writer", "other_product_flow"}:
            fail(f"_run_* source received unexpected family: {edge}")

    import_edges = [
        edge
        for edge in edges
        if edge.get("edge_family") == "import_dependency"
    ]
    for edge in import_edges:
        if edge.get("kind") == "file_imports_module" and not edge.get("target_path"):
            fail(f"Unresolved/external import was surfaced as internal import dependency: {edge}")
        if not edge.get("target_path"):
            fail(f"Import dependency lacks target_path: {edge}")

    if not any(edge.get("kind") == "internal_import_dependency" for edge in import_edges):
        fail("No recovered internal import dependency was selected.")

    symbol_roles = {item.get("role") for item in symbols}
    if "cli_handler" not in symbol_roles and not any("_run_" in str(item.get("display")) for item in symbols):
        fail("High-connectivity symbols do not expose refined CLI handler semantics.")

    print("PASS: Phase 19 projection role/import audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


TEST = r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def test_projection_refines_cli_roles_and_recovers_internal_imports() -> None:
    result = run_cbl("pack", "--issue", "projection role import test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads((ROOT / ".codecontext" / "latest" / "handoff_projection.json").read_text(encoding="utf-8"))
    assert payload["schema"]["version"] == 5

    edges = payload["graph"]["representative_edges"]
    assert edges

    base_edges = [edge for edge in edges if "_base_manifest_args" in str(edge["source"])]
    for edge in base_edges:
        assert edge["source_role"] != "cli_handler"
        assert edge["edge_family"] not in {"handler_to_analysis", "cli_handler_to_analysis"}

    run_edges = [edge for edge in edges if str(edge["source"]).split("::")[-1].startswith("_run_")]
    assert run_edges
    for edge in run_edges:
        assert edge["source_role"] == "cli_handler"

    import_edges = [edge for edge in edges if edge["edge_family"] == "import_dependency"]
    assert import_edges
    assert any(edge["kind"] == "internal_import_dependency" for edge in import_edges)
    for edge in import_edges:
        assert edge["target_path"]
        assert edge["target_path"].startswith("src/codebase_lens/")

    symbol_roles = {item["role"] for item in payload["graph"]["high_connectivity_product_symbols"]}
    assert "cli_handler" in symbol_roles or any("_run_" in item["display"] for item in payload["graph"]["high_connectivity_product_symbols"])
'''


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def replace_function(source: str, function_name: str, replacement: str) -> str:
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one function named {function_name}, found {len(matches)}.")

    node = matches[0]
    if node.end_lineno is None:
        raise RuntimeError(f"AST node for {function_name} has no end_lineno.")

    lines = source.splitlines()
    new_lines = lines[: node.lineno - 1] + normalize(replacement).splitlines() + lines[node.end_lineno :]
    return "\n".join(new_lines).rstrip() + "\n"


def remove_functions(source: str, names: set[str]) -> str:
    tree = ast.parse(source)
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            if node.end_lineno is None:
                raise RuntimeError(f"AST node for {node.name} has no end_lineno.")
            spans.append((node.lineno, node.end_lineno))

    if not spans:
        return source

    remove_lines: set[int] = set()
    for start, end in spans:
        remove_lines.update(range(start, end + 1))

    kept = [line for index, line in enumerate(source.splitlines(), start=1) if index not in remove_lines]
    return "\n".join(kept).rstrip() + "\n"


def write_file(relative: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
    if path.suffix == ".py":
        modified.add(path)


def list_bounds_for_key(text: str, key: str) -> tuple[int, int]:
    match = re.search(rf'(?P<quote>["\']){re.escape(key)}(?P=quote)\s*:\s*\[', text)
    if not match:
        raise RuntimeError(f"Could not find list key {key!r}.")

    open_index = text.find("[", match.start())
    depth = 0
    quote: str | None = None
    escaped = False
    i = open_index

    while i < len(text):
        ch = text[i]

        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch in {"'", '"'}:
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return open_index, i

        i += 1

    raise RuntimeError(f"Could not find closing bracket for {key!r}.")


def insert_before_list_close(text: str, key: str, block: str) -> str:
    _, close = list_bounds_for_key(text, key)
    return text[:close] + block + text[close:]


def patch_contract(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    required_file = "scripts/dev/audits/audit_phase19_projection_roles_imports.py"
    if f'"{required_file}"' not in text and f"'{required_file}'" not in text:
        text = insert_before_list_close(text, "required_files", f'            "{required_file}",\n')

    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def assert_parseable(paths: set[Path]) -> None:
    for path in sorted(paths):
        if path.suffix != ".py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise RuntimeError(f"Generated invalid Python in {path}: {exc}") from exc


def main() -> int:
    modified: set[Path] = set()

    source = PROJECTION.read_text(encoding="utf-8")
    source = remove_functions(
        source,
        {
            "_is_cli_handler_label",
            "_is_cli_entrypoint_label",
            "_is_cli_support_label",
            "_module_name_from_source_path",
            "_file_node_for_path",
            "_import_record_source_path",
            "_import_record_module",
            "_import_record_line",
            "_import_record_evidence",
            "_import_record_resolved_path",
            "_extract_import_records",
            "_read_import_records",
            "_module_file_lookup",
            "_resolved_internal_import_payloads",
            "_collapse_representative_payloads",
        },
    )

    replacements = {
        "_symbol_role": SYMBOL_ROLE,
        "_edge_family": EDGE_FAMILY,
        "_edge_selection_reason": EDGE_SELECTION_REASON,
        "_edge_relevance_score": EDGE_RELEVANCE_SCORE,
        "_edge_payload": EDGE_PAYLOAD,
        "_representative_edges": REPRESENTATIVE_AND_IMPORT_HELPERS,
        "_projection_payload": PROJECTION_PAYLOAD,
    }

    for function_name, replacement in replacements.items():
        source = replace_function(source, function_name, replacement)

    PROJECTION.write_text(source, encoding="utf-8", newline="\n")
    modified.add(PROJECTION)

    write_file("scripts/dev/audits/audit_phase19_projection_roles_imports.py", AUDIT, modified)
    write_file("tests/test_handoff_projection_roles_imports.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 015H applied: projection CLI roles refined and internal imports recovered.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())