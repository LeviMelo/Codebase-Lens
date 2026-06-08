from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codebase_lens.contracts.architecture import evaluate_contract, load_contract_spec
from codebase_lens.reports.json import contract_result_payload, write_json_report
from codebase_lens.reports.manifest import OutputLayout
from codebase_lens.reports.snapshot import SnapshotBundleResult, write_snapshot_bundle
from codebase_lens.core.redaction import redact_console_text


@dataclass(frozen=True)
class HandoffPackResult:
    outputs: dict[str, str]
    counts: dict[str, int]
    warnings: tuple[str, ...]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_tree_excerpt(path: Path, *, max_lines: int = 160) -> list[str]:
    if not path.is_file():
        return ["(repo_tree.txt was not generated)"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= max_lines:
        return lines
    return [*lines[:max_lines], f"... ({len(lines) - max_lines} additional tree lines omitted)"]


def _format_output_list(outputs: dict[str, str]) -> list[str]:
    return [f"- `{key}` → `{value}`" for key, value in sorted(outputs.items())]


def _format_changed_files(layout: OutputLayout, *, max_items: int = 60) -> list[str]:
    payload = _read_json(layout.latest_dir / "changed_files.json")
    records = payload.get("changed_files", [])
    if not isinstance(records, list) or not records:
        return ["- No changed files were captured in this pack."]

    lines: list[str] = []
    for record in records[:max_items]:
        if not isinstance(record, dict):
            continue
        path = record.get("path", "<unknown>")
        origin = record.get("origin", "<unknown>")
        status = record.get("status", "?")
        additions = record.get("additions")
        deletions = record.get("deletions")
        lines.append(f"- `{path}` [{status}, {origin}, +{additions}/-{deletions}]")

    if len(records) > max_items:
        lines.append(f"- ... {len(records) - max_items} additional changed files omitted.")

    return lines


def _format_changed_symbols(layout: OutputLayout, *, max_items: int = 80) -> list[str]:
    payload = _read_json(layout.latest_dir / "changed_symbols.json")
    records = payload.get("changed_symbols", [])
    if not isinstance(records, list) or not records:
        return ["- No changed Python symbols were captured in this pack."]

    lines: list[str] = []
    for record in records[:max_items]:
        if not isinstance(record, dict):
            continue
        path = record.get("path", "<unknown>")
        name = record.get("qualified_name", "<unknown>")
        start = record.get("start_line", "?")
        end = record.get("end_line", "?")
        lines.append(f"- `{name}` → `{path}:L{start}-L{end}`")

    if len(records) > max_items:
        lines.append(f"- ... {len(records) - max_items} additional changed symbols omitted.")

    return lines


def _format_omissions(layout: OutputLayout, *, max_items: int = 60) -> list[str]:
    payload = _read_json(layout.latest_dir / "omissions.json")
    records = payload.get("omitted_files") or payload.get("omissions", [])
    if not isinstance(records, list) or not records:
        return ["- No omitted files were reported by the scanner."]

    lines: list[str] = []
    for record in records[:max_items]:
        if not isinstance(record, dict):
            continue
        path = record.get("path", "<unknown>")
        reason = record.get("reason", "<unknown>")
        evidence = record.get("evidence")
        suffix = f" — {evidence}" if evidence else ""
        lines.append(f"- `{path}` → {reason}{suffix}")

    if len(records) > max_items:
        lines.append(f"- ... {len(records) - max_items} additional omissions omitted from markdown; see `omissions.json`.")

    return lines


def _format_budget(layout: OutputLayout) -> list[str]:
    payload = _read_json(layout.latest_dir / "budget_report.json")
    if not payload:
        return ["- `budget_report.json` was not generated."]

    return [
        f"- Requested budget tokens: {payload.get('requested_budget_tokens')}",
        f"- Budget pressure: {payload.get('budget_pressure')}",
        f"- Focus terms: {payload.get('focus_terms', [])}",
        f"- Estimation method: {payload.get('estimation_method')}",
    ]



def _read_symbol_graph_excerpt(layout: OutputLayout, *, max_lines: int = 140) -> list[str]:
    path = layout.latest_dir / "symbol_graph.md"
    if not path.is_file():
        return ["`symbol_graph.md` was not generated."]

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= max_lines:
        return lines
    return [*lines[:max_lines], f"... ({len(lines) - max_lines} additional symbol-graph lines omitted; see `symbol_graph.md` and `symbol_graph.json`.)"]


def _changed_scope_notice(layout: OutputLayout, *, changed_only: bool) -> list[str]:
    if not changed_only:
        return []

    payload = _read_json(layout.latest_dir / "changed_files.json")
    records = payload.get("changed_files", [])
    if isinstance(records, list) and records:
        return []

    return [
        "No Git changes detected for this changed-only pack.",
        "",
        "This means changed-file and changed-symbol sections are intentionally empty.",
        "",
        "Suggested commands:",
        "",
        "- `cbl pack --budget 16000`",
        "- `cbl snapshot --budget 16000`",
        "- `cbl symbols`",
        "- `cbl callers <symbol>`",
    ]


def _write_pack_index(
    layout: OutputLayout,
    *,
    issue: str | None,
    changed_only: bool,
    outputs: dict[str, str],
    counts: dict[str, int],
    warnings: tuple[str, ...],
    budget: int,
    focus_terms: tuple[str, ...],
) -> Path:
    payload = {
        "schema": {
            "name": "cbl.pack_index",
            "version": 1,
        },
        "issue": issue,
        "scope": "changed" if changed_only else "full",
        "budget": budget,
        "focus_terms": list(focus_terms),
        "outputs": outputs,
        "counts": counts,
        "warnings": list(warnings),
    }
    return write_json_report(layout.latest_dir / "pack_index.json", payload)


def write_handoff_pack(
    layout: OutputLayout,
    repo_root: str | Path,
    *,
    max_file_bytes: int,
    changed_only: bool = False,
    issue: str | None = None,
    spec_path: str | Path | None = None,
    budget: int = 16000,
    focus_terms: tuple[str, ...] = (),
) -> HandoffPackResult:
    root = Path(repo_root).resolve()

    snapshot = write_snapshot_bundle(
        layout,
        root,
        max_file_bytes=max_file_bytes,
        changed_only=changed_only,
        tree_depth=5,
        budget=budget,
        focus_terms=focus_terms,
    )

    outputs = dict(snapshot.outputs)
    warnings = list(snapshot.warnings)
    counts = dict(snapshot.counts)

    if spec_path is not None:
        spec = load_contract_spec(root, spec_path)
        contract_result = evaluate_contract(root, spec)
        write_json_report(layout.latest_dir / "contract_report.json", contract_result_payload(contract_result))
        outputs["contract_report_json"] = ".codecontext/latest/contract_report.json"
        counts["contract_errors"] = contract_result.counts.get("errors", 0)
        counts["contract_violations"] = contract_result.counts.get("violations", 0)

    tree_excerpt = _read_tree_excerpt(layout.latest_dir / "repo_tree.txt")
    output_lines = _format_output_list(outputs)
    changed_files = _format_changed_files(layout)
    changed_symbols = _format_changed_symbols(layout)
    omissions = _format_omissions(layout)
    budget_lines = _format_budget(layout)
    symbol_graph_excerpt = _read_symbol_graph_excerpt(layout)
    changed_scope_notice = _changed_scope_notice(layout, changed_only=changed_only)

    markdown_lines = [
        "# CBL AI Handoff Pack",
        "",
        f"Repository: `{root.name}`",
        f"Scope: `{'changed' if changed_only else 'full'}`",
        f"Issue/context: {issue if issue else '(none provided)'}",
        "",
        "## Counts",
        "",
        f"- Included files: {counts.get('included_files', 0)}",
        f"- Python files analyzed: {counts.get('python_files_analyzed', 0)}",
        f"- Symbols: {counts.get('symbols', 0)}",
        f"- Imports: {counts.get('imports', 0)}",
        f"- CLI commands: {counts.get('commands', 0)}",
        f"- Routes: {counts.get('routes', 0)}",
        f"- Test files: {counts.get('test_files', 0)}",
        f"- Test functions: {counts.get('test_functions', 0)}",
        f"- Fixtures: {counts.get('fixtures', 0)}",
        f"- Changed files: {counts.get('changed_files', 0)}",
        f"- Changed symbols: {counts.get('changed_symbols', 0)}",
        f"- Omissions: {counts.get('omissions', 0)}",
        "",
        "## Budget and Focus",
        "",
        *budget_lines,
        "",
        "## Changed-Only Scope Notice",
        "",
        *(changed_scope_notice or ["No changed-only scope warning applies."]),
        "",
        "## Symbol Relationship Graph",
        "",
        "Function I/O and static calls are summarized below. Full machine-readable graph: `symbol_graph.json`. Full readable graph: `symbol_graph.md`.",
        "",
        *symbol_graph_excerpt,
        "",
        "## Generated Outputs",
        "",
        *output_lines,
        "",
        "## Changed Files",
        "",
        *changed_files,
        "",
        "## Changed Python Symbols",
        "",
        *changed_symbols,
        "",
        "## Omissions",
        "",
        *omissions,
        "",
        "## Repository Tree Excerpt",
        "",
        "```text",
        *tree_excerpt,
        "```",
        "",
        "## Safety Notes",
        "",
        "- Paths in this pack are repository-relative unless explicitly stated otherwise.",
        "- `.codecontext/`, private environment files, common build outputs, caches, and binary artifacts are excluded by scanner policy.",
        "- Secret-like assignments are redacted before AI-facing report generation.",
    ]

    if warnings:
        markdown_lines.extend(["", "## Warnings", ""])
        markdown_lines.extend(f"- {warning}" for warning in warnings)

    handoff_path = layout.latest_dir / "ai_handoff.md"
    handoff_path.write_text(redact_console_text("\n".join(markdown_lines).rstrip() + "\n"), encoding="utf-8", newline="\n")
    outputs["ai_handoff_md"] = ".codecontext/latest/ai_handoff.md"

    from codebase_lens.reports.handoff_projection import write_handoff_projection_reports

    outputs.update(
        write_handoff_projection_reports(
            layout,
            issue=issue,
            changed_only=changed_only,
            budget=budget,
            focus_terms=focus_terms,
            counts=counts,
            warnings=tuple(warnings),
        )
    )

    _write_pack_index(
        layout,
        issue=issue,
        changed_only=changed_only,
        outputs=outputs,
        counts=counts,
        warnings=tuple(warnings),
        budget=budget,
        focus_terms=focus_terms,
    )
    outputs["pack_index_json"] = ".codecontext/latest/pack_index.json"

    return HandoffPackResult(
        outputs=outputs,
        counts=counts,
        warnings=tuple(warnings),
    )
