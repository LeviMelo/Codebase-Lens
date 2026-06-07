from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/analyzers/symbol_graph.py": r'''
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SymbolInput:
    name: str
    annotation: str | None
    default: str | None
    kind: str


@dataclass(frozen=True)
class ReturnObservation:
    line: int
    expression: str


@dataclass(frozen=True)
class CallEdge:
    name: str
    line: int
    confidence: str


@dataclass(frozen=True)
class CallerEdge:
    symbol: str
    path: str
    line: int
    confidence: str


@dataclass(frozen=True)
class SymbolGraphNode:
    symbol_id: str
    qualified_name: str
    simple_name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    signature: str
    inputs: tuple[SymbolInput, ...]
    returns_annotation: str | None
    observed_returns: tuple[ReturnObservation, ...]
    calls: tuple[CallEdge, ...]
    called_by: tuple[CallerEdge, ...]
    imports_used: tuple[str, ...]
    tests_likely_covering: tuple[str, ...]
    evidence: tuple[str, ...]
    confidence: str


@dataclass(frozen=True)
class SymbolGraphResult:
    nodes: tuple[SymbolGraphNode, ...]
    counts: dict[str, int]
    syntax_errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _RawSymbol:
    qualified_name: str
    simple_name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    signature: str
    inputs: tuple[SymbolInput, ...]
    returns_annotation: str | None
    observed_returns: tuple[ReturnObservation, ...]
    calls: tuple[CallEdge, ...]
    imported_names: dict[str, str]


def _unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _line_slice(lines: list[str], start_line: int, end_line: int) -> str:
    if start_line < 1 or end_line < start_line:
        return ""
    return "\n".join(lines[start_line - 1 : end_line])


def _signature_for(node: ast.AST, lines: list[str]) -> str:
    start = getattr(node, "lineno", 1)
    end = start
    raw = _line_slice(lines, start, min(start + 12, len(lines)))
    collected: list[str] = []

    depth = 0
    for offset, line in enumerate(raw.splitlines(), start=start):
        stripped = line.strip()
        collected.append(stripped)
        depth += stripped.count("(") + stripped.count("[") + stripped.count("{")
        depth -= stripped.count(")") + stripped.count("]") + stripped.count("}")
        if stripped.endswith(":") and depth <= 0:
            end = offset
            break

    text = " ".join(part for part in collected if part)
    return text[:500]


def _defaults_by_arg(args: list[ast.arg], defaults: list[ast.expr]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {arg.arg: None for arg in args}
    if not defaults:
        return mapping

    aligned = [None] * (len(args) - len(defaults)) + list(defaults)
    for arg, default in zip(args, aligned):
        mapping[arg.arg] = _unparse(default) if default is not None else None
    return mapping


def _inputs_for(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[SymbolInput, ...]:
    values: list[SymbolInput] = []
    args = node.args

    positional = list(args.posonlyargs) + list(args.args)
    positional_defaults = _defaults_by_arg(positional, list(args.defaults))

    for arg in args.posonlyargs:
        values.append(SymbolInput(arg.arg, _unparse(arg.annotation), positional_defaults.get(arg.arg), "positional_only"))

    for arg in args.args:
        values.append(SymbolInput(arg.arg, _unparse(arg.annotation), positional_defaults.get(arg.arg), "positional_or_keyword"))

    if args.vararg is not None:
        values.append(SymbolInput(args.vararg.arg, _unparse(args.vararg.annotation), None, "varargs"))

    keyword_defaults = {
        arg.arg: (_unparse(default) if default is not None else None)
        for arg, default in zip(args.kwonlyargs, args.kw_defaults)
    }
    for arg in args.kwonlyargs:
        values.append(SymbolInput(arg.arg, _unparse(arg.annotation), keyword_defaults.get(arg.arg), "keyword_only"))

    if args.kwarg is not None:
        values.append(SymbolInput(args.kwarg.arg, _unparse(args.kwarg.annotation), None, "kwargs"))

    return tuple(values)


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = [func.attr]
        current: ast.AST = func.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)
    return _unparse(func)


def _calls_for(node: ast.AST) -> tuple[CallEdge, ...]:
    values: list[CallEdge] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _call_name(child)
            if not name:
                continue
            confidence = "medium" if "." in name else "high"
            values.append(CallEdge(name=name, line=getattr(child, "lineno", 0), confidence=confidence))
    return tuple(values)


def _returns_for(node: ast.AST) -> tuple[ReturnObservation, ...]:
    values: list[ReturnObservation] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Return):
            expression = _unparse(child.value) if child.value is not None else "None"
            values.append(ReturnObservation(line=getattr(child, "lineno", 0), expression=(expression or "<unparseable>")[:300]))
    return tuple(values)


