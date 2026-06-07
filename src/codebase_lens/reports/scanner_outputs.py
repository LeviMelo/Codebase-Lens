from __future__ import annotations

from pathlib import Path

from codebase_lens.reports.manifest import OutputLayout, write_json
from codebase_lens.scanners.inventory import file_universe_to_inventory
from codebase_lens.scanners.tree import render_tree_report


def write_file_inventory(layout: OutputLayout, result) -> Path:
    target = layout.latest_dir / "file_inventory.json"
    write_json(target, file_universe_to_inventory(result))
    return target


def write_tree_report(
    layout: OutputLayout,
    result,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> Path:
    target = layout.latest_dir / "repo_tree.txt"
    target.write_text(
        render_tree_report(
            result,
            max_depth=max_depth,
            show_sizes=show_sizes,
            show_skipped=show_skipped,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target
