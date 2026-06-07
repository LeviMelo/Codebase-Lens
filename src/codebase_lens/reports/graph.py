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
