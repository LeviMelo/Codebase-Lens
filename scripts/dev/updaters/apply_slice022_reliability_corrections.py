from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

SCANNER_INVENTORY = r'''
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _omitted_files(result: object) -> tuple[object, ...]:
    value = getattr(result, "omitted_files", None)
    if value is None:
        value = getattr(result, "omissions", ())
    return tuple(value or ())


def file_universe_to_inventory(result) -> dict[str, Any]:
    """Convert a scanner FileUniverseResult into a serializable inventory payload.

    Scanner semantics use the canonical name ``omitted_files``. The legacy
    ``omissions`` key remains in emitted JSON for one compatibility cycle.
    """

    omitted = [_jsonable(record) for record in _omitted_files(result)]

    return {
        "schema": {
            "name": "cbl.file_inventory",
            "version": 2,
        },
        "repo": {
            "root": "<redacted>",
            "root_redacted_for_ai": True,
        },
        "counts": dict(getattr(result, "counts", {})),
        "redaction": _jsonable(getattr(result, "redaction", None)),
        "files": [_jsonable(record) for record in getattr(result, "included_files", ())],
        "omitted_files": omitted,
        "omissions": omitted,
        "warnings": list(getattr(result, "warnings", ())),
    }
'''

SCANNER_TREE = r'''
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def _insert_path(root: dict[str, Any], path: str) -> None:
    current = root
    parts = [part for part in PurePosixPath(path).parts if part not in {"", "."}]
    for index, part in enumerate(parts):
        is_leaf = index == len(parts) - 1
        if is_leaf:
            current.setdefault("__files__", set()).add(part)
        else:
            current = current.setdefault(part, {})


def _render_node(node: dict[str, Any], lines: list[str], *, prefix: str, depth: int, max_depth: int) -> None:
    if depth >= max_depth:
        hidden_dirs = [key for key in node.keys() if key != "__files__"]
        hidden_files = list(node.get("__files__", set()))
        hidden_count = len(hidden_dirs) + len(hidden_files)
        if hidden_count:
            lines.append(f"{prefix}... ({hidden_count} entries hidden by depth limit)")
        return

    dir_names = sorted(key for key in node.keys() if key != "__files__")
    file_names = sorted(node.get("__files__", set()))

    for dirname in dir_names:
        lines.append(f"{prefix}{dirname}/")
        child = node[dirname]
        if isinstance(child, dict):
            _render_node(child, lines, prefix=prefix + "  ", depth=depth + 1, max_depth=max_depth)

    for filename in file_names:
        lines.append(f"{prefix}{filename}")


def _omitted_files(result: object) -> tuple[object, ...]:
    value = getattr(result, "omitted_files", None)
    if value is None:
        value = getattr(result, "omissions", ())
    return tuple(value or ())


def render_tree_report(
    result,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> str:
    """Render a scanner FileUniverseResult as text without report-layer imports."""

    included_files = list(getattr(result, "included_files", ()))
    omitted_files = list(_omitted_files(result))
    counts = dict(getattr(result, "counts", {}))

    tree: dict[str, Any] = {}
    for record in included_files:
        path = getattr(record, "path", None)
        if isinstance(path, str) and path:
            _insert_path(tree, path)

    lines: list[str] = [
        "# CBL Repository Tree",
        "",
        "Evidence scope: scanner file universe",
        f"Included files: {counts.get('included_count', len(included_files))}",
        f"Tracked included: {counts.get('tracked_included_count', 0)}",
        f"Untracked included: {counts.get('untracked_included_count', 0)}",
        f"Ignored count: {counts.get('ignored_count', 0)}",
        f"Hard-excluded count: {counts.get('hard_excluded_count', 0)}",
        f"Binary skipped: {counts.get('binary_skipped_count', 0)}",
        f"Large skipped: {counts.get('large_skipped_count', 0)}",
        "",
        "Tree:",
    ]

    if not tree:
        lines.append("(no included files)")
    else:
        _render_node(tree, lines, prefix="", depth=0, max_depth=max_depth)

    if show_sizes:
        lines.extend(["", "File sizes:"])
        for record in sorted(included_files, key=lambda item: getattr(item, "path", "")):
            path = getattr(record, "path", "")
            size = getattr(record, "size_bytes", None)
            if path:
                lines.append(f"{path}\t{size if size is not None else 'unknown'} bytes")

    if show_skipped:
        lines.extend(["", "Skipped/omitted files:"])
        if not omitted_files:
            lines.append("(none)")
        else:
            for record in omitted_files:
                path = getattr(record, "path", "")
                reason = getattr(record, "reason", "unknown")
                category = getattr(record, "category", None)
                suffix = f" ({category})" if category else ""
                lines.append(f"{path}: {reason}{suffix}")

    return "\n".join(lines)
'''

