from __future__ import annotations

from pathlib import Path
from typing import Any

from codebase_lens.reports.json import write_json_report
from codebase_lens.reports.manifest import OutputLayout


def _changed_files(diff_result: object) -> tuple[object, ...]:
    value = getattr(diff_result, "changed_files", ())
    return tuple(value or ())


def _counts(diff_result: object) -> dict[str, Any]:
    value = getattr(diff_result, "counts", {})
    return dict(value) if isinstance(value, dict) else {}


def _warnings(diff_result: object) -> tuple[str, ...]:
    value = getattr(diff_result, "warnings", ())
    return tuple(str(item) for item in (value or ()))


def _status_label(status: str) -> str:
    return {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "U": "unmerged",
        "?": "untracked",
    }.get(status, status or "unknown")


def _file_line(record: object) -> str:
    path = str(getattr(record, "path", ""))
    status = str(getattr(record, "status", ""))
    origin = str(getattr(record, "origin", ""))
    additions = getattr(record, "additions", None)
    deletions = getattr(record, "deletions", None)
    binary = bool(getattr(record, "is_binary", False))
    hunks = getattr(record, "hunks", ()) or ()

    stats = []
    if additions is not None:
        stats.append(f"+{additions}")
    if deletions is not None:
        stats.append(f"-{deletions}")
    if binary:
        stats.append("binary")
    stats.append(f"hunks={len(hunks)}")

    return f"- `{path}` — {_status_label(status)}; origin `{origin}`; {', '.join(stats)}"


def _changed_symbol_lines(changed_symbols_payload: dict[str, Any] | None) -> list[str]:
    if not changed_symbols_payload:
        return ["- Changed-symbol mapping was not requested. Re-run `cbl diff --symbols` for line-overlap symbol evidence."]

    records = changed_symbols_payload.get("changed_symbols", [])
    if not isinstance(records, list) or not records:
        return ["- No changed Python symbols were identified."]

    lines = []
    for record in records[:80]:
        if not isinstance(record, dict):
            continue
        path = record.get("path", "")
        name = record.get("qualified_name") or record.get("name") or "<unknown>"
        start = record.get("start_line", "?")
        end = record.get("end_line", start)
        origin = record.get("change_origin", "unknown")
        lines.append(f"- `{name}` — `{path}:L{start}-L{end}`; origin `{origin}`")

    if len(records) > 80:
        lines.append(f"- ... {len(records) - 80} additional changed symbols omitted from Markdown; see `diff.json`.")

    return lines or ["- No changed Python symbols were identified."]


def render_diff_summary_markdown(
    diff_result: object,
    *,
    changed_symbols_payload: dict[str, Any] | None = None,
    base: str | None = None,
) -> str:
    files = _changed_files(diff_result)
    counts = _counts(diff_result)
    warnings = _warnings(diff_result)

    staged = [item for item in files if "staged" in str(getattr(item, "origin", ""))]
    unstaged = [item for item in files if "unstaged" in str(getattr(item, "origin", ""))]
    untracked = [item for item in files if "untracked" in str(getattr(item, "origin", ""))]

    lines: list[str] = [
        "# Diff Summary",
        "",
        "## Git Base",
        "",
        f"- Base argument: `{base or '(not supplied)'}`",
        f"- Changed files: {counts.get('changed_files_count', len(files))}",
        f"- Hunks: {counts.get('hunk_count', 0)}",
        "",
        "## Staged Changes",
        "",
    ]

    lines.extend(_file_line(item) for item in staged[:80])
    if not staged:
        lines.append("- No staged changes detected.")

    lines.extend(["", "## Unstaged Changes", ""])
    lines.extend(_file_line(item) for item in unstaged[:80])
    if not unstaged:
        lines.append("- No unstaged changes detected.")

    lines.extend(["", "## Untracked Source Files", ""])
    lines.extend(_file_line(item) for item in untracked[:80])
    if not untracked:
        lines.append("- No untracked source files detected.")

    lines.extend(["", "## Changed Files", ""])
    lines.extend(_file_line(item) for item in files[:120])
    if not files:
        lines.append("- No changed files detected.")
    if len(files) > 120:
        lines.append(f"- ... {len(files) - 120} additional changed files omitted from Markdown; see `diff.json`.")

    lines.extend(["", "## Changed Symbols", ""])
    lines.extend(_changed_symbol_lines(changed_symbols_payload))

    lines.extend(["", "## Diff Stats", ""])
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")

    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in warnings)

    lines.extend(
        [
            "",
            "## Follow-Up Commands",
            "",
            "- `python -m codebase_lens changed --no-archive`",
            "- `python -m codebase_lens diff --symbols --no-archive`",
            "- `python -m codebase_lens pack --changed --issue \"review current changes\" --no-archive`",
            "",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"


def write_diff_reports(
    layout: OutputLayout,
    diff_result: object,
    payload: dict[str, Any],
    *,
    changed_symbols_payload: dict[str, Any] | None = None,
    base: str | None = None,
) -> dict[str, str]:
    write_json_report(layout.latest_dir / "diff.json", payload)

    summary = render_diff_summary_markdown(
        diff_result,
        changed_symbols_payload=changed_symbols_payload,
        base=base,
    )
    (layout.latest_dir / "diff_summary.md").write_text(summary, encoding="utf-8", newline="\n")

    return {
        "diff_json": ".codecontext/latest/diff.json",
        "diff_summary_md": ".codecontext/latest/diff_summary.md",
    }
