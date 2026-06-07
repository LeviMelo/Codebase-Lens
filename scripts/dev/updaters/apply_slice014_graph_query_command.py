from __future__ import annotations

import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/analyzers/graph_query.py": r'''
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphQueryResult:
    query: dict[str, Any]
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    counts: dict[str, int]
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


def _selected_edges(edges: list[dict[str, Any]], selected_ids: set[str], *, include_unresolved_for_selected: bool = True) -> tuple[dict[str, Any], ...]:
    values: list[dict[str, Any]] = []

    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")

        if source in selected_ids and target in selected_ids:
            values.append(edge)
            continue

        if include_unresolved_for_selected and source in selected_ids and not target:
            values.append(edge)

    by_id: dict[str, dict[str, Any]] = {}
    for edge in values:
        by_id[str(edge.get("id"))] = edge

    return tuple(sorted(by_id.values(), key=lambda item: (str(item.get("kind")), str(item.get("source")), str(item.get("target") or ""), str(item.get("target_text") or ""))))


def query_evidence_graph_payload(
    graph_payload: dict[str, Any],
    *,
    symbol: str | None = None,
    path: str | None = None,
    module: str | None = None,
    changed: bool = False,
    depth: int = 1,
    limit: int = 60,
) -> GraphQueryResult:
    nodes = [node for node in graph_payload.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in graph_payload.get("edges", []) if isinstance(edge, dict)]

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
    selected_edges = _selected_edges(edges, selected_ids)

    selected_nodes = sorted(
        selected_nodes,
        key=lambda node: (
            0 if _node_path(node).startswith("src/codebase_lens/") else 1,
            str(node.get("kind")),
            _node_path(node),
            _node_label(node),
        ),
    )[: max(limit, len(seed_ids))]

    retained_ids = {_node_id(node) for node in selected_nodes}
    selected_edges = tuple(
        edge
        for edge in selected_edges
        if str(edge.get("source") or "") in retained_ids
        and (not edge.get("target") or str(edge.get("target")) in retained_ids)
    )

    edge_kinds = Counter(str(edge.get("kind")) for edge in selected_edges)
    node_kinds = Counter(str(node.get("kind")) for node in selected_nodes)

    return GraphQueryResult(
        query={
            "symbol": symbol,
            "path": path,
            "module": module,
            "changed": changed,
            "depth": depth,
            "limit": limit,
            "seed_count": len(seed_ids),
        },
        nodes=tuple(selected_nodes),
        edges=selected_edges,
        counts={
            "nodes": len(selected_nodes),
            "edges": len(selected_edges),
            "seed_nodes": len(seed_ids),
            "unresolved_edges": sum(1 for edge in selected_edges if not edge.get("target")),
            "node_kinds": dict(sorted(node_kinds.items())),
            "edge_kinds": dict(sorted(edge_kinds.items())),
        },
        warnings=tuple(warnings),
    )


def graph_query_payload(result: GraphQueryResult) -> dict[str, Any]:
    return {
        "schema": {
            "name": "cbl.graph_query",
            "version": 1,
        },
        "query": dict(result.query),
        "nodes": list(result.nodes),
        "edges": list(result.edges),
        "counts": dict(result.counts),
        "warnings": list(result.warnings),
    }
''',

    "src/codebase_lens/reports/graph_query.py": r'''
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
''',

    "tests/test_graph_query_integration.py": r'''
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
    repo = tmp_path / "graph_query_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'graph-query-repo'\n", encoding="utf-8")
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


