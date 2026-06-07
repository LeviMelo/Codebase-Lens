from __future__ import annotations

import re
from pathlib import Path

ROOT = Path.cwd()


GRAPH_HANDLER = r'''

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


def function_bounds(text: str, function_name: str) -> tuple[int, int]:
    start_match = re.search(rf"^def {re.escape(function_name)}\(", text, flags=re.MULTILINE)
    if start_match is None:
        raise RuntimeError(f"Could not find {function_name}().")

    start = start_match.start()
    next_match = re.search(r"^def [A-Za-z_][A-Za-z0-9_]*\(", text[start_match.end() :], flags=re.MULTILINE)
    if next_match is None:
        return start, len(text)

    return start, start_match.end() + next_match.start()


def remove_existing_graph_parser_blocks(text: str) -> str:
    pattern = re.compile(
        r'''
        ^\s*graph\s*=\s*[A-Za-z_][A-Za-z0-9_]*\.add_parser\(\s*["']graph["'][\s\S]*?
        ^\s*graph\.set_defaults\(handler=_run_graph\)\s*\n+
        ''',
        flags=re.MULTILINE | re.VERBOSE,
    )
    return pattern.sub("", text)


def detect_subparser_variable(build_text: str) -> str:
    candidates = re.findall(r"(\w+)\.add_parser\(\s*[\"']doctor[\"']", build_text)
    if candidates:
        return candidates[0]

    candidates = re.findall(r"(\w+)\s*=\s*parser\.add_subparsers\(", build_text)
    if candidates:
        return candidates[0]

    raise RuntimeError("Could not detect subparser variable inside build_parser().")


def detect_parent_clause(build_text: str) -> str:
    doctor_line = re.search(r"\w+\.add_parser\(\s*[\"']doctor[\"'](?P<body>[^\n]*)", build_text)
    if doctor_line:
        body = doctor_line.group("body")
        parent_match = re.search(r"parents\s*=\s*(\[[^\]]+\])", body)
        if parent_match:
            return f", parents={parent_match.group(1)}"

    if "parents=[parent]" in build_text:
        return ", parents=[parent]"

    return ""


def build_graph_parser_block(subparser_variable: str, parent_clause: str) -> str:
    return f'''    graph = {subparser_variable}.add_parser("graph"{parent_clause}, help="Query scoped evidence graph neighborhoods.")
    graph.add_argument("--symbol", help="Symbol name or substring to seed the graph query.")
    graph.add_argument("--path", help="Repository-relative path to seed the graph query.")
    graph.add_argument("--module", help="Module name or substring to seed the graph query.")
    graph.add_argument("--depth", type=int, default=1, help="Undirected graph expansion depth from seed nodes.")
    graph.add_argument("--limit", type=int, default=60, help="Maximum nodes to retain in the markdown-oriented query view.")
    graph.add_argument("--changed", action="store_true", help="Seed query from changed hunks and changed symbols.")
    graph.set_defaults(handler=_run_graph)

'''


def patch_build_parser(text: str) -> str:
    text = remove_existing_graph_parser_blocks(text)

    start, end = function_bounds(text, "build_parser")
    build_text = text[start:end]

    if 'add_parser("graph"' in build_text or "add_parser('graph'" in build_text:
        return text

    subparser_variable = detect_subparser_variable(build_text)
    parent_clause = detect_parent_clause(build_text)
    graph_block = build_graph_parser_block(subparser_variable, parent_clause)

    return_pos = build_text.rfind("    return parser")
    if return_pos == -1:
        raise RuntimeError("Could not find final `return parser` inside build_parser().")

    absolute_return_pos = start + return_pos
    return text[:absolute_return_pos] + graph_block + text[absolute_return_pos:]


def patch_handler(text: str) -> str:
    if "def _run_graph(" in text:
        return text

    marker = "\ndef _run_pack("
    insert_pos = text.find(marker)
    if insert_pos == -1:
        marker = "\ndef _run_contract("
        insert_pos = text.find(marker)

    if insert_pos == -1:
        raise RuntimeError("Could not find insertion point for _run_graph().")

    return text[:insert_pos] + GRAPH_HANDLER + text[insert_pos:]


def find_container_bounds(text: str, open_index: int) -> tuple[int, int]:
    opener = text[open_index]
    closer = { "[": "]", "(": ")", "{": "}" }[opener]

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

        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return open_index, i

        i += 1

    raise RuntimeError("Could not find container close.")


def patch_command_registries(text: str) -> str:
    known_commands = {
        "doctor",
        "snapshot",
        "tree",
        "symbols",
        "symbol",
        "imports",
        "cli",
        "routes",
        "tests",
        "callers",
        "contract",
        "pack",
        "diff",
        "changed",
        "clean",
    }

    search_pos = 0
    patched_any = False

    while True:
        match = re.search(
            r"(?m)^([A-Z_][A-Z0-9_]*|[a-z_][a-z0-9_]*)\s*(?::[^=\n]+)?=\s*([\[\(\{])",
            text[search_pos:],
        )

        if match is None:
            break

        open_index = search_pos + match.start(2)
        variable_name = match.group(1)
        opener = match.group(2)

        try:
            start, end = find_container_bounds(text, open_index)
        except RuntimeError:
            search_pos = open_index + 1
            continue

        block = text[start : end + 1]
        command_hits = sum(1 for command in known_commands if f'"{command}"' in block or f"'{command}'" in block)

        if command_hits >= 8 and '"graph"' not in block and "'graph'" not in block:
            lower_name = variable_name.lower()

            # Do not blindly insert handler values into arbitrary dictionaries unless they are clearly handler maps.
            if opener == "{":
                if "_run_" in block and ("handler" in lower_name or "command" in lower_name):
                    insertion = '    "graph": _run_graph,\n'
                    text = text[:end] + insertion + text[end:]
                    patched_any = True
                    search_pos = end + len(insertion) + 1
                    continue

                # Plain set of command names.
                if ":" not in block:
                    insertion = '    "graph",\n'
                    text = text[:end] + insertion + text[end:]
                    patched_any = True
                    search_pos = end + len(insertion) + 1
                    continue

            elif opener in {"[", "("}:
                insertion = '    "graph",\n'
                text = text[:end] + insertion + text[end:]
                patched_any = True
                search_pos = end + len(insertion) + 1
                continue

        search_pos = end + 1

    return text


def patch_cli() -> None:
    path = ROOT / "src" / "codebase_lens" / "cli.py"
    text = path.read_text(encoding="utf-8")

    text = patch_build_parser(text)
    text = patch_handler(text)
    text = patch_command_registries(text)

    path.write_text(text, encoding="utf-8", newline="\n")

    start, end = function_bounds(text, "build_parser")
    build_text = text[start:end]
    if 'add_parser("graph"' not in build_text and "add_parser('graph'" not in build_text:
        raise RuntimeError("graph parser is still not registered inside build_parser().")


def main() -> int:
    patch_cli()
    print("Repair applied: graph command registered inside build_parser and command registries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())