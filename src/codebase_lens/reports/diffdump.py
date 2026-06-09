from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from codebase_lens.core.paths import resolve_user_path, to_posix_relative
from codebase_lens.core.redaction import redact_text
from codebase_lens.reports.json import changed_files_payload, write_json_report
from codebase_lens.reports.manifest import OutputLayout


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_line(record: object) -> str:
    path = str(getattr(record, "path", ""))
    status = str(getattr(record, "status", ""))
    additions = getattr(record, "additions", None)
    deletions = getattr(record, "deletions", None)
    hunks = getattr(record, "hunks", ()) or ()
    old_path = getattr(record, "old_path", None)
    rename = f"; old path `{old_path}`" if old_path else ""
    return f"- `{path}` — status `{status}`; +{additions if additions is not None else '?'} -{deletions if deletions is not None else '?'}; hunks={len(hunks)}{rename}"


def _changed_symbol_lines(changed_symbols_payload: dict[str, Any] | None) -> list[str]:
    if not changed_symbols_payload:
        return ["- Changed-symbol mapping was not requested. Re-run with `--symbols`."]
    records = changed_symbols_payload.get("changed_symbols", [])
    if not isinstance(records, list) or not records:
        return ["- No changed Python symbols were identified."]
    lines: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        path = record.get("path", "")
        name = record.get("qualified_name") or record.get("name") or "<unknown>"
        start = record.get("start_line", "?")
        end = record.get("end_line", start)
        lines.append(f"- `{name}` — `{path}:L{start}-L{end}`")
    return lines


def render_diff_dump_markdown(diff_result: object, patch_text: str, *, from_ref: str, to_ref: str, unified: int, changed_symbols_payload: dict[str, Any] | None = None, patch_warnings: tuple[str, ...] = ()) -> tuple[str, dict[str, Any]]:
    files = tuple(getattr(diff_result, "changed_files", ()) or ())
    counts = dict(getattr(diff_result, "counts", {}) or {})
    warnings = [*list(getattr(diff_result, "warnings", ()) or ()), *list(patch_warnings)]
    redacted_patch = redact_text(patch_text)
    lines: list[str] = ["# CBL Diff Dump", "", f"From: `{from_ref}`", f"To: `{to_ref}`", f"Unified context lines: {unified}", "Patch truncation: `disabled`", "Safety: redaction enabled", "", "## Counts", ""]
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")
    lines.extend(["", "## Changed Files", ""])
    lines.extend(_file_line(item) for item in files) if files else lines.append("- No changed files detected in this Git range.")
    lines.extend(["", "## Changed Symbols", ""])
    lines.extend(_changed_symbol_lines(changed_symbols_payload))
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in warnings)
    lines.extend(["", "## Full Patch", "", "~~~~diff", redacted_patch.text.rstrip("\n") if redacted_patch.text else "<empty diff>", "~~~~", ""])
    index = {"schema": {"name": "cbl.diff_dump", "version": 1}, "from_ref": from_ref, "to_ref": to_ref, "unified": unified, "patch_sha256": _sha256_text(redacted_patch.text), "patch_bytes": len(redacted_patch.text.encode("utf-8")), "changed_files": [asdict(item) for item in files], "changed_symbols": changed_symbols_payload, "counts": counts, "warnings": warnings, "redaction": {"enabled": True, "redacted_occurrences_count": redacted_patch.stats.redacted_occurrences_count, "patterns_hit": list(redacted_patch.stats.patterns_hit)}}
    return "\n".join(lines).rstrip() + "\n", index


def write_diffdump_reports(layout: OutputLayout, repo_root: str | Path, diff_result: object, patch_text: str, *, from_ref: str, to_ref: str, unified: int, changed_symbols_payload: dict[str, Any] | None = None, patch_warnings: tuple[str, ...] = (), out_file: str | None = None) -> dict[str, str]:
    root = Path(repo_root).resolve()
    markdown, index = render_diff_dump_markdown(diff_result, patch_text, from_ref=from_ref, to_ref=to_ref, unified=unified, changed_symbols_payload=changed_symbols_payload, patch_warnings=patch_warnings)
    (layout.latest_dir / "diff_dump.md").write_text(markdown, encoding="utf-8", newline="\n")
    write_json_report(layout.latest_dir / "diff_dump_index.json", index)
    write_json_report(layout.latest_dir / "diff.json", changed_files_payload(diff_result))
    outputs = {"diff_dump_md": ".codecontext/latest/diff_dump.md", "diff_dump_index_json": ".codecontext/latest/diff_dump_index.json", "diff_json": ".codecontext/latest/diff.json"}
    if out_file:
        target = resolve_user_path(root, out_file, allow_absolute=False, allow_hard_excluded=False)
        rel = to_posix_relative(root, target)
        if Path(rel).name in {"codebase_dump.md", "codebase_dump.txt"}:
            raise ValueError("--out-file for diffdump may not target a codebase dump artifact name.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8", newline="\n")
        outputs["diff_dump_copy"] = rel
    return outputs