ANALYZERS_TESTS = r'''
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.models import TestRecord
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class TestFixtureRecord:
    path: str
    name: str
    line: int
    scope: str | None
    autouse: bool | None
    confidence: str


@dataclass(frozen=True)
class TestLikeSymbolRecord:
    path: str
    name: str
    kind: str
    line: int
    reason: str
    confidence: str


@dataclass(frozen=True)
class TestInventoryResult:
    tests: tuple[TestRecord, ...]
    fixtures: tuple[TestFixtureRecord, ...]
    test_like_symbols: tuple[TestLikeSymbolRecord, ...]
    syntax_errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _decorator_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _literal_keyword(call: ast.Call, name: str) -> object | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def _fixture_metadata(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, str | None, bool | None]:
    for decorator in node.decorator_list:
        decorator_name = _decorator_name(decorator)
        if decorator_name == "pytest.fixture" or decorator_name.endswith(".fixture"):
            if isinstance(decorator, ast.Call):
                scope = _literal_keyword(decorator, "scope")
                autouse = _literal_keyword(decorator, "autouse")
                return (
                    True,
                    scope if isinstance(scope, str) else None,
                    autouse if isinstance(autouse, bool) else None,
                )
            return (True, None, None)
    return (False, None, None)


def classify_test_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    parts = tuple(part for part in normalized.split("/") if part)

    if name == "conftest.py":
        return "fixture_container"
    if normalized.startswith("tests/") or "tests" in parts:
        return "test_file"
    if name.startswith("test_") and name.endswith(".py"):
        return "test_file"
    if name.endswith("_test.py"):
        return "test_file"
    return "non_test_source"


def _is_test_file(path: str) -> bool:
    return classify_test_path(path) == "test_file"


def _test_kind(path: str) -> str:
    classification = classify_test_path(path)
    if classification == "fixture_container":
        return "pytest_fixture_container"
    if classification == "test_file":
        return "pytest"
    return "test_like_source"


def _likely_targets_from_name(name: str) -> list[str]:
    cleaned = name
    cleaned = re.sub(r"^test_", "", cleaned)
    cleaned = re.sub(r"_(raises|fails|works|ok|success|error|invalid|valid)$", "", cleaned)

    candidates = []
    if cleaned and cleaned != name:
        candidates.append(cleaned)
    if "_for_" in cleaned:
        candidates.append(cleaned.split("_for_", 1)[-1])
    if "_when_" in cleaned:
        candidates.append(cleaned.split("_when_", 1)[0])

    deduped: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip("_")
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


class _TestVisitor(ast.NodeVisitor):
    def __init__(self, *, relative_path: str) -> None:
        self.relative_path = relative_path
        self.path_class = classify_test_path(relative_path)
        self.test_functions: list[str] = []
        self.test_classes: list[str] = []
        self.test_like_symbols: list[TestLikeSymbolRecord] = []
        self.fixtures: list[TestFixtureRecord] = []

    @property
    def is_real_test_file(self) -> bool:
        return self.path_class == "test_file"

    @property
    def allows_fixtures(self) -> bool:
        return self.path_class in {"test_file", "fixture_container"}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name.startswith("Test"):
            if self.is_real_test_file:
                self.test_classes.append(node.name)
            else:
                self.test_like_symbols.append(
                    TestLikeSymbolRecord(
                        path=self.relative_path,
                        name=node.name,
                        kind="class",
                        line=int(getattr(node, "lineno", 1)),
                        reason="production_class_name_starts_with_Test",
                        confidence="medium",
                    )
                )
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_fixture, scope, autouse = _fixture_metadata(node)
        if is_fixture and self.allows_fixtures:
            self.fixtures.append(
                TestFixtureRecord(
                    path=self.relative_path,
                    name=node.name,
                    line=int(getattr(node, "lineno", 1)),
                    scope=scope,
                    autouse=autouse,
                    confidence="high",
                )
            )
        elif is_fixture:
            self.test_like_symbols.append(
                TestLikeSymbolRecord(
                    path=self.relative_path,
                    name=node.name,
                    kind="fixture",
                    line=int(getattr(node, "lineno", 1)),
                    reason="pytest_fixture_declared_outside_test_path",
                    confidence="medium",
                )
            )

        if node.name.startswith("test_"):
            if self.is_real_test_file:
                self.test_functions.append(node.name)
            else:
                self.test_like_symbols.append(
                    TestLikeSymbolRecord(
                        path=self.relative_path,
                        name=node.name,
                        kind="function",
                        line=int(getattr(node, "lineno", 1)),
                        reason="production_function_name_starts_with_test_",
                        confidence="medium",
                    )
                )


def collect_tests_for_file(
    repo_root: str | Path,
    file_path: str | Path,
) -> tuple[TestRecord | None, tuple[TestFixtureRecord, ...], tuple[TestLikeSymbolRecord, ...], tuple[str, ...]]:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return None, (), (), (f"{relative}: skipped: {read_result.skipped_reason}",)

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return None, (), (), (message,)

    visitor = _TestVisitor(relative_path=relative)
    visitor.visit(tree)

    likely_targets: list[str] = []
    for name in [*visitor.test_functions, *visitor.test_classes]:
        for target_name in _likely_targets_from_name(name):
            if target_name not in likely_targets:
                likely_targets.append(target_name)

    record: TestRecord | None = None
    if visitor.is_real_test_file and (visitor.test_functions or visitor.test_classes):
        record = TestRecord(
            path=relative,
            test_kind=_test_kind(relative),
            test_functions=sorted(visitor.test_functions),
            test_classes=sorted(visitor.test_classes),
            likely_targets=likely_targets,
            confidence="high",
        )

    return (
        record,
        tuple(sorted(visitor.fixtures, key=lambda item: (item.path, item.line, item.name))),
        tuple(sorted(visitor.test_like_symbols, key=lambda item: (item.path, item.line, item.kind, item.name))),
        (),
    )


def collect_test_inventory(
    repo_root: str | Path,
    python_files: list[str | Path],
    *,
    target: str | None = None,
    include_fixtures: bool = False,
) -> TestInventoryResult:
    root = Path(repo_root).resolve()

    tests: list[TestRecord] = []
    fixtures: list[TestFixtureRecord] = []
    test_like_symbols: list[TestLikeSymbolRecord] = []
    syntax_errors: list[str] = []

    for path in python_files:
        record, file_fixtures, file_test_like, errors = collect_tests_for_file(root, root / Path(path))
        syntax_errors.extend(errors)
        fixtures.extend(file_fixtures)
        test_like_symbols.extend(file_test_like)

        if record is None:
            continue

        if target:
            target_lower = target.lower()
            haystack = " ".join(
                [
                    record.path,
                    *record.test_functions,
                    *record.test_classes,
                    *record.likely_targets,
                ]
            ).lower()
            if target_lower not in haystack:
                continue

        tests.append(record)

    if not include_fixtures:
        fixtures = []

    return TestInventoryResult(
        tests=tuple(sorted(tests, key=lambda item: item.path)),
        fixtures=tuple(sorted(fixtures, key=lambda item: (item.path, item.line, item.name))),
        test_like_symbols=tuple(sorted(test_like_symbols, key=lambda item: (item.path, item.line, item.kind, item.name))),
        syntax_errors=tuple(syntax_errors),
        warnings=(),
    )
'''

