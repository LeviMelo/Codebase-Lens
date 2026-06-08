from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd()
TARGET = ROOT / "src" / "codebase_lens" / "contracts" / "command_surface.py"


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    old = '''CORE_EXTERNAL_PACK_ARTIFACTS = (
    "manifest.json",
    "handoff_projection.json",
    "handoff_projection.md",
    "ai_handoff.md",
    "evidence_graph.json",
    "graph_summary.md",
    "symbol_graph.json",
    "symbol_graph.md",
    "file_inventory.json",
    "tree.md",
)
'''

    new = '''# These are mandatory artifacts for `cbl pack`.
# Do not include command-specific artifacts such as `tree.md`, which belongs to
# the tree-report command surface rather than the handoff pack contract.
CORE_EXTERNAL_PACK_ARTIFACTS = (
    "manifest.json",
    "handoff_projection.json",
    "handoff_projection.md",
    "ai_handoff.md",
    "evidence_graph.json",
    "graph_summary.md",
    "symbol_graph.json",
    "symbol_graph.md",
    "file_inventory.json",
)
'''

    if old not in text:
        raise RuntimeError("Could not find the expected CORE_EXTERNAL_PACK_ARTIFACTS block.")

    text = text.replace(old, new)
    ast.parse(text)

    TARGET.write_text(text, encoding="utf-8", newline="\n")

    print("Slice 016 repair applied: command surface gate no longer requires tree.md from cbl pack.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())