from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

HANDOFF_PROJECTION = r'''
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codebase_lens.reports.json import write_json_report
from codebase_lens.reports.manifest import OutputLayout


@dataclass(frozen=True)
class HandoffProjectionResult:
    outputs: dict[str, str]
    counts: dict[str, int]
    warnings: tuple[str, ...]


BUILTIN_OR_LOW_VALUE_CALLS = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "float",
    "int",
    "isinstance",
    "issubclass",
    "len",
    "list",
    "max",
    "min",
    "open",
    "print",
    "range",
    "repr",
    "reversed",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
    "SystemExit",
}

LOW_VALUE_HELPER_NAMES = {
    "fail",
    "run_cbl",
    "names_in_file",
    "make_repo",
    "assert_parseable",
    "main",
    "_get",
    "_as_dict",
    "_as_list",
    "_node_id",
    "_node_path",
    "_node_label",
    "_bullet",
}

LOW_VALUE_ATTRIBUTE_SUFFIXES = {
    ".append",
    ".extend",
    ".add",
    ".update",
    ".setdefault",
    ".get",
    ".items",
    ".keys",
    ".values",
    ".read_text",
    ".write_text",
    ".splitlines",
    ".rstrip",
    ".strip",
    ".replace",
    ".join",
    ".resolve",
    ".startswith",
    ".endswith",
    ".lower",
    ".upper",
}

DYNAMIC_DISPATCH_TERMS = {
    "args.handler",
    "handler",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "globals",
    "locals",
    "__import__",
    "import_module",
    "load_contract_spec",
    "evaluate_contract",
}

EXTERNAL_LIBRARY_PREFIXES = {
    "ast.",
    "json.",
    "os.",
    "re.",
    "subprocess.",
    "sys.",
    "Path.",
    "pathlib.",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or "")


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or node.get("id") or "")


def _node_path(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("path") or "")


def _node_kind(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("kind") or "")


def _node_data(node: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    return _as_dict(node.get("data"))


def _node_location(node: dict[str, Any]) -> str:
    path = node.get("path")
    line_range = node.get("line_range")
    if not path:
        return ""

    if isinstance(line_range, list) and len(line_range) == 2:
        return f"{path}:L{line_range[0]}-L{line_range[1]}"

    if isinstance(line_range, tuple) and len(line_range) == 2:
        return f"{path}:L{line_range[0]}-L{line_range[1]}"

    return str(path)


def _edge_evidence(edge: dict[str, Any]) -> str:
    evidence = edge.get("evidence")
    if isinstance(evidence, list) and evidence:
        return str(evidence[0])
    if isinstance(evidence, tuple) and evidence:
        return str(evidence[0])
    return ""


def _node_by_id(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_node_id(node): node for node in nodes if isinstance(node, dict) and _node_id(node)}


def _is_product_path(path: str) -> bool:
    return path.startswith("src/codebase_lens/")


def _is_low_value_path(path: str) -> bool:
    return path.startswith(("scripts/dev/", "tests/"))


def _is_cli_path(path: str) -> bool:
    return path == "src/codebase_lens/cli.py"


def _is_report_path(path: str) -> bool:
    return path.startswith("src/codebase_lens/reports/")


def _is_analyzer_path(path: str) -> bool:
    return path.startswith("src/codebase_lens/analyzers/")


def _is_report_or_analyzer_path(path: str) -> bool:
    return _is_report_path(path) or _is_analyzer_path(path)


def _source_node(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return nodes_by_id.get(str(edge.get("source") or ""))


def _target_node(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    target = edge.get("target")
    if not target:
        return None
    return nodes_by_id.get(str(target))


def _display_node(node: dict[str, Any] | None, *, fallback: str = "") -> str:
    if not isinstance(node, dict):
        return fallback or "<unresolved>"

    label = _node_label(node)
    path = _node_path(node)
    kind = _node_kind(node)

    if path and kind == "symbol":
        return f"{path}::{label}"
    if path and kind == "file":
        return path
    if path and kind in {"cli_command", "route", "test"}:
        return f"{label} @ {path}"

    return label


def _span(node: dict[str, Any]) -> int:
    line_range = node.get("line_range")
    if isinstance(line_range, list) and len(line_range) == 2:
        try:
            return max(0, int(line_range[1]) - int(line_range[0]) + 1)
        except (TypeError, ValueError):
            return 0
    if isinstance(line_range, tuple) and len(line_range) == 2:
        try:
            return max(0, int(line_range[1]) - int(line_range[0]) + 1)
        except (TypeError, ValueError):
            return 0
    return 0


def _symbol_score(node: dict[str, Any], incoming: Counter[str], outgoing: Counter[str]) -> float:
    node_id = _node_id(node)
    label = _node_label(node)
    path = _node_path(node)
    span = _span(node)
    connectivity = incoming[node_id] + outgoing[node_id]

    score = 0.0
    score += min(connectivity, 80) * 2.0
    score += min(span, 160) * 0.45

    if _is_report_or_analyzer_path(path):
        score += 55.0
    if _is_cli_path(path):
        score += 45.0
    if path.startswith("src/codebase_lens/scanners/"):
        score += 25.0
    if path.startswith("src/codebase_lens/core/"):
        score += 18.0

    if not label.startswith("_"):
        score += 40.0

    if label.startswith((
        "write_",
        "build_",
        "collect_",
        "query_",
        "render_",
        "discover_",
        "evaluate_",
        "load_",
        "map_",
    )):
        score += 45.0

    if label.startswith("_run_"):
        score += 35.0

    if label in LOW_VALUE_HELPER_NAMES:
        score -= 120.0

    if label.startswith("_") and span <= 4:
        score -= 60.0

    if _is_low_value_path(path):
        score -= 250.0

    return score


def _rank_product_symbols(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    incoming = Counter(str(edge.get("target")) for edge in edges if isinstance(edge, dict) and edge.get("target"))
    outgoing = Counter(str(edge.get("source")) for edge in edges if isinstance(edge, dict) and edge.get("source"))

    symbols = [
        node
        for node in nodes
        if isinstance(node, dict)
        and node.get("kind") == "symbol"
        and _is_product_path(_node_path(node))
    ]

    ranked = sorted(
        symbols,
        key=lambda node: (
            -_symbol_score(node, incoming, outgoing),
            _node_path(node),
            _node_label(node),
        ),
    )
    return ranked[:limit]


def _entrypoints(nodes: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    values = [
        node
        for node in nodes
        if isinstance(node, dict) and node.get("kind") in {"cli_command", "route"}
    ]
    return sorted(values, key=lambda node: (str(node.get("kind")), str(node.get("label"))))[:limit]


def _edge_family(edge: dict[str, Any], source: dict[str, Any] | None, target: dict[str, Any] | None) -> str:
    kind = str(edge.get("kind") or "")
    source_label = _node_label(source) if source else ""
    target_label = _node_label(target) if target else ""
    source_path = _node_path(source)
    target_path = _node_path(target)
    combined = " ".join([source_label, target_label, source_path, target_path]).lower()

    if "symbol_graph" in combined:
        return "symbol_graph_flow"
    if "evidence_graph" in combined:
        return "evidence_graph_flow"
    if "graph_query" in combined:
        return "graph_query_flow"
    if "snapshot" in combined or "handoff" in combined or "pack" in combined:
        return "pack_snapshot_flow"
    if kind == "file_declares_cli_command" or source_label.startswith("_run_") or source_path == "src/codebase_lens/cli.py":
        return "cli_orchestration"
    if "manifest" in combined or "write_json_report" in combined or "write_" in target_label and _is_report_path(target_path):
        return "reporting_manifest"
    if kind in {"file_imports_module", "module_resolves_to_file"}:
        return "project_imports"
    if "universe" in combined or "redaction" in combined or "paths.py" in combined:
        return "scanner_safety_flow"
    if kind == "file_contains_symbol":
        return "declaration_context"
    return "other_product_flow"


def _edge_selection_reason(edge: dict[str, Any], family: str) -> str:
    kind = str(edge.get("kind") or "")

    if family == "pack_snapshot_flow":
        return "connects pack, snapshot, or handoff orchestration"
    if family == "evidence_graph_flow":
        return "connects evidence-graph construction or reporting"
    if family == "symbol_graph_flow":
        return "connects symbol-graph construction or rendering"
    if family == "graph_query_flow":
        return "connects graph query command or report generation"
    if family == "cli_orchestration":
        return "connects public CLI command handler flow"
    if family == "reporting_manifest":
        return "connects report or manifest emission flow"
    if family == "project_imports":
        return "shows project import/module dependency"
    if family == "scanner_safety_flow":
        return "connects file-universe, path-safety, or redaction flow"
    if kind == "file_contains_symbol":
        return "fallback declaration context for a product symbol"
    return "high-scoring product dependency edge"


def _edge_relevance_score(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> float:
    kind = str(edge.get("kind") or "")
    source = _source_node(edge, nodes_by_id)
    target = _target_node(edge, nodes_by_id)
    source_path = _node_path(source)
    target_path = _node_path(target)
    source_label = _node_label(source) if source else ""
    target_label = _node_label(target) if target else str(edge.get("target_text") or "")
    family = _edge_family(edge, source, target)

    score = 0.0

    if _is_product_path(source_path):
        score += 100.0
    if _is_product_path(target_path):
        score += 100.0
    if _is_low_value_path(source_path) or _is_low_value_path(target_path):
        score -= 300.0

    if kind == "symbol_calls_symbol":
        score += 150.0
    elif kind == "file_declares_cli_command":
        score += 120.0
    elif kind == "file_imports_module":
        score += 95.0
    elif kind == "module_resolves_to_file":
        score += 80.0
    elif kind == "file_contains_symbol":
        score += 10.0

    if family in {"pack_snapshot_flow", "evidence_graph_flow", "symbol_graph_flow", "graph_query_flow"}:
        score += 100.0
    elif family == "scanner_safety_flow":
        score += 55.0
    elif family == "cli_orchestration":
        score += 45.0
    elif family == "project_imports":
        score += 35.0
    elif family == "reporting_manifest":
        score -= 20.0

    if _is_report_or_analyzer_path(source_path) or _is_report_or_analyzer_path(target_path):
        score += 45.0
    if _is_cli_path(source_path) or _is_cli_path(target_path):
        score += 35.0

    if source_label in LOW_VALUE_HELPER_NAMES or target_label in LOW_VALUE_HELPER_NAMES:
        score -= 120.0

    if source_label.startswith("_run_") or target_label.startswith("_run_"):
        score += 25.0

    if source_label.startswith(("write_", "build_", "collect_", "query_", "render_")):
        score += 35.0
    if target_label.startswith(("write_", "build_", "collect_", "query_", "render_")):
        score += 35.0

    return score


def _edge_payload(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source = _source_node(edge, nodes_by_id)
    target = _target_node(edge, nodes_by_id)
    family = _edge_family(edge, source, target)
    score = _edge_relevance_score(edge, nodes_by_id)

    return {
        "kind": edge.get("kind"),
        "source": _display_node(source, fallback=str(edge.get("source") or "")),
        "target": _display_node(target, fallback=str(edge.get("target") or edge.get("target_text") or "<unresolved>")),
        "source_path": _node_path(source),
        "target_path": _node_path(target),
        "confidence": edge.get("confidence"),
        "evidence": _edge_evidence(edge),
        "edge_family": family,
        "selection_reason": _edge_selection_reason(edge, family),
        "relevance_score": round(score, 3),
    }


def _representative_edges(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    nodes_by_id = _node_by_id(nodes)

    allowed = {
        "symbol_calls_symbol",
        "file_declares_cli_command",
        "file_imports_module",
        "module_resolves_to_file",
        "file_contains_symbol",
    }

    raw_candidates: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue

        kind = str(edge.get("kind") or "")
        if kind not in allowed:
            continue

        source = _source_node(edge, nodes_by_id)
        target = _target_node(edge, nodes_by_id)
        source_path = _node_path(source)
        target_path = _node_path(target)

        if not (_is_product_path(source_path) or _is_product_path(target_path)):
            continue

        if kind == "file_contains_symbol" and not _is_product_path(source_path):
            continue

        raw_candidates.append(edge)

    ranked = sorted(
        raw_candidates,
        key=lambda edge: (
            -_edge_relevance_score(edge, nodes_by_id),
            str(edge.get("kind") or ""),
            _edge_evidence(edge),
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
        ),
    )

    family_caps = {
        "cli_orchestration": 4,
        "reporting_manifest": 4,
        "pack_snapshot_flow": 5,
        "evidence_graph_flow": 4,
        "symbol_graph_flow": 4,
        "graph_query_flow": 4,
        "project_imports": 4,
        "scanner_safety_flow": 3,
        "declaration_context": 2,
        "other_product_flow": 3,
    }

    required_families = [
        "pack_snapshot_flow",
        "evidence_graph_flow",
        "symbol_graph_flow",
        "graph_query_flow",
    ]

    selected_edges: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str, str]] = set()
    family_counts: Counter[str] = Counter()

    def add(edge: dict[str, Any]) -> bool:
        payload = _edge_payload(edge, nodes_by_id)
        key = (
            str(payload.get("kind")),
            str(payload.get("source")),
            str(payload.get("target")),
            str(payload.get("evidence")),
        )
        if key in selected_keys:
            return False

        family = str(payload["edge_family"])
        if family_counts[family] >= family_caps.get(family, 3):
            return False

        selected_edges.append(payload)
        selected_keys.add(key)
        family_counts[family] += 1
        return True

    for family in required_families:
        for edge in ranked:
            source = _source_node(edge, nodes_by_id)
            target = _target_node(edge, nodes_by_id)
            if _edge_family(edge, source, target) == family:
                add(edge)
                break

    for edge in ranked:
        if len(selected_edges) >= limit:
            break
        add(edge)

    return selected_edges[:limit]


def _is_low_value_unresolved_call(target_text: str) -> bool:
    if not target_text:
        return True

    leaf = target_text.rsplit(".", 1)[-1]

    if target_text in BUILTIN_OR_LOW_VALUE_CALLS or leaf in BUILTIN_OR_LOW_VALUE_CALLS:
        return True

    if target_text in LOW_VALUE_HELPER_NAMES or leaf in LOW_VALUE_HELPER_NAMES:
        return True

    if any(target_text.endswith(suffix) for suffix in LOW_VALUE_ATTRIBUTE_SUFFIXES):
        return True

    return False


def _call_category(target_text: str) -> str:
    leaf = target_text.rsplit(".", 1)[-1]

    if target_text in DYNAMIC_DISPATCH_TERMS or leaf in DYNAMIC_DISPATCH_TERMS:
        return "dynamic_or_dispatch"

    if any(target_text.startswith(prefix) for prefix in EXTERNAL_LIBRARY_PREFIXES):
        return "external_library"

    if _is_low_value_unresolved_call(target_text):
        return "container_or_builtin"

    if "." in target_text:
        return "attribute_or_external"

    return "unclassified_product_call"


def _unresolved_call_score(edge: dict[str, Any], source: dict[str, Any] | None) -> float:
    source_path = _node_path(source)
    source_label = _node_label(source) if source else ""
    target_text = str(edge.get("target_text") or "")
    category = _call_category(target_text)

    score = 0.0

    if _is_product_path(source_path):
        score += 100.0
    if _is_report_or_analyzer_path(source_path):
        score += 50.0
    if _is_cli_path(source_path):
        score += 45.0
    if source_label.startswith("_run_"):
        score += 30.0
    if source_label.startswith(("write_", "build_", "collect_", "query_", "render_")):
        score += 35.0

    if category == "dynamic_or_dispatch":
        score += 130.0
    elif category == "attribute_or_external":
        score += 20.0
    elif category == "external_library":
        score -= 10.0
    elif category == "container_or_builtin":
        score -= 160.0

    if _is_low_value_path(source_path):
        score -= 300.0
    if source_label in LOW_VALUE_HELPER_NAMES:
        score -= 100.0

    return score


def _unresolved_call_payload(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source = _source_node(edge, nodes_by_id)
    target_text = str(edge.get("target_text") or "")
    category = _call_category(target_text)
    return {
        "source": _display_node(source, fallback=str(edge.get("source") or "")),
        "source_path": _node_path(source),
        "target_text": target_text,
        "call_category": category,
        "confidence": edge.get("confidence"),
        "evidence": _edge_evidence(edge),
        "relevance_score": round(_unresolved_call_score(edge, source), 3),
    }


def _unresolved_call_groups(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    nodes_by_id = _node_by_id(nodes)

    dynamic: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    attribute: list[dict[str, Any]] = []
    omitted_low_value_count = 0

    seen: set[tuple[str, str, str]] = set()

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("kind") != "symbol_calls_name":
            continue
        if edge.get("target") is not None:
            continue

        source = _source_node(edge, nodes_by_id)
        source_path = _node_path(source)
        target_text = str(edge.get("target_text") or "")

        if not _is_product_path(source_path):
            continue

        key = (str(edge.get("source") or ""), target_text, _edge_evidence(edge))
        if key in seen:
            continue
        seen.add(key)

        payload = _unresolved_call_payload(edge, nodes_by_id)
        category = str(payload["call_category"])

        if category == "container_or_builtin":
            omitted_low_value_count += 1
        elif category == "external_library":
            external.append(payload)
        elif category == "dynamic_or_dispatch":
            dynamic.append(payload)
        else:
            attribute.append(payload)

    dynamic = sorted(dynamic, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]
    external = sorted(external, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]
    attribute = sorted(attribute, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]

    return {
        "dynamic_or_dispatch_calls": dynamic,
        "external_library_calls": external,
        "attribute_or_external_calls": attribute,
        "omitted_low_value_unresolved_call_count": omitted_low_value_count,
    }


def _changed_records(layout: OutputLayout, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changed_files = _as_list(_read_json(layout.latest_dir / "changed_files.json").get("changed_files"))
    changed_symbols = _as_list(_read_json(layout.latest_dir / "changed_symbols.json").get("changed_symbols"))

    files = [item for item in changed_files if isinstance(item, dict)][:limit]
    symbols = [item for item in changed_symbols if isinstance(item, dict)][:limit]
    return files, symbols


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
    budget_report = _read_json(layout.latest_dir / "budget_report.json")
    changed_files, changed_symbols = _changed_records(layout, limit=20)

    node_kinds = Counter(str(node.get("kind")) for node in nodes)
    edge_kinds = Counter(str(edge.get("kind")) for edge in edges)
    unresolved_groups = _unresolved_call_groups(nodes, edges, limit=16)

    return {
        "schema": {
            "name": "cbl.handoff_projection",
            "version": 2,
        },
        "issue": issue,
        "scope": "changed" if changed_only else "full",
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
                    "signature": _node_data(node).get("signature"),
                }
                for node in _rank_product_symbols(nodes, edges, limit=12)
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
            "representative_edges": _representative_edges(nodes, edges, limit=20),
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


def _bullet(text: str) -> str:
    return f"- {text}"


def _render_projection_markdown(payload: dict[str, Any]) -> str:
    budget = _as_dict(payload.get("budget"))
    counts = _as_dict(payload.get("counts"))
    graph = _as_dict(payload.get("graph"))
    changed_scope = _as_dict(payload.get("changed_scope"))
    artifacts = _as_dict(payload.get("sidecar_artifacts"))

    product_symbols = _as_list(graph.get("high_connectivity_product_symbols"))
    entrypoints = _as_list(graph.get("entrypoints"))
    representative_edges = _as_list(graph.get("representative_edges"))
    dynamic_calls = _as_list(graph.get("dynamic_or_dispatch_calls"))
    external_calls = _as_list(graph.get("external_library_calls"))
    attribute_calls = _as_list(graph.get("attribute_or_external_calls"))
    omitted_low_value_count = int(graph.get("omitted_low_value_unresolved_call_count") or 0)
    changed_files = _as_list(changed_scope.get("changed_files"))
    changed_symbols = _as_list(changed_scope.get("changed_symbols"))

    lines: list[str] = [
        "# CBL Handoff Projection",
        "",
        "This sidecar is a compact graph-projection view over the CBL evidence artifacts. The legacy `ai_handoff.md` is preserved unchanged.",
        "",
        "## Purpose",
        "",
        "- Provide a lower-noise AI-facing map of the repository without embedding raw source or a full symbol graph dump.",
        "- Point the user or downstream AI toward exact follow-up CBL commands for high-resolution source retrieval.",
        "- Preserve evidence discipline: graph facts are derived from `.codecontext/latest/evidence_graph.json` and related sidecars.",
        "",
        "## Repository State",
        "",
        _bullet(f"Issue/context: `{payload.get('issue') or '(none provided)'}`"),
        _bullet(f"Scope: `{payload.get('scope')}`"),
        _bullet(f"Included files: `{counts.get('included_files', 0)}`"),
        _bullet(f"Python files analyzed: `{counts.get('python_files_analyzed', 0)}`"),
        _bullet(f"Symbols: `{counts.get('symbols', 0)}`"),
        _bullet(f"Imports: `{counts.get('imports', 0)}`"),
        _bullet(f"CLI commands: `{counts.get('commands', 0)}`"),
        _bullet(f"Test functions: `{counts.get('test_functions', 0)}`"),
        "",
        "## Budget",
        "",
        _bullet(f"Requested budget tokens: `{budget.get('requested_budget_tokens')}`"),
        _bullet(f"Budget pressure: `{budget.get('budget_pressure')}`"),
        _bullet(f"Focus terms: `{budget.get('focus_terms', [])}`"),
        _bullet(f"Estimation method: `{budget.get('estimation_method')}`"),
        "",
        "## Evidence Graph Summary",
        "",
        _bullet(f"Evidence graph nodes: `{counts.get('evidence_graph_nodes', 0)}`"),
        _bullet(f"Evidence graph edges: `{counts.get('evidence_graph_edges', 0)}`"),
        _bullet(f"Unresolved graph edges: `{counts.get('evidence_graph_unresolved_edges', 0)}`"),
        "",
        "## Entrypoints",
        "",
    ]

    if entrypoints:
        for item in entrypoints:
            if not isinstance(item, dict):
                continue
            location = item.get("location") or "no direct location"
            lines.append(_bullet(f"`{item.get('label')}` ({item.get('kind')}) → `{location}`"))
    else:
        lines.append("- No CLI command or route entrypoints were selected for this projection.")

    lines.extend(["", "## High-Connectivity Product Symbols", ""])
    if product_symbols:
        for item in product_symbols:
            if not isinstance(item, dict):
                continue
            label = item.get("display") or item.get("label")
            location = item.get("location") or "no direct location"
            signature = item.get("signature") or "signature unavailable"
            lines.append(_bullet(f"`{label}` → `{location}`"))
            lines.append(f"  - Signature: `{signature}`")
    else:
        lines.append("- No product symbols under `src/codebase_lens/` were selected.")

    lines.extend(["", "## Representative Dependency Edges", ""])
    if representative_edges:
        for item in representative_edges:
            if not isinstance(item, dict):
                continue
            evidence = f" Evidence: `{item.get('evidence')}`." if item.get("evidence") else ""
            lines.append(
                _bullet(
                    f"`{item.get('kind')}`: `{item.get('source')}` → `{item.get('target')}` "
                    f"[{item.get('confidence')}].{evidence}"
                )
            )
            lines.append(
                f"  - Family: `{item.get('edge_family')}`; reason: {item.get('selection_reason')}; "
                f"score: `{item.get('relevance_score')}`"
            )
    else:
        lines.append("- No representative product dependency edges were selected.")

    lines.extend(["", "## Dynamic / Unresolved Calls", ""])
    if dynamic_calls:
        lines.append("High-value dynamic or dispatch-like unresolved calls:")
        for item in dynamic_calls:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence} [{item.get('confidence')}]."))
    else:
        lines.append("- No high-value dynamic or dispatch-like unresolved product-code calls were selected.")

    if external_calls:
        lines.append("")
        lines.append("External/library calls summarized, not treated as architectural dispatch:")
        for item in external_calls[:8]:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence}."))

    if attribute_calls:
        lines.append("")
        lines.append(f"Attribute/external unresolved calls retained in JSON: `{len(attribute_calls)}` shown in `handoff_projection.json`.")

    if omitted_low_value_count:
        lines.append("")
        lines.append(f"Low-value builtin/container unresolved calls omitted from Markdown: `{omitted_low_value_count}`.")

    lines.extend(["", "## Changed Scope", ""])
    if changed_scope.get("empty_changed_scope"):
        lines.append("- No Git changes detected for this changed-only pack.")
        lines.append("- Changed-file and changed-symbol lists are intentionally empty.")
    else:
        lines.append(_bullet(f"Changed only: `{changed_scope.get('changed_only')}`"))
        lines.append(_bullet(f"Changed files shown: `{len(changed_files)}`"))
        lines.append(_bullet(f"Changed symbols shown: `{len(changed_symbols)}`"))

    if changed_files:
        lines.append("")
        lines.append("Changed files:")
        for item in changed_files:
            if isinstance(item, dict):
                lines.append(_bullet(f"`{item.get('path')}` [{item.get('status')}, {item.get('origin')}]"))

    if changed_symbols:
        lines.append("")
        lines.append("Changed symbols:")
        for item in changed_symbols:
            if isinstance(item, dict):
                lines.append(_bullet(f"`{item.get('qualified_name')}` → `{item.get('path')}:L{item.get('start_line')}-L{item.get('end_line')}`"))

    lines.extend(
        [
            "",
            "## Follow-Up Commands",
            "",
            "- `cbl graph --symbol <symbol> --depth 2 --budget 24000`",
            "- `cbl graph --path <path> --depth 1 --budget 24000`",
            "- `cbl symbol --name <symbol> --context 80`",
            "- `cbl file --path <path> --lines <start>:<end>`",
            "- `cbl callers --name <symbol>`",
            "- `cbl imports --module <module>`",
            "- `cbl pack --issue \"<issue>\" --budget 24000`",
            "",
            "## Sidecar Artifacts",
            "",
        ]
    )

    for key, value in sorted(artifacts.items()):
        lines.append(_bullet(f"`{key}` → `{value}`"))

    warnings = _as_list(payload.get("warnings"))
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings[:20]:
            lines.append(_bullet(str(warning)))
        if len(warnings) > 20:
            lines.append(_bullet(f"... {len(warnings) - 20} additional warnings omitted."))

    return "\n".join(lines).rstrip() + "\n"


def write_handoff_projection_reports(
    layout: OutputLayout,
    *,
    issue: str | None,
    changed_only: bool,
    budget: int,
    focus_terms: tuple[str, ...],
    counts: dict[str, int],
    warnings: tuple[str, ...],
) -> dict[str, str]:
    payload = _projection_payload(
        layout,
        issue=issue,
        changed_only=changed_only,
        budget=budget,
        focus_terms=focus_terms,
        counts=counts,
        warnings=warnings,
    )

    write_json_report(layout.latest_dir / "handoff_projection.json", payload)
    (layout.latest_dir / "handoff_projection.md").write_text(
        _render_projection_markdown(payload),
        encoding="utf-8",
        newline="\n",
    )

    return {
        "handoff_projection_json": ".codecontext/latest/handoff_projection.json",
        "handoff_projection_md": ".codecontext/latest/handoff_projection.md",
    }
'''