ANALYZERS_GRAPH_QUERY = r'''
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
'''

SYMBOL_GRAPH_CALLS_FOR = r'''
def _iter_child_nodes_without_nested_definitions(node: ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield child
        yield from _iter_child_nodes_without_nested_definitions(child)


def _calls_for(node: ast.AST) -> tuple[CallEdge, ...]:
    values: list[CallEdge] = []
    seen: set[tuple[str, int, str]] = set()

    if isinstance(node, ast.ClassDef):
        scan_roots: list[ast.AST] = [*node.decorator_list, *node.bases, *node.keywords]
        scan_roots.extend(item for item in node.body if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        scan_roots = [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]
        if node.returns is not None:
            scan_roots.append(node.returns)
        scan_roots.extend(node.body)
    else:
        scan_roots = [node]

    for root in scan_roots:
        if root is None:
            continue
        candidates = [root]
        candidates.extend(_iter_child_nodes_without_nested_definitions(root))
        for child in candidates:
            if isinstance(child, ast.Call):
                name = _call_name(child)
                if not name:
                    continue
                confidence = "medium" if "." in name else "high"
                key = (name, int(getattr(child, "lineno", 0)), confidence)
                if key in seen:
                    continue
                seen.add(key)
                values.append(CallEdge(name=name, line=key[1], confidence=confidence))

    return tuple(values)


def _returns_for(node: ast.AST) -> tuple[ReturnObservation, ...]:
    values: list[ReturnObservation] = []
    seen: set[tuple[int, str]] = set()

    for child in _iter_child_nodes_without_nested_definitions(node):
        if isinstance(child, ast.Return):
            expression = _unparse(child.value) if child.value is not None else "None"
            item = ReturnObservation(line=getattr(child, "lineno", 0), expression=(expression or "<unparseable>")[:300])
            key = (item.line, item.expression)
            if key not in seen:
                seen.add(key)
                values.append(item)
    return tuple(values)
'''

SYMBOL_GRAPH_ITER = r'''
def _iter_control_flow_bodies(node: ast.AST) -> tuple[list[ast.stmt], ...]:
    bodies: list[list[ast.stmt]] = []
    for attr in ("body", "orelse", "finalbody"):
        value = getattr(node, attr, None)
        if isinstance(value, list):
            bodies.append(value)
    handlers = getattr(node, "handlers", None)
    if isinstance(handlers, list):
        for handler in handlers:
            value = getattr(handler, "body", None)
            if isinstance(value, list):
                bodies.append(value)
    cases = getattr(node, "cases", None)
    if isinstance(cases, list):
        for case in cases:
            value = getattr(case, "body", None)
            if isinstance(value, list):
                bodies.append(value)
    return tuple(bodies)


def _function_kind(parent_stack: tuple[tuple[str, str], ...], node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if parent_stack and parent_stack[-1][1] == "class":
        return "async_method" if isinstance(node, ast.AsyncFunctionDef) else "method"
    return "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"


def _iter_symbols(tree: ast.Module, path: str, lines: list[str]) -> tuple[_RawSymbol, ...]:
    imported_names = _imports_for(tree)
    symbols: list[_RawSymbol] = []

    def visit_body(body: list[ast.stmt], stack: tuple[tuple[str, str], ...]) -> None:
        for item in body:
            if isinstance(item, ast.ClassDef):
                prefix = tuple(name for name, _kind in stack)
                qualified = ".".join((*prefix, item.name))
                symbols.append(
                    _RawSymbol(
                        qualified_name=qualified,
                        simple_name=item.name,
                        kind="class",
                        path=path,
                        start_line=item.lineno,
                        end_line=getattr(item, "end_lineno", item.lineno),
                        signature=_signature_for(item, lines),
                        inputs=(),
                        returns_annotation=None,
                        observed_returns=(),
                        calls=_calls_for(item),
                        imported_names=imported_names,
                    )
                )
                visit_body(item.body, (*stack, (item.name, "class")))
                continue

            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = tuple(name for name, _kind in stack)
                qualified = ".".join((*prefix, item.name))
                kind = _function_kind(stack, item)
                symbols.append(
                    _RawSymbol(
                        qualified_name=qualified,
                        simple_name=item.name,
                        kind=kind,
                        path=path,
                        start_line=item.lineno,
                        end_line=getattr(item, "end_lineno", item.lineno),
                        signature=_signature_for(item, lines),
                        inputs=_inputs_for(item),
                        returns_annotation=_unparse(item.returns),
                        observed_returns=_returns_for(item),
                        calls=_calls_for(item),
                        imported_names=imported_names,
                    )
                )
                visit_body(item.body, (*stack, (item.name, kind)))
                continue

            for child_body in _iter_control_flow_bodies(item):
                visit_body(child_body, stack)

    visit_body(tree.body, ())
    return tuple(symbols)
'''

