from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any, Literal

UnresolvedMode = Literal["seed", "selected", "none"]


@dataclass(frozen=True)
class GraphQueryResult:
    query: dict[str, Any]
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    counts: dict[str, int | dict[str, int]]
    warnings: tuple[str, ...]


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id", ""))


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("label", ""))


def _node_path(node: dict[str, Any]) -> str:
    return str(node.get("path") or "")


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("data")
    return value if isinstance(value, dict) else {}


def _matches_symbol(node: dict[str, Any], query: str) -> bool:
    if node.get("kind") != "symbol":
        return False

    needle = query.lower()
    label = _node_label(node).lower()
    data = _node_data(node)

    candidates = [
        label,
        str(data.get("qualified_name", "")).lower(),
        str(data.get("simple_name", "")).lower(),
        str(data.get("signature", "")).lower(),
    ]

    return any(needle in candidate for candidate in candidates)


def _matches_path(node: dict[str, Any], query: str) -> bool:
    normalized = query.replace("\\", "/").strip().lower()
    path = _node_path(node).lower()
    return bool(path) and (path == normalized or normalized in path)


def _matches_module(node: dict[str, Any], query: str) -> bool:
    needle = query.lower()
    data = _node_data(node)

    if node.get("kind") == "module":
        candidates = [
            _node_label(node).lower(),
            str(data.get("module", "")).lower(),
        ]
        return any(needle in candidate for candidate in candidates)

    path = _node_path(node).replace("/", ".").lower()
    return needle in path


def _changed_seed_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> set[str]:
    seeds: set[str] = set()

    for node in nodes:
        if node.get("kind") == "changed_hunk":
            seeds.add(_node_id(node))

    for edge in edges:
        if edge.get("kind") in {"changed_symbol_touches_symbol", "file_has_changed_hunk"}:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source:
                seeds.add(source)
            if target:
                seeds.add(target)

    return seeds


def _default_seed_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> set[str]:
    incoming = Counter(str(edge.get("target")) for edge in edges if edge.get("target"))
    outgoing = Counter(str(edge.get("source")) for edge in edges if edge.get("source"))

    product_symbols = [
        node
        for node in nodes
        if node.get("kind") == "symbol" and _node_path(node).startswith("src/codebase_lens/")
    ]

    def priority(node: dict[str, Any]) -> tuple[int, str, str]:
        nid = _node_id(node)
        return (-(incoming[nid] + outgoing[nid]), _node_path(node), _node_label(node))

    ranked = sorted(product_symbols, key=priority)[:limit]
    return {_node_id(node) for node in ranked if _node_id(node)}


def _adjacency(edges: list[dict[str, Any]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}

    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")

        if not source:
            continue

        graph.setdefault(source, set())

        if target:
            graph[source].add(target)
            graph.setdefault(target, set()).add(source)

    return graph


def _expand(seed_ids: set[str], edges: list[dict[str, Any]], *, depth: int) -> set[str]:
    if depth <= 0:
        return set(seed_ids)

    graph = _adjacency(edges)
    visited = set(seed_ids)
    queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in seed_ids)

    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue

        for neighbor in graph.get(current, set()):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, current_depth + 1))

    return visited


def _unresolved_sources_for_mode(mode: str, *, seed_ids: set[str], selected_ids: set[str]) -> set[str]:
    if mode == "none":
        return set()
    if mode == "selected":
        return set(selected_ids)
    return set(seed_ids)


def _selected_edges(
    edges: list[dict[str, Any]],
    selected_ids: set[str],
    *,
    seed_ids: set[str],
    unresolved_mode: str = "seed",
    unresolved_per_source_limit: int = 25,
    total_edge_limit: int = 250,
) -> tuple[tuple[dict[str, Any], ...], dict[str, int]]:
    values: list[dict[str, Any]] = []
    omitted_unresolved = 0
    omitted_by_total_limit = 0
    unresolved_seen_by_source: dict[str, int] = defaultdict(int)
    unresolved_sources = _unresolved_sources_for_mode(unresolved_mode, seed_ids=seed_ids, selected_ids=selected_ids)

    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")

        if source in selected_ids and target in selected_ids:
            values.append(edge)
            continue

        if source in unresolved_sources and not target:
            unresolved_seen_by_source[source] += 1
            if unresolved_seen_by_source[source] > unresolved_per_source_limit:
                omitted_unresolved += 1
                continue
            values.append(edge)

    by_id: dict[str, dict[str, Any]] = {}
    for edge in values:
        by_id[str(edge.get("id"))] = edge

    sorted_values = tuple(sorted(by_id.values(), key=lambda item: (str(item.get("kind")), str(item.get("source")), str(item.get("target") or ""), str(item.get("target_text") or ""))))

    if total_edge_limit > 0 and len(sorted_values) > total_edge_limit:
        omitted_by_total_limit = len(sorted_values) - total_edge_limit
        sorted_values = sorted_values[:total_edge_limit]

    return sorted_values, {
        "omitted_unresolved_edges": omitted_unresolved,
        "omitted_edges_by_limit": omitted_by_total_limit,
    }