def test_graph_command_queries_symbol_neighborhood(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("graph", "--repo", str(repo), "--symbol", "transform", "--depth", "2", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL graph: OK" in result.stdout

    latest = repo / ".codecontext" / "latest"
    query_json = latest / "graph_query.json"
    query_md = latest / "graph_query.md"
    evidence_graph = latest / "evidence_graph.json"

    assert query_json.is_file()
    assert query_md.is_file()
    assert evidence_graph.is_file()

    payload = json.loads(query_json.read_text(encoding="utf-8"))
    labels = {node["label"] for node in payload["nodes"]}

    assert "transform" in labels
    assert "double" in labels or "run" in labels
    assert payload["counts"]["nodes"] > 0
    assert payload["counts"]["edges"] > 0

    markdown = query_md.read_text(encoding="utf-8")
    assert "# CBL Graph Query" in markdown
    assert "## Follow-Up Commands" in markdown
    assert "transform" in markdown


def test_graph_command_reports_empty_match_without_failure(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("graph", "--repo", str(repo), "--symbol", "does_not_exist", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads((repo / ".codecontext" / "latest" / "graph_query.json").read_text(encoding="utf-8"))
    assert payload["counts"]["nodes"] == 0
    assert payload["warnings"] == ["No graph nodes matched the requested query."]
''',

    "scripts/dev/audits/audit_phase12_graph_query.py": r'''
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
    "src/codebase_lens/analyzers/graph_query.py": [
        "GraphQueryResult",
        "query_evidence_graph_payload",
        "graph_query_payload",
    ],
    "src/codebase_lens/reports/graph_query.py": [
        "write_graph_query_reports",
        "render_graph_query_markdown",
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

    help_result = run_cbl("--help")
    if help_result.returncode != 0:
        fail("cbl --help failed.")
    if "graph" not in help_result.stdout:
        fail("cbl --help does not expose graph command.")

    graph = run_cbl("graph", "--symbol", "write_handoff_pack", "--depth", "2", "--budget", "24000", "--no-archive")
    if graph.returncode != 0:
        fail(f"cbl graph failed:\nSTDOUT:\n{graph.stdout}\nSTDERR:\n{graph.stderr}")

    if "CBL graph: OK" not in graph.stdout:
        fail("graph command did not report success.")

    latest = ROOT / ".codecontext" / "latest"
    for name in ["graph_query.json", "graph_query.md", "evidence_graph.json", "graph_summary.md", "manifest.json"]:
        if not (latest / name).is_file():
            fail(f"Missing graph command output: {name}")

    payload = json.loads((latest / "graph_query.json").read_text(encoding="utf-8"))
    labels = {node.get("label") for node in payload.get("nodes", []) if isinstance(node, dict)}

    if "write_handoff_pack" not in labels:
        fail("graph query did not include requested symbol write_handoff_pack.")

    if payload.get("counts", {}).get("edges", 0) <= 0:
        fail("graph query returned no edges for write_handoff_pack.")

    markdown = (latest / "graph_query.md").read_text(encoding="utf-8")
    for marker in ["# CBL Graph Query", "## Nodes", "## Edges", "## Follow-Up Commands"]:
        if marker not in markdown:
            fail(f"graph_query.md missing marker: {marker}")

    if "C:\\Users\\" in markdown:
        fail("graph_query.md leaked an absolute Windows user path.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 12 graph query audit passed.")
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


def patch_cli_parser() -> None:
    path = ROOT / "src" / "codebase_lens" / "cli.py"
    text = path.read_text(encoding="utf-8")

    if 'sub.add_parser("graph"' in text or "sub.add_parser('graph'" in text:
        return

    build_start = text.find("def build_parser(")
    if build_start == -1:
        raise RuntimeError("Could not find build_parser() in cli.py.")

    return_marker = "    return parser\n"
    return_pos = text.find(return_marker, build_start)
    if return_pos == -1:
        raise RuntimeError("Could not find return parser inside build_parser().")

    block = '''    graph = sub.add_parser("graph", parents=[parent], help="Query scoped evidence graph neighborhoods.")
    graph.add_argument("--symbol", help="Symbol name or substring to seed the graph query.")
    graph.add_argument("--path", help="Repository-relative path to seed the graph query.")
    graph.add_argument("--module", help="Module name or substring to seed the graph query.")
    graph.add_argument("--depth", type=int, default=1, help="Undirected graph expansion depth from seed nodes.")
    graph.add_argument("--limit", type=int, default=60, help="Maximum nodes to retain in the markdown-oriented query view.")
    graph.add_argument("--changed", action="store_true", help="Seed query from changed hunks and changed symbols.")
    graph.set_defaults(handler=_run_graph)

'''

    text = text[:return_pos] + block + text[return_pos:]
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_cli_handler() -> None:
    path = ROOT / "src" / "codebase_lens" / "cli.py"
    text = path.read_text(encoding="utf-8")

    if "def _run_graph(" in text:
        return

    marker = "\ndef _run_pack("
    insert_pos = text.find(marker)
    if insert_pos == -1:
        marker = "\ndef _run_contract("
        insert_pos = text.find(marker)

    if insert_pos == -1:
        raise RuntimeError("Could not find insertion point for _run_graph() in cli.py.")

    handler = r'''

def _run_graph(args: argparse.Namespace) -> int:
    try:
        import json

        from codebase_lens.analyzers.graph_query import query_evidence_graph_payload
        from codebase_lens.reports.graph_query import write_graph_query_reports
        from codebase_lens.reports.snapshot import write_snapshot_bundle

        root_info = _detect_root(args)
        repo_root = root_info.root
        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        snapshot_result = write_snapshot_bundle(
            layout,
            repo_root,
            max_file_bytes=args.max_file_bytes,
            changed_only=args.changed,
            budget=args.budget,
            focus_terms=tuple(args.focus),
        )

        graph_payload = json.loads((layout.latest_dir / "evidence_graph.json").read_text(encoding="utf-8"))

        query_result = query_evidence_graph_payload(
            graph_payload,
            symbol=args.symbol,
            path=args.path,
            module=args.module,
            changed=args.changed,
            depth=args.depth,
            limit=args.limit,
        )

        outputs = dict(snapshot_result.outputs)
        outputs.update(write_graph_query_reports(layout, query_result))

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "graph",
                outputs,
            )
        )
        write_manifest_bundle(layout, manifest)

        if not args.no_archive:
            copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"CBL graph: ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except PathSafetyError as exc:
        print(redact_console_text(f"CBL graph: ERROR: {exc}"))
        return EXIT_PATH_SAFETY_VIOLATION
    except ValueError as exc:
        print(redact_console_text(f"CBL graph: ERROR: {exc}"))
        return EXIT_INVALID_ARGUMENTS
    except OSError as exc:
        print(redact_console_text(f"CBL graph: ERROR: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except Exception as exc:
        print(redact_console_text(f"CBL graph: ERROR: {type(exc).__name__}: {exc}"))
        return EXIT_GENERAL_ERROR

    print(redact_console_text("CBL graph: OK"))
    print(redact_console_text(f"Selected nodes: {query_result.counts['nodes']}"))
    print(redact_console_text(f"Selected edges: {query_result.counts['edges']}"))
    print(redact_console_text(f"Graph query: {display_path(repo_root, layout.latest_dir / 'graph_query.md')}"))
    print(redact_console_text(f"Graph query JSON: {display_path(repo_root, layout.latest_dir / 'graph_query.json')}"))
    print(redact_console_text(f"Evidence graph: {display_path(repo_root, layout.latest_dir / 'evidence_graph.json')}"))
    return 0

'''

    text = text[:insert_pos] + handler + text[insert_pos:]
    path.write_text(text, encoding="utf-8", newline="\n")


def find_key_list_bounds(text: str, key: str) -> tuple[int, int]:
    pattern = re.compile(rf'(?P<quote>["\']){re.escape(key)}(?P=quote)\s*:\s*\[')
    match = pattern.search(text)
    if match is None:
        raise RuntimeError(f"Could not find list-valued key {key!r} in architecture.py.")

    open_index = text.find("[", match.start())
    if open_index == -1:
        raise RuntimeError(f"Could not find opening list bracket for {key!r}.")

    depth = 0
    quote: str | None = None
    escaped = False
    triple = False
    i = open_index

    while i < len(text):
        ch = text[i]

        if quote is not None:
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if triple:
                if text.startswith(quote * 3, i):
                    quote = None
                    triple = False
                    i += 3
                    continue
                i += 1
                continue
            if ch == quote:
                quote = None
            i += 1
            continue

        if ch in {"'", '"'}:
            quote = ch
            if text.startswith(ch * 3, i):
                triple = True
                i += 3
            else:
                triple = False
                i += 1
            continue

        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return open_index, i

        i += 1

    raise RuntimeError(f"Could not find closing list bracket for {key!r}.")


def insert_before_list_close(text: str, key: str, block: str) -> str:
    _, close_index = find_key_list_bounds(text, key)
    return text[:close_index] + block + text[close_index:]


def required_symbols_block(path: str, symbols: list[str]) -> str:
    lines = [
        "            {",
        f'                "path": "{path}",',
        '                "symbols": [',
    ]
    for symbol in symbols:
        lines.append(f'                    "{symbol}",')
    lines.extend(
        [
            "                ],",
            "            },",
        ]
    )
    return "\n".join(lines) + "\n"


def patch_contract() -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    required_files = [
        "src/codebase_lens/analyzers/graph_query.py",
        "src/codebase_lens/reports/graph_query.py",
        "scripts/dev/audits/audit_phase12_graph_query.py",
    ]

    missing_files = [item for item in required_files if f'"{item}"' not in text and f"'{item}'" not in text]
    if missing_files:
        block = "".join(f'            "{item}",\n' for item in missing_files)
        text = insert_before_list_close(text, "required_files", block)

    symbol_entries = [
        (
            "src/codebase_lens/analyzers/graph_query.py",
            ["GraphQueryResult", "query_evidence_graph_payload", "graph_query_payload"],
        ),
        (
            "src/codebase_lens/reports/graph_query.py",
            ["write_graph_query_reports", "render_graph_query_markdown"],
        ),
    ]

    blocks: list[str] = []
    for entry_path, symbols in symbol_entries:
        if f'"path": "{entry_path}"' in text or f"'path': '{entry_path}'" in text:
            continue
        blocks.append(required_symbols_block(entry_path, symbols))

    if blocks:
        text = insert_before_list_close(text, "required_symbols", "".join(blocks))

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_command_lists() -> None:
    targets = [
        ROOT / "scripts" / "dev" / "audits" / "audit_v01_readiness.py",
        ROOT / "tests" / "test_phase0_cli.py",
    ]

    for path in targets:
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")
        if '"graph"' in text or "'graph'" in text:
            continue

        if '"pack",' in text:
            text = text.replace('"pack",', '"pack",\n    "graph",', 1)
        elif "'pack'," in text:
            text = text.replace("'pack',", "'pack',\n    'graph',", 1)
        elif '"clean",' in text:
            text = text.replace('"clean",', '"graph",\n    "clean",', 1)

        path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_cli_parser()
    patch_cli_handler()
    patch_contract()
    patch_command_lists()

    print("Slice 014 applied: cbl graph scoped query command implemented.")
    print("Run Phase 12 audit, Phase 11 audit, prior audits, contract, pytest, and git diff --check before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())