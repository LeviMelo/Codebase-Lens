from __future__ import annotations

import re
from pathlib import Path

ROOT = Path.cwd()

REQUIRED_FILES = [
    "src/codebase_lens/core/graph.py",
    "src/codebase_lens/analyzers/evidence_graph.py",
    "src/codebase_lens/reports/graph.py",
    "scripts/dev/audits/audit_phase11_evidence_graph.py",
]

REQUIRED_SYMBOL_BLOCKS = [
    {
        "path": "src/codebase_lens/core/graph.py",
        "symbols": [
            "GraphNode",
            "GraphEdge",
            "EvidenceGraph",
            "evidence_graph_payload",
            "graph_slice_payload",
        ],
    },
    {
        "path": "src/codebase_lens/analyzers/evidence_graph.py",
        "symbols": [
            "build_evidence_graph",
        ],
    },
    {
        "path": "src/codebase_lens/reports/graph.py",
        "symbols": [
            "write_evidence_graph_reports",
            "render_graph_summary",
        ],
    },
]

GRAPH_OUTPUTS = [
    "evidence_graph.json",
    "graph_summary.md",
    "call_graph.json",
    "module_graph.json",
]


def find_key_list_bounds(text: str, key: str) -> tuple[int, int]:
    pattern = re.compile(rf'(?P<quote>["\']){re.escape(key)}(?P=quote)\s*:\s*\[')
    match = pattern.search(text)
    if match is None:
        raise RuntimeError(f"Could not find list-valued key {key!r} in architecture.py.")

    open_index = text.find("[", match.start())
    if open_index == -1:
        raise RuntimeError(f"Could not find opening list bracket for {key!r}.")

    depth = 0
    i = open_index
    quote: str | None = None
    triple = False
    escaped = False

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


def patch_required_files(text: str) -> str:
    missing = [item for item in REQUIRED_FILES if f'"{item}"' not in text and f"'{item}'" not in text]
    if not missing:
        return text

    block = "".join(f'            "{item}",\n' for item in missing)
    return insert_before_list_close(text, "required_files", block)


def required_symbols_block(entry: dict[str, object]) -> str:
    path = str(entry["path"])
    symbols = list(entry["symbols"])  # type: ignore[arg-type]

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


def patch_required_symbols(text: str) -> str:
    blocks: list[str] = []

    for entry in REQUIRED_SYMBOL_BLOCKS:
        path = str(entry["path"])
        if f'"path": "{path}"' in text or f"'path': '{path}'" in text:
            continue
        blocks.append(required_symbols_block(entry))

    if not blocks:
        return text

    return insert_before_list_close(text, "required_symbols", "".join(blocks))


def patch_architecture() -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    text = patch_required_files(text)
    text = patch_required_symbols(text)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_audit_outputs(path: Path) -> None:
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8")

    if all(f'"{name}"' in text for name in GRAPH_OUTPUTS):
        return

    marker = '    "symbol_graph.md",\n'
    if marker not in text:
        marker = '        "symbol_graph.md",\n'

    if marker not in text:
        # Some audits do not maintain an explicit required-output list. Leave them alone.
        path.write_text(text, encoding="utf-8", newline="\n")
        return

    indent = marker.split('"', 1)[0]
    addition = "".join(f'{indent}"{name}",\n' for name in GRAPH_OUTPUTS if f'"{name}"' not in text)

    text = text.replace(marker, marker + addition, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def assert_slice013_files_exist() -> None:
    required = [
        "src/codebase_lens/core/graph.py",
        "src/codebase_lens/analyzers/evidence_graph.py",
        "src/codebase_lens/reports/graph.py",
        "tests/test_evidence_graph_integration.py",
        "scripts/dev/audits/audit_phase11_evidence_graph.py",
    ]

    missing = [item for item in required if not (ROOT / item).is_file()]
    if missing:
        raise RuntimeError(
            "Slice 013 files are missing. The previous updater may have failed before writing files. "
            f"Missing: {missing}"
        )


def main() -> int:
    assert_slice013_files_exist()

    patch_architecture()

    for relative in [
        "scripts/dev/audits/audit_v01_readiness.py",
        "scripts/dev/audits/audit_phase8_snapshot_pack.py",
        "scripts/dev/audits/audit_phase10_symbol_graph.py",
    ]:
        patch_audit_outputs(ROOT / relative)

    print("Repair applied: Slice 013 contract/audit patch completed with robust list insertion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())