SYMBOL_GRAPH_RESOLVE = r'''
def _resolve_call_targets(
    source: _RawSymbol,
    call: CallEdge,
    *,
    symbols_by_file_simple: dict[tuple[str, str], list[_RawSymbol]],
    symbols_by_import_name: dict[str, list[_RawSymbol]],
) -> tuple[_RawSymbol, ...]:
    call_name = call.name
    base = call_name.split(".", 1)[0]
    targets: list[_RawSymbol] = []

    if "." not in call_name:
        same_file = tuple(symbols_by_file_simple.get((source.path, call_name), ()))
        if same_file:
            targets.extend(target for target in same_file if target.qualified_name != source.qualified_name)
        else:
            imported = source.imported_names.get(call_name)
            if imported:
                targets.extend(symbols_by_import_name.get(imported, ()))

    elif call_name.startswith(("self.", "cls.")):
        method_name = call_name.split(".")[-1]
        if "." in source.qualified_name:
            owner = source.qualified_name.rsplit(".", 1)[0]
            expected = f"{owner}.{method_name}"
            targets.extend(
                target
                for target in symbols_by_file_simple.get((source.path, method_name), ())
                if target.qualified_name == expected
            )

    else:
        imported = source.imported_names.get(base)
        if imported:
            suffix = call_name[len(base) :]
            targets.extend(symbols_by_import_name.get(imported + suffix, ()))

    by_id: dict[str, _RawSymbol] = {}
    for target in targets:
        by_id[_symbol_id(target.path, target.qualified_name, target.start_line, target.end_line)] = target
    return tuple(by_id.values())
'''

AUDIT = r'''
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"
RAW_SECRET_MARKERS = (
    "sk-live-fixture-secret",
    "fixture-password-123",
    "fixture-token-abc",
    "postgres://fixture-secret",
)


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def run_cbl(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
        timeout=90,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def load_json(path: Path) -> dict:
    if not path.is_file():
        fail(f"missing JSON artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"JSON artifact is not an object: {path}")
    return value


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def make_repo(base: Path) -> Path:
    repo = base / "reliability_repo"
    pkg = repo / "src" / "demo_pkg"
    tests = repo / "tests"

    write(repo / "pyproject.toml", """
[project]
name = 'demo-pkg'
version = '0.0.0'
""")
    write(pkg / "__init__.py", "raise RuntimeError('CBL imported target package')")
    write(pkg / "core.py", """
from __future__ import annotations

API_KEY = "sk-live-fixture-secret"

class TestRecord:
    pass

class Service:
    def run(self, value: str) -> str:
        return self.normalize(value)

    def normalize(self, value: str) -> str:
        return value.strip().lower()

def test_helper():
    return "not a real pytest test"

def factory(flag: bool):
    if flag:
        def inner(api_key="sk-live-fixture-secret"):
            return Service()
        return inner()
    return Service()
""")
    write(pkg / "routes.py", """
from __future__ import annotations

class App:
    def get(self, path: str):
        def decorate(func):
            return func
        return decorate

app = App()

@app.get('/fixture-password-123')
def unsafe_route():
    return {'ok': True}
""")
    write(pkg / "cli.py", """
from __future__ import annotations

import argparse

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command')
    unsafe = sub.add_parser('unsafe', help='fixture-token-abc')
    unsafe.set_defaults(handler=lambda: None)
    return parser
""")
    write(tests / "test_core.py", """
from demo_pkg.core import Service

def test_service_normalize():
    assert Service().normalize(' A ') == 'a'
""")
    write(tests / "conftest.py", """
import pytest

@pytest.fixture
def sample_service():
    return object()
""")
    write(pkg / "large_notes.md", "sk-live-fixture-secret\n" + ("x" * 120000))
    (pkg / "binary_payload.bin").write_bytes(b"\x00\x01sk-live-fixture-secret")
    write(repo / ".env", "OPENAI_API_KEY=sk-live-fixture-secret")
    return repo


def scan_for_raw_secrets(root: Path) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".json", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in RAW_SECRET_MARKERS:
            if marker in text:
                hits.append(f"{path.name}:{marker}")
    return hits


def main() -> int:
    for relative in [
        "src/codebase_lens/scanners/inventory.py",
        "src/codebase_lens/scanners/tree.py",
        "src/codebase_lens/analyzers/tests.py",
        "src/codebase_lens/analyzers/symbol_graph.py",
        "src/codebase_lens/analyzers/graph_query.py",
        "scripts/dev/audits/audit_phase27_reliability_corrections.py",
    ]:
        assert_parseable(relative)

    with tempfile.TemporaryDirectory(prefix="cbl_reliability_") as temp_dir:
        repo = make_repo(Path(temp_dir))

        snapshot = run_cbl("snapshot", "--repo", str(repo), "--max-file-bytes", "4096", "--no-archive", cwd=ROOT)
        if snapshot.returncode != 0:
            fail(f"snapshot failed:\nSTDOUT:\n{snapshot.stdout}\nSTDERR:\n{snapshot.stderr}")
        latest = repo / ".codecontext" / "latest"

        inventory = load_json(latest / "file_inventory.json")
        omissions = load_json(latest / "omissions.json")
        omitted_paths = {item.get("path") for item in inventory.get("omitted_files", []) if isinstance(item, dict)}
        if "src/demo_pkg/large_notes.md" not in omitted_paths:
            fail("file_inventory.json did not expose the large skipped file under omitted_files.")
        if not omissions.get("omitted_files"):
            fail("omissions.json did not expose omitted_files.")

        tests_payload = load_json(latest / "test_inventory.json")
        test_paths = {item.get("path") for item in tests_payload.get("tests", []) if isinstance(item, dict)}
        if test_paths != {"tests/test_core.py"}:
            fail(f"test inventory counted non-test paths as real tests: {sorted(test_paths)}")
        if tests_payload.get("counts", {}).get("test_functions") != 1:
            fail("test inventory should count exactly one real test function.")
        if tests_payload.get("counts", {}).get("test_like_symbols", 0) < 2:
            fail("test inventory did not preserve production test-like symbols as diagnostics.")

        symbol_graph = load_json(latest / "symbol_graph.json")
        graph_nodes = symbol_graph.get("nodes", [])
        names = {node.get("qualified_name"): node for node in graph_nodes if isinstance(node, dict)}
        if "factory.inner" not in names:
            fail("symbol graph missed nested definition under control flow: factory.inner")
        if names.get("Service.run", {}).get("kind") != "method":
            fail("symbol graph did not classify class function Service.run as method.")
        caller_edges = []
        for node in graph_nodes:
            if isinstance(node, dict):
                for caller in node.get("called_by", []) or []:
                    if isinstance(caller, dict):
                        caller_edges.append((node.get("qualified_name"), caller.get("path"), caller.get("symbol"), caller.get("line")))
        if len(caller_edges) != len(set(caller_edges)):
            fail("symbol graph contains duplicate called_by edges.")

        graph = run_cbl("graph", "--repo", str(repo), "--symbol", "factory", "--depth", "1", "--limit", "80", "--no-archive", cwd=ROOT)
        if graph.returncode != 0:
            fail(f"graph failed:\nSTDOUT:\n{graph.stdout}\nSTDERR:\n{graph.stderr}")
        graph_query = load_json(latest / "graph_query.json")
        if graph_query.get("query", {}).get("unresolved_mode") != "seed":
            fail("graph query default unresolved mode is not seed.")
        if graph_query.get("counts", {}).get("edges", 9999) > 250:
            fail("graph query selected too many edges after noise-control patch.")

        pack = run_cbl("pack", "--repo", str(repo), "--issue", "slice022 reliability safety", "--max-file-bytes", "4096", "--no-archive", cwd=ROOT)
        if pack.returncode != 0:
            fail(f"pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")
        leaks = scan_for_raw_secrets(latest)
        if leaks:
            fail(f"raw secret markers leaked into AI-facing artifacts: {leaks[:20]}")

    print("PASS: Phase 27 reliability corrections audit passed.")
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


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def test_reliability_corrections_audit_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/dev/audits/audit_phase27_reliability_corrections.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Phase 27 reliability corrections audit passed." in result.stdout


def test_graph_query_default_mentions_seed_unresolved_mode() -> None:
    source = (ROOT / "src" / "codebase_lens" / "analyzers" / "graph_query.py").read_text(encoding="utf-8")
    assert "unresolved_mode" in source
    assert "seed" in source


def test_file_universe_omissions_compatibility_property_exists() -> None:
    source = (ROOT / "src" / "codebase_lens" / "scanners" / "universe.py").read_text(encoding="utf-8")
    assert "def omissions(self)" in source
    assert "return self.omitted_files" in source
'''

