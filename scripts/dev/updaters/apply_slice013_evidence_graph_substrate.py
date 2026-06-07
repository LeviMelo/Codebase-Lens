from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/core/graph.py": r'''
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    label: str
    path: str | None
    line_range: tuple[int, int] | None
    data: dict[str, Any]


@dataclass(frozen=True)
class GraphEdge:
    id: str
    kind: str
    source: str
    target: str | None
    target_text: str | None
    evidence: tuple[str, ...]
    confidence: str
    data: dict[str, Any]


@dataclass(frozen=True)
class EvidenceGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    counts: dict[str, int]
    warnings: tuple[str, ...]


def jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


def stable_id(prefix: str, *parts: object) -> str:
    text = "\x1f".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def file_node_id(path: str) -> str:
    return f"file:{path}"


def module_node_id(module: str) -> str:
    return f"module:{module}"


def symbol_node_id(symbol_id: str) -> str:
    return f"symbol:{symbol_id}"


def cli_node_id(command_path: str, path: str | None = None, line: int | None = None) -> str:
    return stable_id("cli", command_path, path, line)


def test_node_id(path: str, name: str, line: int | None = None) -> str:
    return stable_id("test", path, name, line)


def changed_hunk_node_id(path: str, start: int, end: int, origin: str) -> str:
    return stable_id("hunk", path, start, end, origin)


def make_edge(
    *,
    kind: str,
    source: str,
    target: str | None = None,
    target_text: str | None = None,
    evidence: tuple[str, ...] = (),
    confidence: str,
    data: dict[str, Any] | None = None,
) -> GraphEdge:
    return GraphEdge(
        id=stable_id("edge", kind, source, target, target_text, "|".join(evidence), confidence),
        kind=kind,
        source=source,
        target=target,
        target_text=target_text,
        evidence=tuple(evidence),
        confidence=confidence,
        data=data or {},
    )


def dedupe_nodes(nodes: list[GraphNode]) -> tuple[GraphNode, ...]:
    by_id: dict[str, GraphNode] = {}
    for node in nodes:
        by_id[node.id] = node
    return tuple(sorted(by_id.values(), key=lambda item: (item.kind, item.id)))


def dedupe_edges(edges: list[GraphEdge]) -> tuple[GraphEdge, ...]:
    by_id: dict[str, GraphEdge] = {}
    for edge in edges:
        by_id[edge.id] = edge
    return tuple(sorted(by_id.values(), key=lambda item: (item.kind, item.source, item.target or "", item.target_text or "", item.id)))


def graph_counts(nodes: tuple[GraphNode, ...], edges: tuple[GraphEdge, ...]) -> dict[str, int]:
    counts: dict[str, int] = {
        "nodes": len(nodes),
        "edges": len(edges),
    }

    for node in nodes:
        key = f"node_{node.kind}"
        counts[key] = counts.get(key, 0) + 1

    for edge in edges:
        key = f"edge_{edge.kind}"
        counts[key] = counts.get(key, 0) + 1

    counts["exact_edges"] = sum(1 for edge in edges if edge.confidence.startswith("exact"))
    counts["heuristic_edges"] = sum(1 for edge in edges if "heuristic" in edge.confidence)
    counts["unresolved_edges"] = sum(1 for edge in edges if edge.target is None)

    return counts


def evidence_graph_payload(graph: EvidenceGraph) -> dict[str, Any]:
    return {
        "schema": {
            "name": "cbl.evidence_graph",
            "version": 1,
        },
        "nodes": [jsonable(node) for node in graph.nodes],
        "edges": [jsonable(edge) for edge in graph.edges],
        "counts": dict(graph.counts),
        "warnings": list(graph.warnings),
    }


def graph_slice_payload(graph: EvidenceGraph, *, edge_kinds: set[str]) -> dict[str, Any]:
    edges = [edge for edge in graph.edges if edge.kind in edge_kinds]
    node_ids: set[str] = set()
    for edge in edges:
        node_ids.add(edge.source)
        if edge.target is not None:
            node_ids.add(edge.target)

    nodes = [node for node in graph.nodes if node.id in node_ids]
    return {
        "schema": {
            "name": "cbl.evidence_graph_slice",
            "version": 1,
        },
        "edge_kinds": sorted(edge_kinds),
        "nodes": [jsonable(node) for node in nodes],
        "edges": [jsonable(edge) for edge in edges],
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
        },
    }
''',

    "src/codebase_lens/analyzers/evidence_graph.py": r'''
from __future__ import annotations

from pathlib import Path
from typing import Any

