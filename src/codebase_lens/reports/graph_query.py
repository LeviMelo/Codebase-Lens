from __future__ import annotations

from collections import Counter
from typing import Any

from codebase_lens.analyzers.graph_query import GraphQueryResult, graph_query_payload
from codebase_lens.reports.json import write_json_report
from codebase_lens.reports.manifest import OutputLayout


def _node_location(node: dict[str, Any]) -> str:
    path = node.get("path")
    line_range = node.get("line_range")

    if not path:
        return ""

    if isinstance(line_range, list) and len(line_range) == 2:
        return f"`{path}:L{line_range[0]}-L{line_range[1]}`"

    if isinstance(line_range, tuple) and len(line_range) == 2:
        return f"`{path}:L{line_range[0]}-L{line_range[1]}`"

    return f"`{path}`"


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("data")
    return value if isinstance(value, dict) else {}


def _render_node(node: dict[str, Any]) -> list[str]:
    label = str(node.get("label", "<unknown>"))
    kind = str(node.get("kind", "<unknown>"))
    location = _node_location(node)
    data = _node_data(node)

    lines = [
        f"### `{label}`",
        "",
        f"- Kind: `{kind}`",
    ]

    if location:
        lines.append(f"- Location: {location}")

    if kind == "symbol":
        signature = data.get("signature")
        if signature:
            lines.append(f"- Signature: `{signature}`")
        if data.get("returns_annotation") is not None:
            lines.append(f"- Returns: `{data.get('returns_annotation') or 'unannotated'}`")

    if kind == "module":
        module = data.get("module")
        if module:
            lines.append(f"- Module: `{module}`")

    if kind == "cli_command":
        command_path = data.get("command_path")
        framework = data.get("framework")
        if command_path:
            lines.append(f"- Command: `{command_path}`")
        if framework:
            lines.append(f"- Framework: `{framework}`")

    lines.append("")
    return lines


def _edge_target(edge: dict[str, Any], node_labels: dict[str, str]) -> str:
    target = edge.get("target")
    if target:
        return f"`{node_labels.get(str(target), str(target))}`"

    target_text = edge.get("target_text")
    if target_text:
        return f"`{target_text}`"

    return "`<unresolved>`"


def _render_edges(edges: tuple[dict[str, Any], ...], node_labels: dict[str, str], *, limit: int = 120) -> list[str]:
    if not edges:
        return ["- No graph edges selected for this query."]

    lines: list[str] = []
    for edge in edges[:limit]:
        kind = edge.get("kind")
        source = node_labels.get(str(edge.get("source")), str(edge.get("source")))
        target = _edge_target(edge, node_labels)
        confidence = edge.get("confidence")
        evidence = edge.get("evidence") or []
        evidence_text = f" — evidence: `{evidence[0]}`" if evidence else ""
        lines.append(f"- `{kind}`: `{source}` → {target} [{confidence}]{evidence_text}")

    if len(edges) > limit:
        lines.append(f"- ... {len(edges) - limit} additional edges omitted from this markdown view; see `graph_query.json`.")

    return lines


def render_graph_query_markdown(result: GraphQueryResult) -> str:
    node_labels = {str(node.get("id")): str(node.get("label", node.get("id"))) for node in result.nodes}
    node_kinds = Counter(str(node.get("kind")) for node in result.nodes)
    edge_kinds = Counter(str(edge.get("kind")) for edge in result.edges)

    lines: list[str] = [
        "# CBL Graph Query",
        "",
        "Evidence scope: scoped projection over `evidence_graph.json`.",
        "",
        "## Query",
        "",
        f"- Symbol: `{result.query.get('symbol')}`",
        f"- Path: `{result.query.get('path')}`",
        f"- Module: `{result.query.get('module')}`",
        f"- Changed only: `{result.query.get('changed')}`",
        f"- Depth: `{result.query.get('depth')}`",
        f"- Seed nodes: `{result.query.get('seed_count')}`",
        "",
        "## Counts",
        "",
        f"- Nodes: {result.counts.get('nodes', 0)}",
        f"- Edges: {result.counts.get('edges', 0)}",
        f"- Unresolved edges: {result.counts.get('unresolved_edges', 0)}",
        "",
        "## Node Kinds",
        "",
    ]

    if node_kinds:
        for kind, count in sorted(node_kinds.items()):
            lines.append(f"- `{kind}`: {count}")
    else:
        lines.append("- No nodes selected.")

    lines.extend(["", "## Edge Kinds", ""])
    if edge_kinds:
        for kind, count in sorted(edge_kinds.items()):
            lines.append(f"- `{kind}`: {count}")
    else:
        lines.append("- No edges selected.")

    if result.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in result.warnings)

    lines.extend(["", "## Nodes", ""])
    for node in result.nodes[:80]:
        lines.extend(_render_node(node))

    if len(result.nodes) > 80:
        lines.append(f"... {len(result.nodes) - 80} additional nodes omitted from this markdown view; see `graph_query.json`.")
        lines.append("")

    lines.extend(["", "## Edges", ""])
    lines.extend(_render_edges(result.edges, node_labels))

    lines.extend(
        [
            "",
            "## Follow-Up Commands",
            "",
            "- `cbl symbol --name <symbol> --context 80` for exact symbol source.",
            "- `cbl file --path <path> --lines <start>:<end>` for exact line-range source.",
            "- `cbl callers --name <symbol>` for legacy caller lookup.",
            "- `cbl graph --symbol <symbol> --depth 2` for a wider graph neighborhood.",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"


def write_graph_query_reports(layout: OutputLayout, result: GraphQueryResult) -> dict[str, str]:
    write_json_report(layout.latest_dir / "graph_query.json", graph_query_payload(result))
    (layout.latest_dir / "graph_query.md").write_text(
        render_graph_query_markdown(result),
        encoding="utf-8",
        newline="\n",
    )

    return {
        "graph_query_json": ".codecontext/latest/graph_query.json",
        "graph_query_md": ".codecontext/latest/graph_query.md",
    }