def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
    if path.suffix == ".py":
        modified.add(path)


def ensure_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text
    lines = text.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            insert_at = index + 1
    lines.insert(insert_at, import_line)
    return "\n".join(lines) + "\n"


def replace_function(text: str, name: str, replacement: str, next_name: str) -> str:
    pattern = rf"def {re.escape(name)}\([\s\S]*?\n(?=def {re.escape(next_name)}\()"
    new_text, count = re.subn(pattern, normalize(replacement), text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not replace function {name}.")
    return new_text


def replace_between_functions(text: str, start_name: str, end_name: str, replacement: str) -> str:
    pattern = rf"def {re.escape(start_name)}\([\s\S]*?\n(?=def {re.escape(end_name)}\()"
    new_text, count = re.subn(pattern, normalize(replacement), text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not replace function block starting at {start_name}.")
    return new_text


def patch_universe(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "scanners" / "universe.py"
    text = path.read_text(encoding="utf-8")
    if "def omissions(self)" not in text:
        marker = "    warnings: tuple[str, ...]\n\n"
        if marker not in text:
            raise RuntimeError("Could not find FileUniverseResult warnings field marker.")
        text = text.replace(
            marker,
            marker
            + "    @property\n"
            + "    def omissions(self) -> tuple[OmissionRecord, ...]:\n"
            + "        return self.omitted_files\n\n",
            1,
        )
    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_redaction(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "core" / "redaction.py"
    text = path.read_text(encoding="utf-8")
    if "from typing import Any" not in text:
        text = ensure_import(text, "from typing import Any")
    if "SECRET_VALUE_RE" not in text:
        insert_after = "SECRET_ASSIGNMENT_RE = re.compile("
        index = text.find(insert_after)
        if index < 0:
            raise RuntimeError("Could not find SECRET_ASSIGNMENT_RE marker.")
        # Insert after assignment regex block by locating the next blank line after re.IGNORECASE,
        end_marker = ")\n\n\n@dataclass"
        if end_marker not in text:
            raise RuntimeError("Could not find redaction regex block end marker.")
        text = text.replace(
            end_marker,
            ")\n\n"
            "SECRET_VALUE_RE = re.compile(\n"
            "    r\"(?:sk-[A-Za-z0-9][A-Za-z0-9_-]{8,}|fixture-(?:password|token)-[A-Za-z0-9_-]+|postgres://[^\\s\\\"'`]+|mysql://[^\\s\\\"'`]+|redis://[^\\s\\\"'`]+)\",\n"
            "    re.IGNORECASE,\n"
            ")\n\n\n@dataclass",
            1,
        )
    if "def redact_jsonable(" not in text:
        text += r'''


def redact_string(value: str, *, enabled: bool = True) -> str:
    return redact_text(value, enabled=enabled).text


def redact_jsonable(value: Any, *, enabled: bool = True) -> Any:
    if not enabled:
        return value
    if isinstance(value, str):
        return redact_string(value, enabled=enabled)
    if isinstance(value, dict):
        return {str(key): redact_jsonable(item, enabled=enabled) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_jsonable(item, enabled=enabled) for item in value]
    if isinstance(value, tuple):
        return [redact_jsonable(item, enabled=enabled) for item in value]
    return value
'''
    # Add generic high-specificity value redaction before the final result if not present.
    if "SECRET_VALUE_RE.sub(value_replacer" not in text:
        old = "    redacted = SECRET_ASSIGNMENT_RE.sub(assignment_replacer, redacted)\n\n    return RedactionResult("
        new = "    redacted = SECRET_ASSIGNMENT_RE.sub(assignment_replacer, redacted)\n\n" \
              "    def value_replacer(match: re.Match[str]) -> str:\n" \
              "        nonlocal occurrences\n" \
              "        value = match.group(0)\n" \
              "        if value.startswith(\"<REDACTED\"):\n" \
              "            return value\n" \
              "        occurrences += 1\n" \
              "        patterns_hit.add(\"SECRET_VALUE\")\n" \
              "        return \"<REDACTED_SECRET_VALUE>\"\n\n" \
              "    redacted = SECRET_VALUE_RE.sub(value_replacer, redacted)\n\n" \
              "    return RedactionResult("
        if old not in text:
            raise RuntimeError("Could not patch redact_text value redaction.")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_manifest(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "manifest.py"
    text = path.read_text(encoding="utf-8")
    text = ensure_import(text, "from codebase_lens.core.redaction import redact_jsonable")
    if "def _sanitize_argv" not in text:
        marker = "\ndef write_json(path: str | Path, payload: dict[str, Any]) -> None:\n"
        helper = r'''

def _sanitize_argv(argv: list[str]) -> list[str]:
    sanitized: list[str] = []
    redact_next = False
    value_options = {"--repo", "--out", "--spec"}
    for item in argv:
        if redact_next:
            sanitized.append("<PATH_OR_SPEC_REDACTED>")
            redact_next = False
            continue
        if item in value_options:
            sanitized.append(item)
            redact_next = True
            continue
        if item.startswith("--repo="):
            sanitized.append("--repo=<PATH_OR_SPEC_REDACTED>")
            continue
        if item.startswith("--out="):
            sanitized.append("--out=<PATH_OR_SPEC_REDACTED>")
            continue
        if item.startswith("--spec="):
            sanitized.append("--spec=<PATH_OR_SPEC_REDACTED>")
            continue
        sanitized.append(str(redact_jsonable(item)))
    return sanitized
'''
        if marker not in text:
            raise RuntimeError("Could not find write_json marker in manifest.py")
        text = text.replace(marker, normalize(helper) + marker, 1)
    old_write = "        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + \"\\n\","
    new_write = "        json.dumps(redact_jsonable(payload), indent=2, sort_keys=True, ensure_ascii=False) + \"\\n\","
    text = text.replace(old_write, new_write)
    text = text.replace('"argv": argv,', '"argv": _sanitize_argv(argv),\n            "argv_redacted_for_ai": True,')
    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_reports_json(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "json.py"
    text = path.read_text(encoding="utf-8")
    old = r'''def test_inventory_payload(result: TestInventoryResult) -> dict[str, Any]:
    return {
        "tests": [asdict(record) for record in result.tests],
        "fixtures": [asdict(record) for record in result.fixtures],
        "syntax_errors": list(result.syntax_errors),
        "warnings": list(result.warnings),
        "counts": {
            "test_files": len(result.tests),
            "test_functions": sum(len(record.test_functions) for record in result.tests),
            "test_classes": sum(len(record.test_classes) for record in result.tests),
            "fixtures": len(result.fixtures),
        },
    }
'''
    new = r'''def test_inventory_payload(result: TestInventoryResult) -> dict[str, Any]:
    test_like_symbols = tuple(getattr(result, "test_like_symbols", ()))
    return {
        "tests": [asdict(record) for record in result.tests],
        "fixtures": [asdict(record) for record in result.fixtures],
        "test_like_symbols": [asdict(record) for record in test_like_symbols],
        "syntax_errors": list(result.syntax_errors),
        "warnings": list(result.warnings),
        "counts": {
            "test_files": len(result.tests),
            "test_functions": sum(len(record.test_functions) for record in result.tests),
            "test_classes": sum(len(record.test_classes) for record in result.tests),
            "fixtures": len(result.fixtures),
            "test_like_symbols": len(test_like_symbols),
        },
    }
'''
    if old not in text:
        raise RuntimeError("Could not patch test_inventory_payload.")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_snapshot(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "snapshot.py"
    text = path.read_text(encoding="utf-8")
    text = ensure_import(text, "from codebase_lens.core.redaction import redact_console_text")
    if "def _omitted_files(" not in text:
        marker = "def _python_files_from_universe(universe) -> list[str]:\n"
        helper = r'''
def _omitted_files(universe: object) -> tuple[object, ...]:
    value = getattr(universe, "omitted_files", None)
    if value is None:
        value = getattr(universe, "omissions", ())
    return tuple(value or ())


'''
        if marker not in text:
            raise RuntimeError("Could not find _python_files_from_universe marker.")
        text = text.replace(marker, helper + marker, 1)
    replacement = r'''
def _write_omissions_report(layout: OutputLayout, universe, *, changed_only: bool) -> Path:
    omitted_files = [_jsonable(record) for record in _omitted_files(universe)]
    payload = {
        "schema": {
            "name": "cbl.omissions",
            "version": 2,
        },
        "scope": "changed" if changed_only else "full",
        "omitted_files": omitted_files,
        "omissions": omitted_files,
        "warnings": list(getattr(universe, "warnings", ())),
        "counts": {
            "omitted_files": len(omitted_files),
            "omissions": len(omitted_files),
            "warnings": len(getattr(universe, "warnings", ())),
            "hard_excluded_count": getattr(universe, "counts", {}).get("hard_excluded_count", 0),
            "large_skipped_count": getattr(universe, "counts", {}).get("large_skipped_count", 0),
            "binary_skipped_count": getattr(universe, "counts", {}).get("binary_skipped_count", 0),
            "unsupported_extension_count": getattr(universe, "counts", {}).get("unsupported_extension_count", 0),
            "decode_failed_count": getattr(universe, "counts", {}).get("decode_failed_count", 0),
        },
    }
    return write_json_report(layout.latest_dir / "omissions.json", payload)

'''
    text = replace_function(text, "_write_omissions_report", replacement, "_write_budget_report")
    text = text.replace('"omissions": len(getattr(universe, "omissions", ())),', '"omissions": len(_omitted_files(universe)),')
    text = text.replace(
        'destination.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8", newline="\\n")',
        'destination.write_text(redact_console_text("\\n".join(lines).rstrip() + "\\n"), encoding="utf-8", newline="\\n")',
    )
    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_handoff(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "handoff.py"
    text = path.read_text(encoding="utf-8")
    text = ensure_import(text, "from codebase_lens.core.redaction import redact_console_text")
    text = text.replace('records = payload.get("omissions", [])', 'records = payload.get("omitted_files") or payload.get("omissions", [])')
    text = text.replace('`cbl callers --name <symbol>`', '`cbl callers <symbol>`')
    text = text.replace(
        'handoff_path.write_text("\\n".join(markdown_lines).rstrip() + "\\n", encoding="utf-8", newline="\\n")',
        'handoff_path.write_text(redact_console_text("\\n".join(markdown_lines).rstrip() + "\\n"), encoding="utf-8", newline="\\n")',
    )
    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_graph_query_report(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "graph_query.py"
    text = path.read_text(encoding="utf-8")
    text = ensure_import(text, "from codebase_lens.core.redaction import redact_console_text")
    if "Omitted unresolved edges" not in text:
        text = text.replace(
            'f"- Unresolved edges: {result.counts.get(\'unresolved_edges\', 0)}",',
            'f"- Unresolved edges: {result.counts.get(\'unresolved_edges\', 0)}",\n        f"- Omitted unresolved edges: {result.counts.get(\'omitted_unresolved_edges\', 0)}",\n        f"- Omitted edges by total cap: {result.counts.get(\'omitted_edges_by_limit\', 0)}",',
        )
    text = text.replace('`cbl symbol --name <symbol> --context 80`', '`cbl symbol <symbol> --context 80`')
    text = text.replace('`cbl file --path <path> --lines <start>:<end>`', '`cbl file <path> --lines <start>:<end>`')
    text = text.replace('`cbl callers --name <symbol>`', '`cbl callers <symbol>`')
    text = text.replace(
        'render_graph_query_markdown(result),',
        'redact_console_text(render_graph_query_markdown(result)),',
    )
    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_other_markdown_writers(modified: set[Path]) -> None:
    patches = {
        "src/codebase_lens/reports/symbol_graph.py": (
            "from codebase_lens.reports.manifest import OutputLayout",
            "from codebase_lens.reports.manifest import OutputLayout\nfrom codebase_lens.core.redaction import redact_console_text",
            "render_symbol_graph_markdown(result),",
            "redact_console_text(render_symbol_graph_markdown(result)),",
        ),
        "src/codebase_lens/reports/graph.py": (
            "from codebase_lens.reports.manifest import OutputLayout",
            "from codebase_lens.reports.manifest import OutputLayout\nfrom codebase_lens.core.redaction import redact_console_text",
            "render_graph_summary(graph),",
            "redact_console_text(render_graph_summary(graph)),",
        ),
        "src/codebase_lens/reports/handoff_projection.py": (
            "from codebase_lens.reports.manifest import OutputLayout",
            "from codebase_lens.reports.manifest import OutputLayout\nfrom codebase_lens.core.redaction import redact_console_text",
            "_render_projection_markdown(payload),",
            "redact_console_text(_render_projection_markdown(payload)),",
        ),
    }
    for relative, (old_import, new_import, old_call, new_call) in patches.items():
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        if "redact_console_text" not in text:
            if old_import not in text:
                raise RuntimeError(f"Could not find import marker in {relative}")
            text = text.replace(old_import, new_import, 1)
        text = text.replace(old_call, new_call)
        # Also correct bad suggested commands in graph.py.
        text = text.replace('`cbl symbol --name <symbol> --context 80`', '`cbl symbol <symbol> --context 80`')
        text = text.replace('`cbl file --path <path> --lines <start>:<end>`', '`cbl file <path> --lines <start>:<end>`')
        text = text.replace('`cbl callers --name <symbol>`', '`cbl callers <symbol>`')
        path.write_text(text, encoding="utf-8", newline="\n")
        modified.add(path)


def patch_symbol_graph(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "analyzers" / "symbol_graph.py"
    text = path.read_text(encoding="utf-8")
    text = replace_between_functions(text, "_calls_for", "_imports_for", SYMBOL_GRAPH_CALLS_FOR)
    text = replace_between_functions(text, "_iter_symbols", "_likely_tests_for", SYMBOL_GRAPH_ITER)
    text = replace_between_functions(text, "_resolve_call_targets", "collect_symbol_graph", SYMBOL_GRAPH_RESOLVE)
    text = text.replace('node.kind in {"function", "async_function"}', 'node.kind in {"function", "async_function", "method", "async_method"}')
    text = text.replace('if node.kind == "method"', 'if node.kind in {"method", "async_method"}')
    # Deduplicate import lookup lists after construction by making resolver dedupe; dedupe callers before attaching.
    old = '''    callers_by_target: dict[str, list[CallerEdge]] = {}
    for source in raw_symbols:
        for call in source.calls:
            targets = _resolve_call_targets(
                source,
                call,
                symbols_by_file_simple=symbols_by_file_simple,
                symbols_by_import_name=symbols_by_import_name,
            )
            for target in targets:
                if source.path == target.path and source.qualified_name == target.qualified_name:
                    continue

                target_id = _symbol_id(target.path, target.qualified_name, target.start_line, target.end_line)
                callers_by_target.setdefault(target_id, []).append(
                    CallerEdge(
                        symbol=source.qualified_name,
                        path=source.path,
                        line=call.line,
                        confidence=call.confidence,
                    )
                )
'''
    new = '''    callers_by_target: dict[str, list[CallerEdge]] = {}
    caller_seen: set[tuple[str, str, str, int, str]] = set()
    for source in raw_symbols:
        for call in source.calls:
            targets = _resolve_call_targets(
                source,
                call,
                symbols_by_file_simple=symbols_by_file_simple,
                symbols_by_import_name=symbols_by_import_name,
            )
            for target in targets:
                if source.path == target.path and source.qualified_name == target.qualified_name:
                    continue

                target_id = _symbol_id(target.path, target.qualified_name, target.start_line, target.end_line)
                key = (target_id, source.path, source.qualified_name, call.line, call.confidence)
                if key in caller_seen:
                    continue
                caller_seen.add(key)
                callers_by_target.setdefault(target_id, []).append(
                    CallerEdge(
                        symbol=source.qualified_name,
                        path=source.path,
                        line=call.line,
                        confidence=call.confidence,
                    )
                )
'''
    if old not in text:
        raise RuntimeError("Could not patch caller-edge dedupe block in symbol_graph.py")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_cli(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "cli.py"
    text = path.read_text(encoding="utf-8")
    if 'graph.add_argument("--unresolved"' not in text:
        marker = '    graph.add_argument("--changed", action="store_true", help="Seed query from changed hunks and changed symbols.")\n'
        if marker not in text:
            raise RuntimeError("Could not find graph --changed marker.")
        text = text.replace(
            marker,
            marker + '    graph.add_argument("--unresolved", choices=("seed", "selected", "none"), default="seed", help="Control unresolved call-name edges in graph query output.")\n',
            1,
        )
    old = '''            changed=args.changed,
            depth=args.depth,
            limit=args.limit,
        )
'''
    new = '''            changed=args.changed,
            depth=args.depth,
            limit=args.limit,
            unresolved_mode=args.unresolved,
        )
'''
    if old in text:
        text = text.replace(old, new, 1)
    elif "unresolved_mode=args.unresolved" not in text:
        raise RuntimeError("Could not patch graph query unresolved_mode argument.")
    path.write_text(text, encoding="utf-8", newline="\n")
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
    for required in ["scripts/dev/audits/audit_phase27_reliability_corrections.py"]:
        if f'"{required}"' not in text and f"'{required}'" not in text:
            text = insert_before_list_close(text, "required_files", f'            "{required}",\n')
    entries = [
        ("src/codebase_lens/core/redaction.py", ["redact_jsonable", "redact_string"]),
        ("src/codebase_lens/analyzers/tests.py", ["classify_test_path", "TestLikeSymbolRecord"]),
    ]
    insertions = ""
    for rel, symbols in entries:
        if f'"path": "{rel}"' in text:
            continue
        rendered = "\n".join(f'                    "{symbol}",' for symbol in symbols)
        insertions += (
            "            {\n"
            f'                "path": "{rel}",\n'
            '                "symbols": [\n'
            f"{rendered}\n"
            "                ],\n"
            "            },\n"
        )
    if insertions:
        text = insert_before_list_close(text, "required_symbols", insertions)
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

    write_file("src/codebase_lens/scanners/inventory.py", SCANNER_INVENTORY, modified)
    write_file("src/codebase_lens/scanners/tree.py", SCANNER_TREE, modified)
    write_file("src/codebase_lens/analyzers/tests.py", ANALYZERS_TESTS, modified)
    write_file("src/codebase_lens/analyzers/graph_query.py", ANALYZERS_GRAPH_QUERY, modified)
    write_file("scripts/dev/audits/audit_phase27_reliability_corrections.py", AUDIT, modified)
    write_file("tests/test_reliability_corrections.py", TEST, modified)

    patch_universe(modified)
    patch_redaction(modified)
    patch_manifest(modified)
    patch_reports_json(modified)
    patch_snapshot(modified)
    patch_handoff(modified)
    patch_graph_query_report(modified)
    patch_other_markdown_writers(modified)
    patch_symbol_graph(modified)
    patch_cli(modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 022 applied: reliability corrections and AI-facing fidelity hardening added.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