def query_evidence_graph_payload(
    graph_payload: dict[str, Any],
    *,
    symbol: str | None = None,
    path: str | None = None,
    module: str | None = None,
    changed: bool = False,
    depth: int = 1,
    limit: int = 60,
    unresolved_mode: UnresolvedMode = "seed",
) -> GraphQueryResult:
    nodes = [node for node in graph_payload.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in graph_payload.get("edges", []) if isinstance(edge, dict)]

    if unresolved_mode not in {"seed", "selected", "none"}:
        unresolved_mode = "seed"

    seed_ids: set[str] = set()
    warnings: list[str] = []

    if symbol:
        seed_ids.update(_node_id(node) for node in nodes if _matches_symbol(node, symbol))
    if path:
        seed_ids.update(_node_id(node) for node in nodes if _matches_path(node, path))
    if module:
        seed_ids.update(_node_id(node) for node in nodes if _matches_module(node, module))
    if changed:
        seed_ids.update(_changed_seed_nodes(nodes, edges))

    explicit_query = bool(symbol or path or module or changed)
    if explicit_query and not seed_ids:
        warnings.append("No graph nodes matched the requested query.")
    if not explicit_query:
        seed_ids.update(_default_seed_nodes(nodes, edges, limit=limit))
        if not seed_ids:
            warnings.append("Default graph query found no product symbols.")

    selected_ids = _expand(seed_ids, edges, depth=max(0, depth))
    selected_nodes = [node for node in nodes if _node_id(node) in selected_ids]

    def _query_node_priority(node: dict[str, Any]) -> tuple[int, int, str, str, str]:
        node_id = _node_id(node)
        return (
            0 if node_id in seed_ids else 1,
            0 if _node_path(node).startswith("src/codebase_lens/") else 1,
            str(node.get("kind")),
            _node_path(node),
            _node_label(node),
        )

    selected_nodes = sorted(selected_nodes, key=_query_node_priority)[: max(limit, len(seed_ids))]
    retained_ids = {_node_id(node) for node in selected_nodes}

    selected_edges, omitted_counts = _selected_edges(
        edges,
        selected_ids,
        seed_ids=seed_ids,
        unresolved_mode=unresolved_mode,
    )
    selected_edges = tuple(
        edge
        for edge in selected_edges
        if str(edge.get("source") or "") in retained_ids
        and (not edge.get("target") or str(edge.get("target")) in retained_ids)
    )

    edge_kinds = Counter(str(edge.get("kind")) for edge in selected_edges)
    node_kinds = Counter(str(node.get("kind")) for node in selected_nodes)

    if omitted_counts["omitted_unresolved_edges"]:
        warnings.append(f"Omitted {omitted_counts['omitted_unresolved_edges']} unresolved call-name edges by per-source cap.")
    if omitted_counts["omitted_edges_by_limit"]:
        warnings.append(f"Omitted {omitted_counts['omitted_edges_by_limit']} graph edges by total edge cap.")

    return GraphQueryResult(
        query={
            "symbol": symbol,
            "path": path,
            "module": module,
            "changed": changed,
            "depth": depth,
            "limit": limit,
            "seed_count": len(seed_ids),
            "unresolved_mode": unresolved_mode,
        },
        nodes=tuple(selected_nodes),
        edges=selected_edges,
        counts={
            "nodes": len(selected_nodes),
            "edges": len(selected_edges),
            "seed_nodes": len(seed_ids),
            "unresolved_edges": sum(1 for edge in selected_edges if not edge.get("target")),
            "omitted_unresolved_edges": omitted_counts["omitted_unresolved_edges"],
            "omitted_edges_by_limit": omitted_counts["omitted_edges_by_limit"],
            "node_kinds": dict(sorted(node_kinds.items())),
            "edge_kinds": dict(sorted(edge_kinds.items())),
        },
        warnings=tuple(warnings),
    )


def graph_query_payload(result: GraphQueryResult) -> dict[str, Any]:
    return {
        "schema": {
            "name": "cbl.graph_query",
            "version": 2,
        },
        "query": dict(result.query),
        "nodes": list(result.nodes),
        "edges": list(result.edges),
        "counts": dict(result.counts),
        "warnings": list(result.warnings),
    }
