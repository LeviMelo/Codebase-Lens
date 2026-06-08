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


def _node_by_id(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_node_id(node): node for node in nodes if isinstance(node, dict) and _node_id(node)}


def _node_labels(nodes: list[dict[str, Any]]) -> dict[str, str]:
    return {_node_id(node): _node_label(node) for node in nodes if isinstance(node, dict) and _node_id(node)}


def _is_product_path(path: str) -> bool:
    return path.startswith("src/codebase_lens/")


def _is_low_value_path(path: str) -> bool:
    return path.startswith(("scripts/dev/", "tests/"))


def _is_cli_path(path: str) -> bool:
    return path == "src/codebase_lens/cli.py"


def _is_report_or_analyzer_path(path: str) -> bool:
    return path.startswith(("src/codebase_lens/reports/", "src/codebase_lens/analyzers/"))


def _source_node(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return nodes_by_id.get(str(edge.get("source") or ""))


def _target_node(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    target = edge.get("target")
    if not target:
        return None
    return nodes_by_id.get(str(target))


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


def _edge_relevance_score(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> float:
    kind = str(edge.get("kind") or "")
    source = _source_node(edge, nodes_by_id)
    target = _target_node(edge, nodes_by_id)
    source_path = _node_path(source)
    target_path = _node_path(target)
    source_label = _node_label(source) if source else ""
    target_label = _node_label(target) if target else str(edge.get("target_text") or "")

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


def _representative_edges(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    labels = _node_labels(nodes)
    nodes_by_id = _node_by_id(nodes)

    candidates: list[dict[str, Any]] = []
    allowed = {
        "symbol_calls_symbol",
        "file_declares_cli_command",
        "file_imports_module",
        "module_resolves_to_file",
        "file_contains_symbol",
    }

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

        # file_contains_symbol is useful only as fallback and only for product files.
        if kind == "file_contains_symbol" and not _is_product_path(source_path):
            continue

        candidates.append(edge)

    ranked = sorted(
        candidates,
        key=lambda edge: (
            -_edge_relevance_score(edge, nodes_by_id),
            str(edge.get("kind") or ""),
            _edge_evidence(edge),
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
        ),
    )

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for edge in ranked:
        source = labels.get(str(edge.get("source")), str(edge.get("source")))
        target = labels.get(str(edge.get("target")), str(edge.get("target") or edge.get("target_text") or "<unresolved>"))
        key = (str(edge.get("kind")), source, target, _edge_evidence(edge))
        if key in seen:
            continue
        seen.add(key)
        selected.append(
            {
                "kind": edge.get("kind"),
                "source": source,
                "target": target,
                "confidence": edge.get("confidence"),
                "evidence": _edge_evidence(edge),
            }
        )
        if len(selected) >= limit:
            break

    return selected


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


def _unresolved_call_score(edge: dict[str, Any], source: dict[str, Any] | None) -> float:
    source_path = _node_path(source)
    source_label = _node_label(source) if source else ""
    target_text = str(edge.get("target_text") or "")

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
    if "." in target_text:
        score += 12.0
    if _is_low_value_path(source_path):
        score -= 300.0
    if source_label in LOW_VALUE_HELPER_NAMES:
        score -= 100.0

    return score


def _unresolved_calls(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    labels = _node_labels(nodes)
    nodes_by_id = _node_by_id(nodes)
    candidates: list[dict[str, Any]] = []

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
        if _is_low_value_unresolved_call(target_text):
            continue

        candidates.append(edge)

    ranked = sorted(
        candidates,
        key=lambda edge: (
            -_unresolved_call_score(edge, _source_node(edge, nodes_by_id)),
            _edge_evidence(edge),
            str(edge.get("target_text") or ""),
        ),
    )

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for edge in ranked:
        source_id = str(edge.get("source") or "")
        target_text = str(edge.get("target_text") or "")
        key = (source_id, target_text, _edge_evidence(edge))
        if key in seen:
            continue
        seen.add(key)
        selected.append(
            {
                "source": labels.get(source_id, source_id),
                "target_text": target_text,
                "confidence": edge.get("confidence"),
                "evidence": _edge_evidence(edge),
            }
        )
        if len(selected) >= limit:
            break

    return selected


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

    return {
        "schema": {
            "name": "cbl.handoff_projection",
            "version": 1,
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
                    "signature": _node_data(node).get("signature"),
                }
                for node in _rank_product_symbols(nodes, edges, limit=12)
            ],
            "entrypoints": [
                {
                    "label": node.get("label"),
                    "kind": node.get("kind"),
                    "location": _node_location(node),
                    "data": _node_data(node),
                }
                for node in _entrypoints(nodes, limit=18)
            ],
            "representative_edges": _representative_edges(nodes, edges, limit=20),
            "unresolved_static_calls": _unresolved_calls(nodes, edges, limit=20),
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
    unresolved_calls = _as_list(graph.get("unresolved_static_calls"))
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
            label = item.get("label")
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
    else:
        lines.append("- No representative product dependency edges were selected.")

    lines.extend(["", "## Dynamic / Unresolved Calls", ""])
    if unresolved_calls:
        for item in unresolved_calls:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence} [{item.get('confidence')}]."))
    else:
        lines.append("- No relevant unresolved product-code call-name edges were selected.")

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
