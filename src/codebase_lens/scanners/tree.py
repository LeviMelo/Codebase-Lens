from __future__ import annotations

from pathlib import Path

from codebase_lens.core.models import FileRecord, OmissionRecord
from codebase_lens.reports.manifest import OutputLayout
from codebase_lens.scanners.universe import FileUniverseResult


def _trim_path(path: str, max_depth: int) -> str:
    parts = [part for part in path.split("/") if part]
    if max_depth <= 0:
        return path
    if len(parts) <= max_depth:
        return path
    return "/".join([*parts[:max_depth], "..."])


def _tree_lines_from_paths(paths: list[str]) -> list[str]:
    lines = ["."]
    seen: set[str] = set()

    for path in sorted(paths):
        parts = [part for part in path.split("/") if part]
        for index, part in enumerate(parts):
            is_file = index == len(parts) - 1
            prefix = "  " * (index + 1)
            current = "/".join(parts[: index + 1])
            display = part if is_file else f"{part}/"
            if current in seen:
                continue
            seen.add(current)
            lines.append(f"{prefix}{display}")

    return lines


def render_tree_report(
    result: FileUniverseResult,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> str:
    paths: list[str] = []
    size_by_path = {record.path: record.size_bytes for record in result.included_files}

    for record in result.included_files:
        rendered = _trim_path(record.path, max_depth)
        if show_sizes and rendered == record.path:
            rendered = f"{rendered} ({record.size_bytes} bytes)"
        paths.append(rendered)

    lines = [
        "CBL Repository Tree",
        f"Repository: {result.repo_root.name}",
        f"Git repository: {str(result.is_git_repo).lower()}",
        f"Included files: {result.counts.get('included_count', 0)}",
        f"Tracked included: {result.counts.get('tracked_included_count', 0)}",
        f"Untracked included: {result.counts.get('untracked_included_count', 0)}",
        f"Ignored count: {result.counts.get('ignored_count', 0)}",
        f"Hard-excluded count: {result.counts.get('hard_excluded_count', 0)}",
        f"Large skipped count: {result.counts.get('large_skipped_count', 0)}",
        f"Binary skipped count: {result.counts.get('binary_skipped_count', 0)}",
        f"Decode-failed count: {result.counts.get('decode_failed_count', 0)}",
        "",
    ]

    lines.extend(_tree_lines_from_paths(sorted(set(paths))))

    if show_skipped:
        lines.append("")
        lines.append("Skipped and omitted files:")
        if not result.omitted_files:
            lines.append("  <none>")
        for omission in result.omitted_files:
            lines.append(f"  {omission.path} [{omission.reason}]")

    return "\n".join(lines) + "\n"


def write_tree_report(
    layout: OutputLayout,
    result: FileUniverseResult,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> Path:
    path = layout.latest_dir / "repo_tree.txt"
    path.write_text(
        render_tree_report(
            result,
            max_depth=max_depth,
            show_sizes=show_sizes,
            show_skipped=show_skipped,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return path