AUDIT = r'''
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections import Counter
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


def section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start == -1:
        fail(f"Missing section: {heading}")
    next_start = text.find("\n## ", start + len(marker))
    if next_start == -1:
        return text[start:]
    return text[start:next_start]


def main() -> int:
    for relative in [
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 15 projection semantics audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    projection_path = latest / "handoff_projection.md"
    projection_json_path = latest / "handoff_projection.json"

    if not projection_path.is_file():
        fail("handoff_projection.md was not generated.")
    if not projection_json_path.is_file():
        fail("handoff_projection.json was not generated.")

    text = projection_path.read_text(encoding="utf-8")
    payload = json.loads(projection_json_path.read_text(encoding="utf-8"))

    representative = section(text, "Representative Dependency Edges")
    unresolved = section(text, "Dynamic / Unresolved Calls")

    if "src/codebase_lens/" not in representative:
        fail("Representative edges do not surface product code.")
    if "::" not in representative:
        fail("Representative edges do not path-qualify symbol display.")
    if "scripts/dev/audits/" in representative:
        fail("Representative edges are polluted by audit helper files.")
    if "`fail`" in representative or "`run_cbl`" in representative or "`names_in_file`" in representative:
        fail("Representative edges include low-value audit helper symbols.")
    if "Family:" not in representative or "reason:" not in representative or "score:" not in representative:
        fail("Representative edges do not expose selection metadata.")

    if "scripts/dev/audits/" in unresolved:
        fail("Unresolved calls are polluted by audit helper files.")
    if "`print`" in unresolved or "`SystemExit`" in unresolved:
        fail("Unresolved calls include low-value builtins/audit exits.")

    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])
    if not isinstance(edges, list) or not edges:
        fail("handoff_projection.json has no representative edges.")

    required_edge_fields = {"edge_family", "selection_reason", "relevance_score", "source_path", "target_path"}
    for edge in edges[:10]:
        missing = required_edge_fields - set(edge)
        if missing:
            fail(f"Representative edge missing fields: {sorted(missing)}")
        blob = json.dumps(edge, sort_keys=True)
        if "scripts/dev/audits/" in blob:
            fail("handoff_projection.json representative edges include audit paths.")

    family_counts = Counter(str(edge.get("edge_family")) for edge in edges)
    if family_counts["cli_orchestration"] > 4:
        fail("Representative edges overuse cli_orchestration family.")
    if family_counts["reporting_manifest"] > 4:
        fail("Representative edges overuse reporting_manifest family.")

    if "dynamic_or_dispatch_calls" not in graph:
        fail("Projection JSON missing dynamic_or_dispatch_calls.")
    if "external_library_calls" not in graph:
        fail("Projection JSON missing external_library_calls.")
    if "attribute_or_external_calls" not in graph:
        fail("Projection JSON missing attribute_or_external_calls.")
    if "omitted_low_value_unresolved_call_count" not in graph:
        fail("Projection JSON missing omitted low-value unresolved call count.")

    if "External/library calls summarized" not in unresolved and graph.get("external_library_calls"):
        fail("Markdown does not summarize external/library calls.")

    if graph.get("omitted_low_value_unresolved_call_count", 0) < 1:
        fail("Projection did not count omitted low-value unresolved calls.")

    print("PASS: Phase 15 projection semantics audit passed.")
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
from collections import Counter
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


def test_handoff_projection_adds_semantic_edge_metadata_and_filters_low_value_calls() -> None:
    result = run_cbl("pack", "--issue", "projection semantics test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    representative_start = text.index("## Representative Dependency Edges")
    unresolved_start = text.index("## Dynamic / Unresolved Calls")
    changed_start = text.index("## Changed Scope")

    representative = text[representative_start:unresolved_start]
    unresolved = text[unresolved_start:changed_start]

    assert "src/codebase_lens/" in representative
    assert "::" in representative
    assert "Family:" in representative
    assert "reason:" in representative
    assert "score:" in representative
    assert "scripts/dev/audits/" not in representative
    assert "`fail`" not in representative
    assert "`run_cbl`" not in representative

    assert "scripts/dev/audits/" not in unresolved
    assert "`print`" not in unresolved
    assert "`SystemExit`" not in unresolved

    graph = payload["graph"]
    edges = graph["representative_edges"]
    assert edges

    for edge in edges:
        assert "edge_family" in edge
        assert "selection_reason" in edge
        assert "relevance_score" in edge
        assert "source_path" in edge
        assert "target_path" in edge

    families = Counter(edge["edge_family"] for edge in edges)
    assert families["cli_orchestration"] <= 4
    assert families["reporting_manifest"] <= 4
    assert {"pack_snapshot_flow", "evidence_graph_flow", "symbol_graph_flow", "graph_query_flow"} & set(families)

    assert "dynamic_or_dispatch_calls" in graph
    assert "external_library_calls" in graph
    assert "attribute_or_external_calls" in graph
    assert "omitted_low_value_unresolved_call_count" in graph
    assert graph["omitted_low_value_unresolved_call_count"] >= 1

    for item in graph["dynamic_or_dispatch_calls"]:
        blob = json.dumps(item, sort_keys=True)
        assert "scripts/dev/audits/" not in blob
        assert "SystemExit" not in blob
        assert "print" not in blob
'''

def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


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

    required_file = "scripts/dev/audits/audit_phase15_projection_semantics.py"
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

    write_file("src/codebase_lens/reports/handoff_projection.py", HANDOFF_PROJECTION, modified)
    write_file("scripts/dev/audits/audit_phase15_projection_semantics.py", AUDIT, modified)
    write_file("tests/test_handoff_projection_semantics.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 015C applied: handoff projection semantics cleaned up.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())