def _imports_for(tree: ast.Module) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                values[local] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                full = f"{module}.{alias.name}" if module else alias.name
                values[local] = full
    return values


def _imports_used(calls: tuple[CallEdge, ...], imported_names: dict[str, str]) -> tuple[str, ...]:
    used: set[str] = set()
    for call in calls:
        base = call.name.split(".", 1)[0]
        if base in imported_names:
            used.add(imported_names[base])
    return tuple(sorted(used))


def _symbol_id(path: str, qualified_name: str, start_line: int, end_line: int) -> str:
    return f"{path}:{qualified_name}:L{start_line}-L{end_line}"


def _iter_symbols(tree: ast.Module, path: str, lines: list[str]) -> tuple[_RawSymbol, ...]:
    imported_names = _imports_for(tree)
    symbols: list[_RawSymbol] = []

    def visit_body(body: list[ast.stmt], prefix: tuple[str, ...]) -> None:
        for item in body:
            if isinstance(item, ast.ClassDef):
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
                visit_body(item.body, (*prefix, item.name))

            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join((*prefix, item.name))
                symbols.append(
                    _RawSymbol(
                        qualified_name=qualified,
                        simple_name=item.name,
                        kind="async_function" if isinstance(item, ast.AsyncFunctionDef) else "function",
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

                visit_body(item.body, (*prefix, item.name))

    visit_body(tree.body, ())
    return tuple(symbols)


def _likely_tests_for(raw: _RawSymbol, all_paths: tuple[str, ...]) -> tuple[str, ...]:
    simple = raw.simple_name.lower()
    module_stem = Path(raw.path).stem.lower()
    values: list[str] = []

    for path in all_paths:
        normalized = path.replace("\\", "/").lower()
        if "/tests/" not in f"/{normalized}" and not normalized.startswith("tests/"):
            continue
        if simple in normalized or module_stem in normalized:
            values.append(path)

    return tuple(sorted(set(values)))


def _call_matches_symbol(call_name: str, target: _RawSymbol) -> bool:
    if call_name == target.simple_name:
        return True
    if call_name == target.qualified_name:
        return True
    if call_name.endswith(f".{target.simple_name}"):
        return True
    return False


def collect_symbol_graph(
    repo_root: str | Path,
    python_files: list[str],
    *,
    focus_paths: set[str] | None = None,
    focus_terms: tuple[str, ...] = (),
) -> SymbolGraphResult:
    root = Path(repo_root).resolve()
    syntax_errors: list[str] = []
    warnings: list[str] = []
    raw_symbols: list[_RawSymbol] = []
    all_paths = tuple(sorted(set(python_files)))

    for relative_path in sorted(set(python_files)):
        file_path = root / relative_path
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            warnings.append(f"{relative_path}: could not read file: {exc}")
            continue

        try:
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError as exc:
            syntax_errors.append(f"{relative_path}:L{exc.lineno or 0}: {exc.msg}")
            continue

        raw_symbols.extend(_iter_symbols(tree, relative_path, source.splitlines()))

    callers_by_target: dict[str, list[CallerEdge]] = {}
    for source in raw_symbols:
        for call in source.calls:
            for target in raw_symbols:
                if source.path == target.path and source.qualified_name == target.qualified_name:
                    continue
                if _call_matches_symbol(call.name, target):
                    target_id = _symbol_id(target.path, target.qualified_name, target.start_line, target.end_line)
                    callers_by_target.setdefault(target_id, []).append(
                        CallerEdge(
                            symbol=source.qualified_name,
                            path=source.path,
                            line=call.line,
                            confidence=call.confidence,
                        )
                    )

    focus_paths = focus_paths or set()

    nodes: list[SymbolGraphNode] = []
    for raw in raw_symbols:
        sid = _symbol_id(raw.path, raw.qualified_name, raw.start_line, raw.end_line)
        evidence = (f"{raw.path}:L{raw.start_line}-L{raw.end_line}",)

        confidence = "static_heuristic"
        if focus_paths and raw.path in focus_paths:
            confidence = "static_heuristic_focus_path"

        if focus_terms and any(term.lower() in raw.qualified_name.lower() or term.lower() in raw.path.lower() for term in focus_terms):
            confidence = "static_heuristic_focus_term"

        nodes.append(
            SymbolGraphNode(
                symbol_id=sid,
                qualified_name=raw.qualified_name,
                simple_name=raw.simple_name,
                kind=raw.kind,
                path=raw.path,
                start_line=raw.start_line,
                end_line=raw.end_line,
                signature=raw.signature,
                inputs=raw.inputs,
                returns_annotation=raw.returns_annotation,
                observed_returns=raw.observed_returns[:20],
                calls=raw.calls[:80],
                called_by=tuple(callers_by_target.get(sid, ()))[:80],
                imports_used=_imports_used(raw.calls, raw.imported_names),
                tests_likely_covering=_likely_tests_for(raw, all_paths),
                evidence=evidence,
                confidence=confidence,
            )
        )

    return SymbolGraphResult(
        nodes=tuple(nodes),
        counts={
            "nodes": len(nodes),
            "functions": sum(1 for node in nodes if node.kind in {"function", "async_function"}),
            "classes": sum(1 for node in nodes if node.kind == "class"),
            "call_edges": sum(len(node.calls) for node in nodes),
            "caller_edges": sum(len(node.called_by) for node in nodes),
            "syntax_errors": len(syntax_errors),
            "warnings": len(warnings),
        },
        syntax_errors=tuple(syntax_errors),
        warnings=tuple(warnings),
    )


def symbol_graph_payload(result: SymbolGraphResult) -> dict[str, Any]:
    return {
        "schema": {
            "name": "cbl.symbol_graph",
            "version": 1,
        },
        "nodes": [asdict(node) for node in result.nodes],
        "counts": dict(result.counts),
        "syntax_errors": list(result.syntax_errors),
        "warnings": list(result.warnings),
    }


def _node_priority(node: SymbolGraphNode) -> tuple[int, int, int, str]:
    focus_score = 2 if "focus" in node.confidence else 0
    connectivity = len(node.called_by) + len(node.calls)
    span = node.end_line - node.start_line
    return (-focus_score, -connectivity, -span, node.path)


def render_symbol_graph_markdown(result: SymbolGraphResult, *, max_nodes: int = 80) -> str:
    lines: list[str] = [
        "# CBL Symbol Relationship Graph",
        "",
        "Evidence scope: static Python AST analysis",
        f"Nodes: {result.counts.get('nodes', 0)}",
        f"Functions: {result.counts.get('functions', 0)}",
        f"Classes: {result.counts.get('classes', 0)}",
        f"Call edges: {result.counts.get('call_edges', 0)}",
        f"Caller edges: {result.counts.get('caller_edges', 0)}",
        "",
    ]

    if result.syntax_errors:
        lines.extend(["## Syntax Errors", ""])
        lines.extend(f"- {item}" for item in result.syntax_errors[:40])
        lines.append("")

    nodes = sorted(result.nodes, key=_node_priority)
    if not nodes:
        lines.extend(
            [
                "## Nodes",
                "",
                "No Python symbols were analyzed for this scope.",
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(["## Symbol Nodes", ""])

    for node in nodes[:max_nodes]:
        lines.extend(
            [
                f"### `{node.qualified_name}`",
                "",
                f"- Kind: `{node.kind}`",
                f"- Declared: `{node.path}:L{node.start_line}-L{node.end_line}`",
                f"- Signature: `{node.signature}`",
                f"- Returns: `{node.returns_annotation or 'unannotated'}`",
                f"- Confidence: `{node.confidence}`",
            ]
        )

        if node.inputs:
            rendered_inputs = []
            for item in node.inputs[:12]:
                annotation = f": {item.annotation}" if item.annotation else ""
                default = f" = {item.default}" if item.default is not None else ""
                rendered_inputs.append(f"`{item.name}{annotation}{default}`")
            lines.append(f"- Inputs: {', '.join(rendered_inputs)}")
        else:
            lines.append("- Inputs: none detected")

        if node.observed_returns:
            returns = [f"`L{item.line}: {item.expression}`" for item in node.observed_returns[:8]]
            lines.append(f"- Observed returns: {', '.join(returns)}")
        else:
            lines.append("- Observed returns: none detected")

        if node.calls:
            calls = [f"`{item.name}`@L{item.line}" for item in node.calls[:12]]
            lines.append(f"- Calls: {', '.join(calls)}")
        else:
            lines.append("- Calls: none detected")

        if node.called_by:
            callers = [f"`{item.symbol}` → `{item.path}:L{item.line}`" for item in node.called_by[:12]]
            lines.append(f"- Called by: {', '.join(callers)}")
        else:
            lines.append("- Called by: none detected")

        if node.imports_used:
            lines.append(f"- Imports used: {', '.join(f'`{item}`' for item in node.imports_used[:12])}")

        if node.tests_likely_covering:
            lines.append(f"- Likely tests: {', '.join(f'`{item}`' for item in node.tests_likely_covering[:12])}")

        lines.extend(["", f"Evidence: `{node.evidence[0]}`", ""])

    if len(nodes) > max_nodes:
        lines.append(f"... {len(nodes) - max_nodes} additional symbol nodes omitted from markdown; see `symbol_graph.json`.")

    return "\n".join(lines).rstrip() + "\n"
''',

    "src/codebase_lens/reports/symbol_graph.py": r'''
from __future__ import annotations

from pathlib import Path

from codebase_lens.analyzers.symbol_graph import (
    SymbolGraphResult,
    render_symbol_graph_markdown,
    symbol_graph_payload,
)
from codebase_lens.reports.json import write_json_report
from codebase_lens.reports.manifest import OutputLayout


def write_symbol_graph_reports(layout: OutputLayout, result: SymbolGraphResult) -> dict[str, str]:
    json_path = layout.latest_dir / "symbol_graph.json"
    markdown_path = layout.latest_dir / "symbol_graph.md"

    write_json_report(json_path, symbol_graph_payload(result))
    markdown_path.write_text(
        render_symbol_graph_markdown(result),
        encoding="utf-8",
        newline="\n",
    )

    return {
        "symbol_graph_json": ".codecontext/latest/symbol_graph.json",
        "symbol_graph_md": ".codecontext/latest/symbol_graph.md",
    }
''',

    "tests/test_symbol_graph_integration.py": r'''
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
    repo = tmp_path / "symbol_graph_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'symbol-graph-repo'\n", encoding="utf-8")

    (package / "service.py").write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "",
                "class Worker:",
                "    def run(self, value: int) -> int:",
                "        return transform(value)",
                "",
                "def transform(value: int) -> int:",
                "    output = helper(value)",
                "    return output + 1",
                "",
                "def helper(value: int) -> int:",
                "    return value * 2",
                "",
                "def write_result(path: Path, value: int) -> None:",
                "    path.write_text(str(transform(value)))",
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


def test_pack_writes_symbol_graph_and_handoff_uses_it(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("pack", "--repo", str(repo), "--issue", "graph test", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL pack: OK" in result.stdout

    latest = repo / ".codecontext" / "latest"
    graph_json = latest / "symbol_graph.json"
    graph_md = latest / "symbol_graph.md"
    handoff = latest / "ai_handoff.md"

    assert graph_json.is_file()
    assert graph_md.is_file()
    assert handoff.is_file()

    payload = json.loads(graph_json.read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    by_name = {node["qualified_name"]: node for node in nodes}

    assert "transform" in by_name
    assert "helper" in by_name
    assert "Worker.run" in by_name

    transform = by_name["transform"]
    assert transform["inputs"][0]["name"] == "value"
    assert transform["inputs"][0]["annotation"] == "int"
    assert transform["returns_annotation"] == "int"
    assert any(call["name"] == "helper" for call in transform["calls"])
    assert any(caller["symbol"] == "Worker.run" for caller in transform["called_by"])

    handoff_text = handoff.read_text(encoding="utf-8")
    assert "## Symbol Relationship Graph" in handoff_text
    assert "`transform`" in handoff_text
    assert "`helper`" in handoff_text
    assert "graph test" in handoff_text


def test_changed_pack_on_clean_repo_warns_that_scope_is_empty(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, text=True, capture_output=True, check=False)

    result = run_cbl("pack", "--repo", str(repo), "--changed", "--issue", "clean changed pack", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    handoff = (repo / ".codecontext" / "latest" / "ai_handoff.md").read_text(encoding="utf-8")
    assert "No Git changes detected for this changed-only pack." in handoff
    assert "cbl pack --budget" in handoff
''',

    "scripts/dev/audits/audit_phase10_symbol_graph.py": r'''
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
    "src/codebase_lens/analyzers/symbol_graph.py": [
        "SymbolGraphNode",
        "SymbolGraphResult",
        "collect_symbol_graph",
        "symbol_graph_payload",
        "render_symbol_graph_markdown",
    ],
    "src/codebase_lens/reports/symbol_graph.py": [
        "write_symbol_graph_reports",
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

    pack = run_cbl("pack", "--issue", "phase 10 symbol graph audit", "--budget", "20000", "--no-archive")
    if pack.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")
    if "CBL pack: OK" not in pack.stdout:
        fail("pack did not report success.")

    latest = ROOT / ".codecontext" / "latest"
    graph_json = latest / "symbol_graph.json"
    graph_md = latest / "symbol_graph.md"
    handoff = latest / "ai_handoff.md"

    for path in [graph_json, graph_md, handoff]:
        if not path.is_file():
            fail(f"Missing expected output: {path.name}")

    payload = json.loads(graph_json.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", [])
    if not nodes:
        fail("symbol_graph.json has no nodes for the CBL repository.")

    names = {node.get("qualified_name") for node in nodes if isinstance(node, dict)}
    required_names = {"write_handoff_pack", "write_snapshot_bundle", "collect_symbol_graph"}
    missing_names = required_names - names
    if missing_names:
        fail(f"symbol_graph.json missing expected symbols: {sorted(missing_names)}")

    handoff_text = handoff.read_text(encoding="utf-8")
    for marker in [
        "## Symbol Relationship Graph",
        "symbol_graph.json",
        "Function I/O and static calls",
        "phase 10 symbol graph audit",
    ]:
        if marker not in handoff_text:
            fail(f"ai_handoff.md missing marker: {marker}")

    if "C:\\Users\\" in handoff_text:
        fail("ai_handoff.md leaked an absolute Windows user path.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 10 symbol graph audit passed.")
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
    path = ROOT / "src/codebase_lens/reports/snapshot.py"
    text = path.read_text(encoding="utf-8")

    import_marker = "from codebase_lens.reports.scanner_outputs import write_file_inventory, write_tree_report\n"
    import_addition = (
        "from codebase_lens.analyzers.symbol_graph import collect_symbol_graph\n"
        "from codebase_lens.reports.symbol_graph import write_symbol_graph_reports\n"
    )
    if import_addition not in text:
        if import_marker not in text:
            raise RuntimeError("snapshot.py import marker not found.")
        text = text.replace(import_marker, import_addition + import_marker, 1)

    old = '''    python_files = _python_files_from_universe(universe)

    changed_file_count = 0
'''
    new = '''    all_python_files = _python_files_from_universe(universe)
    python_files = list(all_python_files)

    changed_file_count = 0
'''
    if old in text and new not in text:
        text = text.replace(old, new, 1)

    old_graph_spot = '''    test_inventory = collect_test_inventory(root, python_files, include_fixtures=True)
    tests_payload = test_inventory_payload(test_inventory)
    outputs.update(
        _write_payload_with_aliases(
            layout,
            tests_payload,
            canonical_name="tests_inventory.json",
            alias_names=("test_inventory.json",),
        )
    )

    counts = {
'''
    new_graph_spot = '''    test_inventory = collect_test_inventory(root, python_files, include_fixtures=True)
    tests_payload = test_inventory_payload(test_inventory)
    outputs.update(
        _write_payload_with_aliases(
            layout,
            tests_payload,
            canonical_name="tests_inventory.json",
            alias_names=("test_inventory.json",),
        )
    )

    graph_result = collect_symbol_graph(
        root,
        all_python_files,
        focus_paths=set(python_files),
        focus_terms=focus_terms,
    )
    warnings.extend(graph_result.warnings)
    outputs.update(write_symbol_graph_reports(layout, graph_result))

    counts = {
'''
    if old_graph_spot not in text:
        if "graph_result = collect_symbol_graph(" not in text:
            raise RuntimeError("snapshot.py graph insertion marker not found.")
    else:
        text = text.replace(old_graph_spot, new_graph_spot, 1)

    old_count = '''        "omissions": len(getattr(universe, "omissions", ())),
'''
    new_count = '''        "omissions": len(getattr(universe, "omissions", ())),
        "symbol_graph_nodes": graph_result.counts.get("nodes", 0),
        "symbol_graph_call_edges": graph_result.counts.get("call_edges", 0),
        "symbol_graph_caller_edges": graph_result.counts.get("caller_edges", 0),
'''
    if old_count in text and new_count not in text:
        text = text.replace(old_count, new_count, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_handoff() -> None:
    path = ROOT / "src/codebase_lens/reports/handoff.py"
    text = path.read_text(encoding="utf-8")

    insertion = r'''

def _read_symbol_graph_excerpt(layout: OutputLayout, *, max_lines: int = 140) -> list[str]:
    path = layout.latest_dir / "symbol_graph.md"
    if not path.is_file():
        return ["`symbol_graph.md` was not generated."]

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= max_lines:
        return lines
    return [*lines[:max_lines], f"... ({len(lines) - max_lines} additional symbol-graph lines omitted; see `symbol_graph.md` and `symbol_graph.json`.)"]


def _changed_scope_notice(layout: OutputLayout, *, changed_only: bool) -> list[str]:
    if not changed_only:
        return []

    payload = _read_json(layout.latest_dir / "changed_files.json")
    records = payload.get("changed_files", [])
    if isinstance(records, list) and records:
        return []

    return [
        "No Git changes detected for this changed-only pack.",
        "",
        "This means changed-file and changed-symbol sections are intentionally empty.",
        "",
        "Suggested commands:",
        "",
        "- `cbl pack --budget 16000`",
        "- `cbl snapshot --budget 16000`",
        "- `cbl symbols`",
        "- `cbl callers --name <symbol>`",
    ]

'''
    marker = "\ndef _write_pack_index(\n"
    if "_read_symbol_graph_excerpt" not in text:
        if marker not in text:
            raise RuntimeError("handoff.py insertion marker not found.")
        text = text.replace(marker, insertion + marker, 1)

    old = '''    omissions = _format_omissions(layout)
    budget_lines = _format_budget(layout)

    markdown_lines = [
'''
    new = '''    omissions = _format_omissions(layout)
    budget_lines = _format_budget(layout)
    symbol_graph_excerpt = _read_symbol_graph_excerpt(layout)
    changed_scope_notice = _changed_scope_notice(layout, changed_only=changed_only)

    markdown_lines = [
'''
    if old in text and new not in text:
        text = text.replace(old, new, 1)

    old_section = '''        "## Generated Outputs",
        "",
        *output_lines,
'''
    new_section = '''        "## Changed-Only Scope Notice",
        "",
        *(changed_scope_notice or ["No changed-only scope warning applies."]),
        "",
        "## Symbol Relationship Graph",
        "",
        "Function I/O and static calls are summarized below. Full machine-readable graph: `symbol_graph.json`. Full readable graph: `symbol_graph.md`.",
        "",
        *symbol_graph_excerpt,
        "",
        "## Generated Outputs",
        "",
        *output_lines,
'''
    if old_section in text and new_section not in text:
        text = text.replace(old_section, new_section, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_contract() -> None:
    path = ROOT / "src/codebase_lens/contracts/architecture.py"
    text = path.read_text(encoding="utf-8")

    marker = '            "src/codebase_lens/analyzers/tests.py",\n'
    addition = (
        '            "src/codebase_lens/analyzers/symbol_graph.py",\n'
        '            "src/codebase_lens/reports/symbol_graph.py",\n'
        '            "scripts/dev/audits/audit_phase10_symbol_graph.py",\n'
    )
    if addition not in text:
        if marker not in text:
            raise RuntimeError("architecture.py required-files marker not found.")
        text = text.replace(marker, marker + addition, 1)

    extra_required = '''            {
                "path": "src/codebase_lens/analyzers/symbol_graph.py",
                "symbols": [
                    "SymbolGraphNode",
                    "SymbolGraphResult",
                    "collect_symbol_graph",
                    "symbol_graph_payload",
                    "render_symbol_graph_markdown",
                ],
            },
            {
                "path": "src/codebase_lens/reports/symbol_graph.py",
                "symbols": [
                    "write_symbol_graph_reports",
                ],
            },
'''
    insertion_marker = '''            {
                "path": "src/codebase_lens/reports/cleanup.py",
'''
    if extra_required not in text:
        if insertion_marker not in text:
            raise RuntimeError("architecture.py required-symbols marker not found.")
        text = text.replace(insertion_marker, extra_required + insertion_marker, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_audits() -> None:
    for relative in [
        "scripts/dev/audits/audit_v01_readiness.py",
        "scripts/dev/audits/audit_phase8_snapshot_pack.py",
    ]:
        path = ROOT / relative
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")

        marker = '    "budget_report.json",\n'
        addition = '    "symbol_graph.json",\n    "symbol_graph.md",\n'
        if addition not in text and marker in text:
            text = text.replace(marker, marker + addition, 1)

        marker_pack = '    "budget_report.json",\n'
        if addition not in text and marker_pack in text:
            text = text.replace(marker_pack, marker_pack + addition, 1)

        path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_snapshot()
    patch_handoff()
    patch_contract()
    patch_audits()

    print("Slice 012 applied: symbol relationship graph and useful handoff pack implemented.")
    print("Run the Phase 10 audit, v0.1 audit, contract, pytest, and git diff --check before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())