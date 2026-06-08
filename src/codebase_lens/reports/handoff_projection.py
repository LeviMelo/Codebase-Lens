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
    "handler",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "globals",
    "locals",
    "__import__",
    "import_module",
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

REPORTING_NAME_TERMS = {
    "report",
    "render",
    "write",
    "markdown",
    "json",
    "manifest",
    "serializer",
    "serialize",
    "output",
    "emit",
}

ANALYSIS_NAME_TERMS = {
    "analyze",
    "analysis",
    "collect",
    "extract",
    "parse",
    "parser",
    "scan",
    "scanner",
    "query",
    "graph",
    "index",
    "inventory",
    "map",
    "resolve",
}

CORE_NAME_TERMS = {
    "model",
    "schema",
    "contract",
    "config",
    "constant",
    "domain",
    "entity",
    "types",
}

IO_NAME_TERMS = {
    "file",
    "path",
    "git",
    "diff",
    "status",
    "ignore",
    "hash",
    "redact",
    "safety",
    "textio",
    "cleanup",
}


@dataclass(frozen=True)
class ProjectProfile:
    source_prefixes: tuple[str, ...]
    cli_paths: tuple[str, ...]


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


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.replace("\\", "/").split("/") if part)


def _is_test_path(path: str) -> bool:
    parts = _path_parts(path)
    name = parts[-1] if parts else ""
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


def _is_script_or_tooling_path(path: str) -> bool:
    parts = _path_parts(path)
    return bool(parts and parts[0] in {"scripts", "tools", "devtools", "bin"})


def _is_low_value_path(path: str) -> bool:
    return _is_test_path(path) or _is_script_or_tooling_path(path)


def _infer_source_prefixes(nodes: list[dict[str, Any]]) -> tuple[str, ...]:
    candidate_counts: Counter[str] = Counter()

    for node in nodes:
        if not isinstance(node, dict):
            continue
        path = _node_path(node)
        if not path or not path.endswith(".py"):
            continue
        if _is_low_value_path(path):
            continue

        parts = _path_parts(path)
        if len(parts) >= 3 and parts[0] == "src":
            candidate_counts[f"src/{parts[1]}/"] += 1
        elif len(parts) >= 2:
            candidate_counts[f"{parts[0]}/"] += 1
        elif len(parts) == 1:
            candidate_counts[parts[0]] += 1

    if not candidate_counts:
        return ()

    max_count = max(candidate_counts.values())
    selected = [
        prefix
        for prefix, count in candidate_counts.items()
        if count >= 2 or count == max_count
    ]
    return tuple(sorted(selected, key=lambda item: (-candidate_counts[item], item))[:8])


def _infer_project_profile(nodes: list[dict[str, Any]]) -> ProjectProfile:
    prefixes = _infer_source_prefixes(nodes)
    cli_paths = sorted(
        {
            _node_path(node)
            for node in nodes
            if isinstance(node, dict)
            and node.get("kind") == "cli_command"
            and _node_path(node)
        }
    )
    return ProjectProfile(source_prefixes=prefixes, cli_paths=tuple(cli_paths))


def _is_product_path(path: str, profile: ProjectProfile) -> bool:
    if not path:
        return False
    if _is_low_value_path(path):
        return False
    if not profile.source_prefixes:
        return path.endswith(".py")
    return any(path.startswith(prefix) for prefix in profile.source_prefixes)


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


def _contains_any(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _path_role(path: str, profile: ProjectProfile) -> str:
    if not path:
        return "unknown"
    if _is_test_path(path):
        return "tests"
    if _is_script_or_tooling_path(path):
        return "scripts"
    if path in profile.cli_paths:
        return "cli_surface"

    blob = path.lower()
    if _contains_any(blob, REPORTING_NAME_TERMS):
        return "reporting"
    if _contains_any(blob, ANALYSIS_NAME_TERMS):
        return "analysis"
    if _contains_any(blob, CORE_NAME_TERMS):
        return "model_or_core"
    if _contains_any(blob, IO_NAME_TERMS):
        return "io_or_safety"
    return "product"


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


def _symbol_score(
    node: dict[str, Any],
    incoming: Counter[str],
    outgoing: Counter[str],
    profile: ProjectProfile,
    focus_terms: tuple[str, ...] = (),
) -> float:
    node_id = _node_id(node)
    label = _node_label(node)
    path = _node_path(node)
    span = _span(node)
    connectivity = incoming[node_id] + outgoing[node_id]
    role = _symbol_role(node, profile)

    score = 0.0
    score += min(connectivity, 80) * 2.0
    score += min(span, 160) * 0.45

    if role == "analysis":
        score += 55.0
    elif role == "reporting":
        score += 50.0
    elif role == "cli_surface":
        score += 45.0
    elif role == "io_or_safety":
        score += 30.0
    elif role == "model_or_core":
        score += 25.0

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
        "parse_",
        "scan_",
        "analyze_",
    )):
        score += 45.0

    if label in LOW_VALUE_HELPER_NAMES:
        score -= 120.0

    if label.startswith("_") and span <= 4:
        score -= 60.0

    if _is_low_value_path(path):
        score -= 250.0

    focus_blob = " ".join(focus_terms).lower()
    self_projection_blob = f"{path} {label}".lower()
    focus_mentions_projection = any(term in focus_blob for term in {"handoff", "projection", "pack"})
    if "handoff" in self_projection_blob and "projection" in self_projection_blob and not focus_mentions_projection:
        score -= 90.0

    return score


