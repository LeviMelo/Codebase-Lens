from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def patch_symbol_graph_analyzer() -> None:
    path = ROOT / "src" / "codebase_lens" / "analyzers" / "symbol_graph.py"
    text = path.read_text(encoding="utf-8")

    old_matcher = '''def _call_matches_symbol(call_name: str, target: _RawSymbol) -> bool:
    if call_name == target.simple_name:
        return True
    if call_name == target.qualified_name:
        return True
    if call_name.endswith(f".{target.simple_name}"):
        return True
    return False


def collect_symbol_graph(
'''

    new_matcher = '''def _module_name_for_path(path: str) -> str | None:
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

    if "." not in call_name:
        same_file = tuple(symbols_by_file_simple.get((source.path, call_name), ()))
        if same_file:
            return tuple(target for target in same_file if target.qualified_name != source.qualified_name)

        imported = source.imported_names.get(call_name)
        if imported:
            return tuple(symbols_by_import_name.get(imported, ()))

        return ()

    if call_name.startswith(("self.", "cls.")):
        method_name = call_name.split(".")[-1]
        if "." not in source.qualified_name:
            return ()

        owner = source.qualified_name.rsplit(".", 1)[0]
        expected = f"{owner}.{method_name}"
        return tuple(
            target
            for target in symbols_by_file_simple.get((source.path, method_name), ())
            if target.qualified_name == expected
        )

    imported = source.imported_names.get(base)
    if imported:
        suffix = call_name[len(base) :]
        return tuple(symbols_by_import_name.get(imported + suffix, ()))

    return ()


def collect_symbol_graph(
'''

    if old_matcher not in text:
        raise RuntimeError("Could not replace old _call_matches_symbol block in symbol_graph.py.")

    text = text.replace(old_matcher, new_matcher, 1)

    old_caller_block = '''    callers_by_target: dict[str, list[CallerEdge]] = {}
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
'''

    new_caller_block = '''    symbols_by_file_simple: dict[tuple[str, str], list[_RawSymbol]] = {}
    symbols_by_import_name: dict[str, list[_RawSymbol]] = {}

    for target in raw_symbols:
        symbols_by_file_simple.setdefault((target.path, target.simple_name), []).append(target)

        module_name = _module_name_for_path(target.path)
        if module_name:
            symbols_by_import_name.setdefault(f"{module_name}.{target.simple_name}", []).append(target)
            symbols_by_import_name.setdefault(f"{module_name}.{target.qualified_name}", []).append(target)

    callers_by_target: dict[str, list[CallerEdge]] = {}
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

    focus_paths = focus_paths or set()
'''

    if old_caller_block not in text:
        raise RuntimeError("Could not replace global simple-name caller-resolution block in symbol_graph.py.")

    text = text.replace(old_caller_block, new_caller_block, 1)

    old_priority = '''def _node_priority(node: SymbolGraphNode) -> tuple[int, int, int, str]:
    focus_score = 2 if "focus" in node.confidence else 0
    connectivity = len(node.called_by) + len(node.calls)
    span = node.end_line - node.start_line
    return (-focus_score, -connectivity, -span, node.path)
'''

    new_priority = '''def _path_tier(path: str) -> int:
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
'''

    if old_priority not in text:
        raise RuntimeError("Could not replace _node_priority in symbol_graph.py.")

    text = text.replace(old_priority, new_priority, 1)

    text = text.replace(
        '        "## Symbol Nodes",',
        '        "## Prioritized Product Symbol Nodes",',
        1,
    )

    text = text.replace(
        '    for node in nodes[:max_nodes]:\n',
        '''    product_nodes = [node for node in nodes if node.path.startswith("src/codebase_lens/")]
    other_nodes = [node for node in nodes if not node.path.startswith("src/codebase_lens/")]
    display_nodes = [*product_nodes, *other_nodes]

    for node in display_nodes[:max_nodes]:
''',
        1,
    )

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_snapshot_focus_paths() -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "snapshot.py"
    text = path.read_text(encoding="utf-8")

    old = '''    graph_result = collect_symbol_graph(
        root,
        all_python_files,
        focus_paths=set(python_files),
        focus_terms=focus_terms,
    )
'''

    new = '''    graph_result = collect_symbol_graph(
        root,
        all_python_files,
        focus_paths=set(python_files) if changed_only else set(),
        focus_terms=focus_terms,
    )
'''

    if old not in text:
        if new in text:
            return
        raise RuntimeError("Could not patch collect_symbol_graph focus_paths call in snapshot.py.")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_phase10_audit() -> None:
    path = ROOT / "scripts" / "dev" / "audits" / "audit_phase10_symbol_graph.py"
    text = path.read_text(encoding="utf-8")

    marker = '''    handoff_text = handoff.read_text(encoding="utf-8")
    for marker in [
        "## Symbol Relationship Graph",
        "symbol_graph.json",
        "Function I/O and static calls",
        "phase 10 symbol graph audit",
    ]:
        if marker not in handoff_text:
            fail(f"ai_handoff.md missing marker: {marker}")

    if "C:\\\\Users\\\\" in handoff_text:
        fail("ai_handoff.md leaked an absolute Windows user path.")
'''

    replacement = '''    handoff_text = handoff.read_text(encoding="utf-8")
    for marker in [
        "## Symbol Relationship Graph",
        "symbol_graph.json",
        "Function I/O and static calls",
        "phase 10 symbol graph audit",
    ]:
        if marker not in handoff_text:
            fail(f"ai_handoff.md missing marker: {marker}")

    if "C:\\\\Users\\\\" in handoff_text:
        fail("ai_handoff.md leaked an absolute Windows user path.")

    first_src_symbol = min(
        [handoff_text.find(token) for token in ["### `write_snapshot_bundle`", "### `write_handoff_pack`", "### `build_parser`"] if handoff_text.find(token) != -1],
        default=-1,
    )
    first_fail = handoff_text.find("### `fail`")

    if first_src_symbol == -1:
        fail("ai_handoff.md does not surface a core src/ symbol in the visible symbol graph excerpt.")

    if first_fail != -1 and first_fail < first_src_symbol:
        fail("ai_handoff.md is still front-loaded with audit helper noise before product symbols.")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("simple_name") != "fail":
            continue
        node_path = node.get("path")
        for caller in node.get("called_by", []):
            if isinstance(caller, dict) and caller.get("path") != node_path:
                fail("symbol_graph.json still contains cross-file false caller edges for helper function fail().")
'''

    if marker not in text:
        if "front-loaded with audit helper noise" in text:
            return
        raise RuntimeError("Could not patch audit_phase10_symbol_graph.py quality-check marker.")

    text = text.replace(marker, replacement, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    patch_symbol_graph_analyzer()
    patch_snapshot_focus_paths()
    patch_phase10_audit()

    print("Repair applied: symbol graph resolution and handoff relevance ordering hardened.")
    print("Run Phase 10 audit, v0.1 readiness audit, Phase 8 audit, contract, pytest, and inspect ai_handoff.md before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())