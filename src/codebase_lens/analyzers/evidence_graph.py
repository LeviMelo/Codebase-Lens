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