def _rank_product_symbols(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    profile: ProjectProfile,
    *,
    limit: int,
    focus_terms: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    incoming = Counter(str(edge.get("target")) for edge in edges if isinstance(edge, dict) and edge.get("target"))
    outgoing = Counter(str(edge.get("source")) for edge in edges if isinstance(edge, dict) and edge.get("source"))

    symbols = [
        node
        for node in nodes
        if isinstance(node, dict)
        and node.get("kind") == "symbol"
        and _is_product_path(_node_path(node), profile)
    ]

    ranked = sorted(
        symbols,
        key=lambda node: (
            -_symbol_score(node, incoming, outgoing, profile, focus_terms=focus_terms),
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


def _representative_edge_key(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(payload.get("kind") or ""),
        str(payload.get("source") or ""),
        str(payload.get("target") or ""),
        str(payload.get("edge_family") or ""),
    )


def _collapse_representative_edge_candidates(
    ranked_edges: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    profile: ProjectProfile,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for edge in ranked_edges:
        payload = _edge_payload(edge, nodes_by_id, profile)
        key = _representative_edge_key(payload)
        evidence = str(payload.get("evidence") or "")
        score = float(payload.get("relevance_score") or 0.0)

        if key not in groups:
            groups[key] = {
                "payload": payload,
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
            group["payload"] = payload
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

    if leaf in {"getattr", "hasattr", "setattr", "delattr"}:
        return "reflective_attribute_read"

    if target_text in DYNAMIC_DISPATCH_TERMS or leaf in DYNAMIC_DISPATCH_TERMS:
        return "dynamic_or_dispatch"

    if any(target_text.startswith(prefix) for prefix in EXTERNAL_LIBRARY_PREFIXES):
        return "external_library"

    if _is_low_value_unresolved_call(target_text):
        return "container_or_builtin"

    if "." in target_text:
        return "attribute_or_external"

    return "unclassified_product_call"


def _unresolved_call_score(edge: dict[str, Any], source: dict[str, Any] | None, profile: ProjectProfile) -> float:
    source_path = _node_path(source)
    source_label = _node_label(source) if source else ""
    target_text = str(edge.get("target_text") or "")
    category = _call_category(target_text)
    source_role = _symbol_role(source, profile) if isinstance(source, dict) else "unknown"

    score = 0.0

    if _is_product_path(source_path, profile):
        score += 100.0
    if source_role == "analysis":
        score += 50.0
    if source_role == "reporting":
        score += 45.0
    if source_role == "cli_surface":
        score += 45.0
    if source_label.startswith(("write_", "build_", "collect_", "query_", "render_", "parse_", "scan_", "analyze_")):
        score += 35.0

    if category == "dynamic_or_dispatch":
        score += 130.0
    elif category == "reflective_attribute_read":
        score += 10.0
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


def _unresolved_call_payload(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]], profile: ProjectProfile) -> dict[str, Any]:
    source = _source_node(edge, nodes_by_id)
    target_text = str(edge.get("target_text") or "")
    category = _call_category(target_text)
    return {
        "source": _display_node(source, fallback=str(edge.get("source") or "")),
        "source_path": _node_path(source),
        "source_role": _symbol_role(source, profile) if isinstance(source, dict) else "unknown",
        "target_text": target_text,
        "call_category": category,
        "confidence": edge.get("confidence"),
        "evidence": _edge_evidence(edge),
        "relevance_score": round(_unresolved_call_score(edge, source, profile), 3),
    }


def _unresolved_call_groups(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], profile: ProjectProfile, *, limit: int) -> dict[str, Any]:
    nodes_by_id = _node_by_id(nodes)

    actual_dispatch: list[dict[str, Any]] = []
    reflective: list[dict[str, Any]] = []
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

        if not _is_product_path(source_path, profile):
            continue

        key = (str(edge.get("source") or ""), target_text, _edge_evidence(edge))
        if key in seen:
            continue
        seen.add(key)

        payload = _unresolved_call_payload(edge, nodes_by_id, profile)
        category = str(payload["call_category"])

        if category == "container_or_builtin":
            omitted_low_value_count += 1
        elif category == "external_library":
            external.append(payload)
        elif category == "dynamic_or_dispatch":
            actual_dispatch.append(payload)
        elif category == "reflective_attribute_read":
            reflective.append(payload)
        else:
            attribute.append(payload)

    actual_dispatch = sorted(actual_dispatch, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]
    external = sorted(external, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]
    attribute = sorted(attribute, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]

    reflective_ranked = sorted(reflective, key=lambda item: (-float(item["relevance_score"]), str(item.get("source_path")), str(item.get("evidence"))))
    reflective_selected: list[dict[str, Any]] = []
    reflective_target_counts: Counter[str] = Counter()
    omitted_repetitive_reflection_count = 0

    for item in reflective_ranked:
        target = str(item.get("target_text") or "")
        if len(reflective_selected) >= 3 or reflective_target_counts[target] >= 2:
            omitted_repetitive_reflection_count += 1
            continue
        reflective_selected.append(item)
        reflective_target_counts[target] += 1

    return {
        "dynamic_or_dispatch_calls": actual_dispatch,
        "actual_dispatch_calls": actual_dispatch,
        "reflective_attribute_reads": reflective_selected,
        "external_library_calls": external,
        "attribute_or_external_calls": attribute,
        "omitted_low_value_unresolved_call_count": omitted_low_value_count,
        "omitted_repetitive_reflection_count": omitted_repetitive_reflection_count,
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


def _bullet(text: str) -> str:
    return f"- {text}"


def _render_projection_markdown(payload: dict[str, Any]) -> str:
    budget = _as_dict(payload.get("budget"))
    counts = _as_dict(payload.get("counts"))
    graph = _as_dict(payload.get("graph"))
    changed_scope = _as_dict(payload.get("changed_scope"))
    artifacts = _as_dict(payload.get("sidecar_artifacts"))
    project_profile = _as_dict(payload.get("project_profile"))

    product_symbols = _as_list(graph.get("high_connectivity_product_symbols"))
    entrypoints = _as_list(graph.get("entrypoints"))
    representative_edges = _as_list(graph.get("representative_edges"))
    actual_dispatch_calls = _as_list(graph.get("actual_dispatch_calls") or graph.get("dynamic_or_dispatch_calls"))
    reflective_reads = _as_list(graph.get("reflective_attribute_reads"))
    external_calls = _as_list(graph.get("external_library_calls"))
    attribute_calls = _as_list(graph.get("attribute_or_external_calls"))
    omitted_low_value_count = int(graph.get("omitted_low_value_unresolved_call_count") or 0)
    omitted_reflection_count = int(graph.get("omitted_repetitive_reflection_count") or 0)
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
        "## Project Profile",
        "",
        _bullet(f"Inferred source prefixes: `{project_profile.get('source_prefixes', [])}`"),
        _bullet(f"CLI paths: `{project_profile.get('cli_paths', [])}`"),
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
            role = item.get("role") or "unknown"
            lines.append(_bullet(f"`{label}` → `{location}`"))
            lines.append(f"  - Role: `{role}`")
            lines.append(f"  - Signature: `{signature}`")
    else:
        lines.append("- No product symbols were selected.")

    lines.extend(["", "## Representative Dependency Edges", ""])
    if representative_edges:
        for item in representative_edges:
            if not isinstance(item, dict):
                continue
            sample_evidence = _as_list(item.get("sample_evidence"))
            evidence = sample_evidence[0] if sample_evidence else item.get("evidence")
            evidence_count = int(item.get("evidence_count") or (1 if evidence else 0))
            evidence_text = f" Evidence: `{evidence}`." if evidence else ""
            lines.append(
                _bullet(
                    f"`{item.get('kind')}`: `{item.get('source')}` → `{item.get('target')}` "
                    f"[{item.get('confidence')}].{evidence_text}"
                )
            )
            lines.append(
                f"  - Family: `{item.get('edge_family')}`; reason: {item.get('selection_reason')}; "
                f"score: `{item.get('relevance_score')}`; roles: `{item.get('source_role')}` → `{item.get('target_role')}`"
            )
            if evidence_count > 1:
                shown = ", ".join(f"`{value}`" for value in sample_evidence[:3])
                lines.append(f"  - Evidence count: `{evidence_count}`; sample evidence: {shown}")
    else:
        lines.append("- No representative product dependency edges were selected.")

    lines.extend(["", "## Dynamic / Unresolved Calls", ""])
    if actual_dispatch_calls:
        lines.append("Actual dispatch-like unresolved calls:")
        for item in actual_dispatch_calls:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence} [{item.get('confidence')}]."))
    else:
        lines.append("- No actual dynamic dispatch-like unresolved product-code calls were selected.")

    if reflective_reads:
        lines.append("")
        lines.append("Reflective attribute reads, capped as lower-value dynamic evidence:")
        for item in reflective_reads:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence}."))

    if omitted_reflection_count:
        lines.append("")
        lines.append(f"Repetitive reflective reads omitted from Markdown: `{omitted_reflection_count}`.")

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
