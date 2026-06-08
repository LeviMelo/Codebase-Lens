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


def _module_name_for_path(path: str) -> str | None:
    candidate = Path(path).with_suffix("")
    parts = list(candidate.parts)

    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]

    if not parts:
        return None

    if parts[0] in {"tests", "scripts"}:
        return ".".join(parts)

    return ".".join(parts)


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

    symbols_by_file_simple: dict[tuple[str, str], list[_RawSymbol]] = {}
    symbols_by_import_name: dict[str, list[_RawSymbol]] = {}

    for target in raw_symbols:
        symbols_by_file_simple.setdefault((target.path, target.simple_name), []).append(target)

        module_name = _module_name_for_path(target.path)
        if module_name:
            symbols_by_import_name.setdefault(f"{module_name}.{target.simple_name}", []).append(target)
            symbols_by_import_name.setdefault(f"{module_name}.{target.qualified_name}", []).append(target)

    callers_by_target: dict[str, list[CallerEdge]] = {}
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
            "functions": sum(1 for node in nodes if node.kind in {"function", "async_function", "method", "async_method"}),
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


def _path_tier(path: str) -> int:
    if path.startswith("src/codebase_lens/"):
        return 0
    if path.startswith("tests/"):
        return 2
    if path.startswith("scripts/dev/audits/"):
        return 3
    if path.startswith("scripts/dev/updaters/"):
        return 4
    return 1


def _noise_penalty(node: SymbolGraphNode) -> int:
    helper_names = {"fail", "run_cbl", "names_in_file", "make_repo", "main"}
    if node.path.startswith(("scripts/dev/", "tests/")) and node.simple_name in helper_names:
        return 10
    return 0


def _node_priority(node: SymbolGraphNode) -> tuple[int, int, int, int, int, str]:
    focus_rank = 0 if "focus" in node.confidence else 1
    path_rank = _path_tier(node.path)
    noise = _noise_penalty(node)
    connectivity = len(node.called_by) + len(node.calls)
    span = node.end_line - node.start_line
    return (focus_rank, path_rank, noise, -connectivity, -span, node.path)


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

    product_nodes = [node for node in nodes if node.path.startswith("src/codebase_lens/")]
    other_nodes = [node for node in nodes if not node.path.startswith("src/codebase_lens/")]
    display_nodes = [*product_nodes, *other_nodes]

    for node in display_nodes[:max_nodes]:
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
