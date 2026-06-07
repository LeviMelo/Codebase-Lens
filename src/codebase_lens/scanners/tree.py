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


def render_tree_report(
    result,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> str:
    """Render a scanner FileUniverseResult as text without report-layer imports."""

    included_files = list(getattr(result, "included_files", ()))
    omissions = list(getattr(result, "omissions", ()))
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
        if not omissions:
            lines.append("(none)")
        else:
            for record in omissions:
                path = getattr(record, "path", "")
                reason = getattr(record, "reason", "unknown")
                evidence = getattr(record, "evidence", None)
                suffix = f" ({evidence})" if evidence else ""
                lines.append(f"{path}: {reason}{suffix}")

    return "\n".join(lines)
