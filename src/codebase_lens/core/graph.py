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