from codebase_lens.core.graph import (
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    changed_hunk_node_id,
    cli_node_id,
    dedupe_edges,
    dedupe_nodes,
    file_node_id,
    graph_counts,
    make_edge,
    module_node_id,
    symbol_node_id,
    test_node_id,
)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def _path(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\\", "/")
    return text or None


def _line_range(start: Any, end: Any) -> tuple[int, int] | None:
    try:
        start_i = int(start)
        end_i = int(end)
    except (TypeError, ValueError):
        return None
    if start_i <= 0 or end_i < start_i:
        return None
    return (start_i, end_i)


def _evidence(path: str | None, start: Any = None, end: Any = None) -> tuple[str, ...]:
    if not path:
        return ()
    rng = _line_range(start, end)
    if rng is None:
        return (path,)
    return (f"{path}:L{rng[0]}-L{rng[1]}",)


def _module_from_path(path: str) -> str | None:
    candidate = Path(path).with_suffix("")
    parts = [part for part in candidate.parts if part not in {"."}]
    if not parts:
        return None
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if not parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def _import_target_text(record: Any) -> str:
    module = _get(record, "module")
    name = _get(record, "name")
    if module and name:
        return f"{module}.{name}"
    if module:
        return str(module)
    if name:
        return str(name)
    return "<unknown import>"


def _command_label(record: Any) -> str:
    for attr in ("command_path", "name", "command"):
        value = _get(record, attr)
        if value:
            return str(value)
    return "<unknown command>"


def _test_names(record: Any) -> list[str]:
    values: list[str] = []
    for attr in ("test_functions", "test_classes"):
        item = _get(record, attr, ())
        if isinstance(item, (list, tuple)):
            values.extend(str(value) for value in item)
    return values


def build_evidence_graph(
    repo_root: str | Path,
    *,
    universe: Any,
    symbol_graph: Any,
    import_records: list[Any],
    command_records: list[Any],
    route_records: list[Any],
    test_inventory: Any,
    changed_files: tuple[Any, ...] = (),
    changed_symbols: tuple[Any, ...] = (),
) -> EvidenceGraph:
    root = Path(repo_root).resolve()
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    warnings: list[str] = []

    repo_id = "repo:current"
    nodes.append(
        GraphNode(
            id=repo_id,
            kind="repository",
            label=root.name,
            path=None,
            line_range=None,
            data={
                "name": root.name,
            },
        )
    )

    file_paths: set[str] = set()
    for record in _get(universe, "included_files", ()):
        path = _path(_get(record, "path"))
        if not path:
            continue
        file_paths.add(path)
        node_id = file_node_id(path)
        nodes.append(
            GraphNode(
                id=node_id,
                kind="file",
                label=path,
                path=path,
                line_range=None,
                data={
                    "size_bytes": _get(record, "size_bytes"),
                    "sha256": _get(record, "sha256"),
                    "git_status": _get(record, "git_status"),
                    "is_tracked": _get(record, "is_tracked"),
                    "is_untracked": _get(record, "is_untracked"),
                },
            )
        )
        edges.append(
            make_edge(
                kind="repository_contains_file",
                source=repo_id,
                target=node_id,
                evidence=(path,),
                confidence="exact_file_universe",
            )
        )

        module = _module_from_path(path) if path.endswith(".py") else None
        if module:
            module_id = module_node_id(module)
            nodes.append(
                GraphNode(
                    id=module_id,
                    kind="module",
                    label=module,
                    path=path,
                    line_range=None,
                    data={
                        "module": module,
                    },
                )
            )
            edges.append(
                make_edge(
                    kind="file_defines_module",
                    source=node_id,
                    target=module_id,
                    evidence=(path,),
                    confidence="heuristic_module_path",
                )
            )

    symbol_lookup: dict[tuple[str, str], str] = {}
    symbol_by_id: dict[str, Any] = {}

    for symbol in _get(symbol_graph, "nodes", ()):
        path = _path(_get(symbol, "path"))
        qualified_name = str(_get(symbol, "qualified_name", ""))
        simple_name = str(_get(symbol, "simple_name", qualified_name))
        raw_symbol_id = str(_get(symbol, "symbol_id", ""))
        if not path or not qualified_name or not raw_symbol_id:
            continue

        node_id = symbol_node_id(raw_symbol_id)
        symbol_lookup[(path, qualified_name)] = node_id
        symbol_lookup[(path, simple_name)] = node_id
        symbol_by_id[node_id] = symbol

        nodes.append(
            GraphNode(
                id=node_id,
                kind="symbol",
                label=qualified_name,
                path=path,
                line_range=_line_range(_get(symbol, "start_line"), _get(symbol, "end_line")),
                data={
                    "qualified_name": qualified_name,
                    "simple_name": simple_name,
                    "symbol_kind": _get(symbol, "kind"),
                    "signature": _get(symbol, "signature"),
                    "inputs": _get(symbol, "inputs", ()),
                    "returns_annotation": _get(symbol, "returns_annotation"),
                    "observed_returns": _get(symbol, "observed_returns", ()),
                    "imports_used": _get(symbol, "imports_used", ()),
                    "tests_likely_covering": _get(symbol, "tests_likely_covering", ()),
                    "confidence": _get(symbol, "confidence"),
                },
            )
        )

        if path in file_paths:
            edges.append(
                make_edge(
                    kind="file_contains_symbol",
                    source=file_node_id(path),
                    target=node_id,
                    evidence=_evidence(path, _get(symbol, "start_line"), _get(symbol, "end_line")),
                    confidence="exact_ast_declaration",
                )
            )

    for symbol in _get(symbol_graph, "nodes", ()):
        source_path = _path(_get(symbol, "path"))
        source_name = str(_get(symbol, "qualified_name", ""))
        source_raw_id = str(_get(symbol, "symbol_id", ""))
        if not source_path or not source_raw_id:
            continue
        source_id = symbol_node_id(source_raw_id)

        for call in _get(symbol, "calls", ()):
            call_name = str(_get(call, "name", ""))
            line = _get(call, "line")
            if not call_name:
                continue

            edges.append(
                make_edge(
                    kind="symbol_calls_name",
                    source=source_id,
                    target=None,
                    target_text=call_name,
                    evidence=_evidence(source_path, line, line),
                    confidence="exact_ast_call_expression",
                    data={
                        "line": line,
                        "source_symbol": source_name,
                    },
                )
            )

        for caller in _get(symbol, "called_by", ()):
            caller_path = _path(_get(caller, "path"))
            caller_symbol = str(_get(caller, "symbol", ""))
            caller_line = _get(caller, "line")
            if not caller_path or not caller_symbol:
                continue

            caller_id = symbol_lookup.get((caller_path, caller_symbol))
            if caller_id is None:
                continue

            edges.append(
                make_edge(
                    kind="symbol_calls_symbol",
                    source=caller_id,
                    target=source_id,
                    evidence=_evidence(caller_path, caller_line, caller_line),
                    confidence=f"heuristic_{_get(caller, 'confidence', 'resolved_call')}",
                    data={
                        "caller_symbol": caller_symbol,
                        "target_symbol": source_name,
                    },
                )
            )

    for record in import_records:
        source_path = _path(_get(record, "path"))
        if not source_path:
            continue

        target_text = _import_target_text(record)
        module_name = str(_get(record, "module", "") or target_text)
        line = _get(record, "line")
        source_file_id = file_node_id(source_path)
        target_module_id = module_node_id(module_name)

        nodes.append(
            GraphNode(
                id=target_module_id,
                kind="module",
                label=module_name,
                path=None,
                line_range=None,
                data={
                    "module": module_name,
                },
            )
        )

        edges.append(
            make_edge(
                kind="file_imports_module",
                source=source_file_id,
                target=target_module_id,
                target_text=target_text,
                evidence=_evidence(source_path, line, line),
                confidence="exact_import_statement",
                data={
                    "module": _get(record, "module"),
                    "name": _get(record, "name"),
                    "alias": _get(record, "alias"),
                    "level": _get(record, "level"),
                    "resolved_path": _get(record, "resolved_path"),
                },
            )
        )

        resolved_path = _path(_get(record, "resolved_path"))
        if resolved_path:
            edges.append(
                make_edge(
                    kind="module_resolves_to_file",
                    source=target_module_id,
                    target=file_node_id(resolved_path),
                    evidence=_evidence(source_path, line, line),
                    confidence="heuristic_project_import_resolution",
                    data={
                        "import_text": target_text,
                    },
                )
            )

    for record in command_records:
        path = _path(_get(record, "path"))
        line = _get(record, "start_line", _get(record, "line"))
        label = _command_label(record)
        node_id = cli_node_id(label, path, line)

        nodes.append(
            GraphNode(
                id=node_id,
                kind="cli_command",
                label=label,
                path=path,
                line_range=_line_range(line, line),
                data={
                    "framework": _get(record, "framework"),
                    "command_path": label,
                    "function_name": _get(record, "function_name"),
                    "handler": _get(record, "handler"),
                },
            )
        )

        if path:
            edges.append(
                make_edge(
                    kind="file_declares_cli_command",
                    source=file_node_id(path),
                    target=node_id,
                    evidence=_evidence(path, line, line),
                    confidence="heuristic_static_cli_analysis",
                )
            )

    for record in route_records:
        path = _path(_get(record, "path"))
        route_path = _get(record, "route_path")
        method = _get(record, "method")
        function_name = _get(record, "function_name")
        if not path or not route_path:
            continue
        route_id = f"route:{path}:{method}:{route_path}:{function_name}"

        nodes.append(
            GraphNode(
                id=route_id,
                kind="route",
                label=f"{method or '?'} {route_path}",
                path=path,
                line_range=_line_range(_get(record, "start_line"), _get(record, "end_line", _get(record, "start_line"))),
                data={
                    "method": method,
                    "route_path": route_path,
                    "function_name": function_name,
                    "framework": _get(record, "framework"),
                },
            )
        )

        edges.append(
            make_edge(
                kind="file_declares_route",
                source=file_node_id(path),
                target=route_id,
                evidence=_evidence(path, _get(record, "start_line"), _get(record, "start_line")),
                confidence="heuristic_static_route_analysis",
            )
        )

    for test_record in _get(test_inventory, "tests", ()):
        path = _path(_get(test_record, "path"))
        if not path:
            continue

        for name in _test_names(test_record):
            node_id = test_node_id(path, name)
            nodes.append(
                GraphNode(
                    id=node_id,
                    kind="test",
                    label=name,
                    path=path,
                    line_range=None,
                    data={
                        "test_name": name,
                        "likely_targets": _get(test_record, "likely_targets", ()),
                    },
                )
            )
            edges.append(
                make_edge(
                    kind="file_contains_test",
                    source=file_node_id(path),
                    target=node_id,
                    evidence=(path,),
                    confidence="heuristic_test_inventory",
                )
            )

            for target in _get(test_record, "likely_targets", ()):
                edges.append(
                    make_edge(
                        kind="test_likely_targets_text",
                        source=node_id,
                        target=None,
                        target_text=str(target),
                        evidence=(path,),
                        confidence="heuristic_test_name_or_import",
                    )
                )

    for changed in changed_files:
        path = _path(_get(changed, "path"))
        if not path:
            continue

        for hunk in _get(changed, "hunks", ()):
            start = int(_get(hunk, "new_start", _get(hunk, "old_start", 0)) or 0)
            length = int(_get(hunk, "new_lines", _get(hunk, "old_lines", 1)) or 1)
            end = max(start, start + max(length, 1) - 1)
            origin = str(_get(changed, "origin", "git"))
            hunk_id = changed_hunk_node_id(path, start, end, origin)

            nodes.append(
                GraphNode(
                    id=hunk_id,
                    kind="changed_hunk",
                    label=f"{path}:L{start}-L{end}",
                    path=path,
                    line_range=(start, end),
                    data={
                        "status": _get(changed, "status"),
                        "origin": origin,
                        "additions": _get(changed, "additions"),
                        "deletions": _get(changed, "deletions"),
                    },
                )
            )
            edges.append(
                make_edge(
                    kind="file_has_changed_hunk",
                    source=file_node_id(path),
                    target=hunk_id,
                    evidence=_evidence(path, start, end),
                    confidence="exact_git_diff_hunk",
                )
            )

    for changed_symbol in changed_symbols:
        path = _path(_get(changed_symbol, "path"))
        name = str(_get(changed_symbol, "qualified_name", ""))
        if not path or not name:
            continue
        target_id = symbol_lookup.get((path, name))
        if target_id is None:
            continue

        edges.append(
            make_edge(
                kind="changed_symbol_touches_symbol",
                source=file_node_id(path),
                target=target_id,
                evidence=_evidence(path, _get(changed_symbol, "start_line"), _get(changed_symbol, "end_line")),
                confidence="exact_line_overlap",
            )
        )

    nodes_tuple = dedupe_nodes(nodes)
    edges_tuple = dedupe_edges(edges)

    return EvidenceGraph(
        nodes=nodes_tuple,
        edges=edges_tuple,
        counts=graph_counts(nodes_tuple, edges_tuple),
        warnings=tuple(warnings),
    )
''',

    "src/codebase_lens/reports/graph.py": r'''
from __future__ import annotations

from collections import Counter
from pathlib import Path

from codebase_lens.core.graph import EvidenceGraph, evidence_graph_payload, graph_slice_payload
from codebase_lens.reports.json import write_json_report
from codebase_lens.reports.manifest import OutputLayout


CALL_EDGE_KINDS = {
    "symbol_calls_name",
    "symbol_calls_symbol",
}

MODULE_EDGE_KINDS = {
    "file_defines_module",
    "file_imports_module",
    "module_resolves_to_file",
}


def _node_counter(graph: EvidenceGraph) -> Counter[str]:
    return Counter(node.kind for node in graph.nodes)


def _edge_counter(graph: EvidenceGraph) -> Counter[str]:
    return Counter(edge.kind for edge in graph.edges)


def _product_symbol_nodes(graph: EvidenceGraph, *, limit: int = 30):
    symbols = [
        node
        for node in graph.nodes
        if node.kind == "symbol" and node.path and node.path.startswith("src/codebase_lens/")
    ]

    incoming = Counter(edge.target for edge in graph.edges if edge.target)
    outgoing = Counter(edge.source for edge in graph.edges)

    def priority(node):
        return (
            -(incoming[node.id] + outgoing[node.id]),
            node.path or "",
            node.label,
        )

    return sorted(symbols, key=priority)[:limit]


def _entrypoint_nodes(graph: EvidenceGraph, *, limit: int = 25):
    values = [node for node in graph.nodes if node.kind in {"cli_command", "route"}]
    return sorted(values, key=lambda node: (node.kind, node.label))[:limit]


def _unresolved_call_edges(graph: EvidenceGraph, *, limit: int = 40):
    values = [
        edge
        for edge in graph.edges
        if edge.kind == "symbol_calls_name" and edge.target is None
    ]
    return sorted(values, key=lambda edge: (edge.source, edge.target_text or ""))[:limit]


def render_graph_summary(graph: EvidenceGraph) -> str:
    node_counts = _node_counter(graph)
    edge_counts = _edge_counter(graph)
    product_symbols = _product_symbol_nodes(graph)
    entrypoints = _entrypoint_nodes(graph)
    unresolved = _unresolved_call_edges(graph)

    lines: list[str] = [
        "# CBL Evidence Graph Summary",
        "",
        "Evidence scope: normalized repository graph assembled from scanner, Git, AST, import, symbol, CLI, route, test, and changed-code analyzers.",
        "",
        "## Counts",
        "",
        f"- Nodes: {graph.counts.get('nodes', 0)}",
        f"- Edges: {graph.counts.get('edges', 0)}",
        f"- Exact edges: {graph.counts.get('exact_edges', 0)}",
        f"- Heuristic edges: {graph.counts.get('heuristic_edges', 0)}",
        f"- Unresolved edges: {graph.counts.get('unresolved_edges', 0)}",
        "",
        "## Node Kinds",
        "",
    ]

    for kind, count in sorted(node_counts.items()):
        lines.append(f"- `{kind}`: {count}")

    lines.extend(["", "## Edge Kinds", ""])
    for kind, count in sorted(edge_counts.items()):
        lines.append(f"- `{kind}`: {count}")

    lines.extend(["", "## Entrypoints", ""])
    if entrypoints:
        for node in entrypoints:
            location = f" — `{node.path}`" if node.path else ""
            lines.append(f"- `{node.label}` ({node.kind}){location}")
    else:
        lines.append("- No CLI command or route entrypoints were detected.")

    lines.extend(["", "## High-Connectivity Product Symbols", ""])
    if product_symbols:
        incoming = Counter(edge.target for edge in graph.edges if edge.target)
        outgoing = Counter(edge.source for edge in graph.edges)
        for node in product_symbols:
            rng = ""
            if node.line_range:
                rng = f":L{node.line_range[0]}-L{node.line_range[1]}"
            lines.append(
                f"- `{node.label}` → `{node.path}{rng}` "
                f"(in={incoming[node.id]}, out={outgoing[node.id]})"
            )
    else:
        lines.append("- No product symbols under `src/codebase_lens/` were detected.")

    lines.extend(["", "## Unresolved Static Calls", ""])
    if unresolved:
        for edge in unresolved[:40]:
            source = edge.source.replace("symbol:", "")
            evidence = edge.evidence[0] if edge.evidence else "no evidence"
            lines.append(f"- `{source}` calls `{edge.target_text}` at `{evidence}`")
        if len(unresolved) > 40:
            lines.append(f"- ... {len(unresolved) - 40} additional unresolved call edges omitted.")
    else:
        lines.append("- No unresolved static call-name edges were recorded.")

    if graph.warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in graph.warnings[:50]:
            lines.append(f"- {warning}")

    lines.extend(
        [
            "",
            "## Follow-Up Commands",
            "",
            "- `cbl graph --symbol <symbol> --depth 2` once graph querying is enabled.",
            "- `cbl symbol --name <symbol> --context 80` for high-resolution source evidence.",
            "- `cbl file --path <path> --lines <start>:<end>` for exact file excerpts.",
            "- `cbl callers --name <symbol>` for legacy caller discovery.",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"


def write_evidence_graph_reports(layout: OutputLayout, graph: EvidenceGraph) -> dict[str, str]:
    write_json_report(layout.latest_dir / "evidence_graph.json", evidence_graph_payload(graph))
    write_json_report(layout.latest_dir / "call_graph.json", graph_slice_payload(graph, edge_kinds=CALL_EDGE_KINDS))
    write_json_report(layout.latest_dir / "module_graph.json", graph_slice_payload(graph, edge_kinds=MODULE_EDGE_KINDS))

    (layout.latest_dir / "graph_summary.md").write_text(
        render_graph_summary(graph),
        encoding="utf-8",
        newline="\n",
    )

    return {
        "evidence_graph_json": ".codecontext/latest/evidence_graph.json",
        "call_graph_json": ".codecontext/latest/call_graph.json",
        "module_graph_json": ".codecontext/latest/module_graph.json",
        "graph_summary_md": ".codecontext/latest/graph_summary.md",
    }
''',

    "tests/test_evidence_graph_integration.py": r'''
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
    repo = tmp_path / "graph_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'graph-repo'\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")

    (package / "service.py").write_text(
        "\n".join(
            [
                "from demo.util import double",
                "",
                "def transform(value: int) -> int:",
                "    return double(value) + 1",
                "",
                "def run(value: int) -> int:",
                "    return transform(value)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (package / "util.py").write_text(
        "\n".join(
            [
                "def double(value: int) -> int:",
                "    return value * 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_service.py").write_text(
        "\n".join(
            [
                "from demo.service import transform",
                "",
                "def test_transform():",
                "    assert transform(2) == 5",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_pack_writes_normalized_evidence_graph(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("pack", "--repo", str(repo), "--issue", "evidence graph test", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    evidence_graph = latest / "evidence_graph.json"
    call_graph = latest / "call_graph.json"
    module_graph = latest / "module_graph.json"
    graph_summary = latest / "graph_summary.md"

    for path in [evidence_graph, call_graph, module_graph, graph_summary]:
        assert path.is_file(), path

    payload = json.loads(evidence_graph.read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    edges = payload["edges"]

    node_kinds = {node["kind"] for node in nodes}
    edge_kinds = {edge["kind"] for edge in edges}

    assert {"repository", "file", "module", "symbol", "test"}.issubset(node_kinds)
    assert "file_contains_symbol" in edge_kinds
    assert "file_imports_module" in edge_kinds
    assert "symbol_calls_name" in edge_kinds
    assert "symbol_calls_symbol" in edge_kinds

    labels = {node["label"] for node in nodes}
    assert "transform" in labels
    assert "double" in labels

    call_edges = [
        edge
        for edge in edges
        if edge["kind"] == "symbol_calls_symbol"
    ]
    assert call_edges
    assert len({edge["id"] for edge in call_edges}) == len(call_edges)

    summary = graph_summary.read_text(encoding="utf-8")
    assert "# CBL Evidence Graph Summary" in summary
    assert "## Follow-Up Commands" in summary


def test_snapshot_index_exposes_evidence_graph_outputs(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("snapshot", "--repo", str(repo), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))

    outputs = snapshot_index["outputs"]
    assert outputs["evidence_graph_json"] == ".codecontext/latest/evidence_graph.json"
    assert outputs["call_graph_json"] == ".codecontext/latest/call_graph.json"
    assert outputs["module_graph_json"] == ".codecontext/latest/module_graph.json"
    assert outputs["graph_summary_md"] == ".codecontext/latest/graph_summary.md"

    counts = snapshot_index["counts"]
    assert counts["evidence_graph_nodes"] > 0
    assert counts["evidence_graph_edges"] > 0
''',

    "scripts/dev/audits/audit_phase11_evidence_graph.py": r'''
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
    "src/codebase_lens/core/graph.py": [
        "GraphNode",
        "GraphEdge",
        "EvidenceGraph",
        "evidence_graph_payload",
        "graph_slice_payload",
    ],
    "src/codebase_lens/analyzers/evidence_graph.py": [
        "build_evidence_graph",
    ],
    "src/codebase_lens/reports/graph.py": [
        "write_evidence_graph_reports",
        "render_graph_summary",
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

    pack = run_cbl("pack", "--issue", "phase 11 evidence graph audit", "--budget", "24000", "--no-archive")
    if pack.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    required_outputs = [
        "evidence_graph.json",
        "graph_summary.md",
        "call_graph.json",
        "module_graph.json",
        "ai_handoff.md",
        "snapshot_index.json",
        "pack_index.json",
    ]

    for name in required_outputs:
        if not (latest / name).is_file():
            fail(f"Missing output: {name}")

    graph = json.loads((latest / "evidence_graph.json").read_text(encoding="utf-8"))
    call_graph = json.loads((latest / "call_graph.json").read_text(encoding="utf-8"))
    module_graph = json.loads((latest / "module_graph.json").read_text(encoding="utf-8"))
    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if len(nodes) < 50:
        fail("evidence_graph.json has unexpectedly few nodes for CBL.")
    if len(edges) < 50:
        fail("evidence_graph.json has unexpectedly few edges for CBL.")

    node_kinds = {node.get("kind") for node in nodes if isinstance(node, dict)}
    edge_kinds = {edge.get("kind") for edge in edges if isinstance(edge, dict)}

    for kind in ["repository", "file", "module", "symbol", "cli_command", "test"]:
        if kind not in node_kinds:
            fail(f"evidence_graph.json missing node kind: {kind}")

    for kind in ["repository_contains_file", "file_contains_symbol", "file_imports_module", "symbol_calls_name", "symbol_calls_symbol"]:
        if kind not in edge_kinds:
            fail(f"evidence_graph.json missing edge kind: {kind}")

    edge_ids = [edge.get("id") for edge in edges if isinstance(edge, dict)]
    if len(edge_ids) != len(set(edge_ids)):
        fail("evidence_graph.json contains duplicate edge IDs.")

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("kind") == "symbol_calls_symbol" and not edge.get("target"):
            fail("symbol_calls_symbol edge missing target.")
        if edge.get("kind") == "symbol_calls_name" and edge.get("target") is not None:
            fail("symbol_calls_name edge should preserve unresolved call text rather than pretending a target.")

    if not call_graph.get("edges"):
        fail("call_graph.json contains no edges.")
    if not module_graph.get("edges"):
        fail("module_graph.json contains no edges.")

    summary = (latest / "graph_summary.md").read_text(encoding="utf-8")
    for marker in ["# CBL Evidence Graph Summary", "## Node Kinds", "## Edge Kinds", "## Follow-Up Commands"]:
        if marker not in summary:
            fail(f"graph_summary.md missing marker: {marker}")

    outputs = snapshot_index.get("outputs", {})
    for key in ["evidence_graph_json", "graph_summary_md", "call_graph_json", "module_graph_json"]:
        if key not in outputs:
            fail(f"snapshot_index outputs missing {key}")

    if "C:\\Users\\" in summary:
        fail("graph_summary.md leaked an absolute Windows user path.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 11 evidence graph audit passed.")
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


def patch_snapshot() -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "snapshot.py"
    text = path.read_text(encoding="utf-8")

    import_marker = "from codebase_lens.analyzers.symbol_graph import collect_symbol_graph\n"
    import_addition = (
        "from codebase_lens.analyzers.evidence_graph import build_evidence_graph\n"
        "from codebase_lens.reports.graph import write_evidence_graph_reports\n"
    )

    if import_addition not in text:
        if import_marker not in text:
            raise RuntimeError("snapshot.py import marker not found.")
        text = text.replace(import_marker, import_marker + import_addition, 1)

    old_init = '''    changed_file_count = 0
    changed_symbol_count = 0

    if changed_only:
'''
    new_init = '''    changed_file_count = 0
    changed_symbol_count = 0
    changed_files_for_graph = ()
    changed_symbols_for_graph = ()

    if changed_only:
'''
    if old_init in text and new_init not in text:
        text = text.replace(old_init, new_init, 1)

    old_changed_files = '''        changed_payload = changed_files_payload(diff_result)
        write_json_report(layout.latest_dir / "changed_files.json", changed_payload)
'''
    new_changed_files = '''        changed_files_for_graph = diff_result.changed_files

        changed_payload = changed_files_payload(diff_result)
        write_json_report(layout.latest_dir / "changed_files.json", changed_payload)
'''
    if old_changed_files in text and "changed_files_for_graph = diff_result.changed_files" not in text:
        text = text.replace(old_changed_files, new_changed_files, 1)

    old_changed_symbols = '''        symbol_result = map_changed_symbols(root, diff_result.changed_files)
        changed_symbols_payload = changed_symbol_result_payload(symbol_result)
'''
    new_changed_symbols = '''        symbol_result = map_changed_symbols(root, diff_result.changed_files)
        changed_symbols_for_graph = symbol_result.changed_symbols
        changed_symbols_payload = changed_symbol_result_payload(symbol_result)
'''
    if old_changed_symbols in text and "changed_symbols_for_graph = symbol_result.changed_symbols" not in text:
        text = text.replace(old_changed_symbols, new_changed_symbols, 1)

    old_graph = '''    graph_result = collect_symbol_graph(
        root,
        all_python_files,
        focus_paths=set(python_files) if changed_only else set(),
        focus_terms=focus_terms,
    )
    warnings.extend(graph_result.warnings)
    outputs.update(write_symbol_graph_reports(layout, graph_result))

    counts = {
'''
    new_graph = '''    graph_result = collect_symbol_graph(
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
'''
    if old_graph in text and "evidence_graph = build_evidence_graph(" not in text:
        text = text.replace(old_graph, new_graph, 1)

    old_counts = '''        "symbol_graph_nodes": graph_result.counts.get("nodes", 0),
        "symbol_graph_call_edges": graph_result.counts.get("call_edges", 0),
        "symbol_graph_caller_edges": graph_result.counts.get("caller_edges", 0),
'''
    new_counts = '''        "symbol_graph_nodes": graph_result.counts.get("nodes", 0),
        "symbol_graph_call_edges": graph_result.counts.get("call_edges", 0),
        "symbol_graph_caller_edges": graph_result.counts.get("caller_edges", 0),
        "evidence_graph_nodes": evidence_graph.counts.get("nodes", 0),
        "evidence_graph_edges": evidence_graph.counts.get("edges", 0),
        "evidence_graph_unresolved_edges": evidence_graph.counts.get("unresolved_edges", 0),
'''
    if old_counts in text and "evidence_graph_nodes" not in text:
        text = text.replace(old_counts, new_counts, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_contract() -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    marker = '            "src/codebase_lens/core/models.py",\n'
    addition = '            "src/codebase_lens/core/graph.py",\n'
    if addition not in text:
        if marker not in text:
            raise RuntimeError("architecture.py required-files core marker not found.")
        text = text.replace(marker, marker + addition, 1)

    marker = '            "src/codebase_lens/analyzers/symbol_graph.py",\n'
    addition = '            "src/codebase_lens/analyzers/evidence_graph.py",\n'
    if addition not in text:
        if marker not in text:
            raise RuntimeError("architecture.py required-files analyzer marker not found.")
        text = text.replace(marker, marker + addition, 1)

    marker = '            "src/codebase_lens/reports/symbol_graph.py",\n'
    addition = (
        '            "src/codebase_lens/reports/graph.py",\n'
        '            "scripts/dev/audits/audit_phase11_evidence_graph.py",\n'
    )
    if addition not in text:
        if marker not in text:
            raise RuntimeError("architecture.py required-files report marker not found.")
        text = text.replace(marker, marker + addition, 1)

    required_symbols_block = '''            {
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
'''

    insertion_marker = '''            {
                "path": "src/codebase_lens/analyzers/symbol_graph.py",
'''
    if required_symbols_block not in text:
        if insertion_marker not in text:
            raise RuntimeError("architecture.py required-symbols insertion marker not found.")
        text = text.replace(insertion_marker, required_symbols_block + insertion_marker, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_readiness_audits() -> None:
    for relative in [
        "scripts/dev/audits/audit_v01_readiness.py",
        "scripts/dev/audits/audit_phase8_snapshot_pack.py",
        "scripts/dev/audits/audit_phase10_symbol_graph.py",
    ]:
        path = ROOT / relative
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")
        marker = '    "symbol_graph.md",\n'
        addition = (
            '    "evidence_graph.json",\n'
            '    "graph_summary.md",\n'
            '    "call_graph.json",\n'
            '    "module_graph.json",\n'
        )

        if marker in text and addition not in text:
            text = text.replace(marker, marker + addition, 1)

        path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_snapshot()
    patch_contract()
    patch_readiness_audits()

    print("Slice 013 applied: normalized evidence graph substrate implemented.")
    print("Run Phase 11 audit, prior audits, contract, pytest, and git diff --check before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())