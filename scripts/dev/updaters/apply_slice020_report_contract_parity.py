from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

CORE_BUDGET = r'''
from __future__ import annotations

from typing import Any

ESTIMATION_METHOD = "heuristic: max(1, file_size_bytes // 4)"


def estimate_tokens_for_bytes(size_bytes: int | None) -> int:
    size = int(size_bytes or 0)
    if size <= 0:
        return 1
    return max(1, size // 4)


def estimate_tokens_for_text(text: str) -> int:
    return max(1, len(text) // 4)


def focus_hits_for_path(path: str, focus_terms: tuple[str, ...]) -> int:
    if not focus_terms:
        return 0
    lowered = path.lower()
    return sum(1 for term in focus_terms if term.lower() in lowered)


def ranked_budget_file_records(
    included_files: object,
    *,
    focus_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    ranked_files: list[dict[str, Any]] = []

    for record in list(included_files or ()):
        path = str(getattr(record, "path", ""))
        size_bytes = int(getattr(record, "size_bytes", 0) or 0)
        estimated_tokens = estimate_tokens_for_bytes(size_bytes)
        focus_hits = focus_hits_for_path(path, focus_terms)

        ranked_files.append(
            {
                "path": path,
                "size_bytes": size_bytes,
                "estimated_tokens": estimated_tokens,
                "focus_hits": focus_hits,
                "priority_score": focus_hits * 1000 + max(0, 100000 - size_bytes),
            }
        )

    ranked_files.sort(key=lambda item: (-int(item["priority_score"]), str(item["path"])))
    return ranked_files


def build_budget_report_payload(
    included_files: object,
    *,
    budget: int,
    focus_terms: tuple[str, ...],
    changed_only: bool,
    python_files: list[str],
) -> dict[str, Any]:
    ranked_files = ranked_budget_file_records(included_files, focus_terms=focus_terms)
    total_estimated_tokens = sum(int(item["estimated_tokens"]) for item in ranked_files)

    return {
        "schema": {
            "name": "cbl.budget_report",
            "version": 2,
        },
        "scope": "changed" if changed_only else "full",
        "requested_budget_tokens": budget,
        "focus_terms": list(focus_terms),
        "estimation_method": ESTIMATION_METHOD,
        "total_estimated_file_tokens": total_estimated_tokens,
        "budget_pressure": "over_budget" if total_estimated_tokens > budget else "within_budget",
        "python_files_analyzed": python_files,
        "ranked_files": ranked_files[:250],
        "counts": {
            "ranked_files": len(ranked_files),
            "python_files_analyzed": len(python_files),
            "focus_terms": len(focus_terms),
        },
    }
'''

REPORTS_DIFF = r'''
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
'''

REPORTS_CONTRACT = r'''
from __future__ import annotations

from pathlib import Path
from typing import Any

from codebase_lens.reports.json import write_json_report
from codebase_lens.reports.manifest import OutputLayout


def _counts(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("counts", {})
    return dict(value) if isinstance(value, dict) else {}


def _violations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("violations", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _warnings(payload: dict[str, Any]) -> list[str]:
    value = payload.get("warnings", [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _contract_name(payload: dict[str, Any]) -> str:
    return str(payload.get("name") or payload.get("contract_name") or payload.get("contract_id") or "architecture contract")


def _violation_line(item: dict[str, Any]) -> str:
    rule = item.get("rule_id", "unknown-rule")
    severity = item.get("severity", "unknown")
    path = item.get("path") or "<repo>"
    line = item.get("line")
    evidence = item.get("evidence")
    message = item.get("message", "")

    location = f"{path}:L{line}" if line else str(path)
    rendered = f"- `{severity}` `{rule}` at `{location}` — {message}"
    if evidence:
        rendered += f" Evidence: `{evidence}`"
    return rendered


def render_contract_audit_markdown(payload: dict[str, Any]) -> str:
    counts = _counts(payload)
    violations = _violations(payload)
    warnings = _warnings(payload)

    errors = [item for item in violations if item.get("severity") == "error"]
    non_errors = [item for item in violations if item.get("severity") != "error"]

    lines: list[str] = [
        "# Architecture Contract Audit",
        "",
        "## Contract Metadata",
        "",
        f"- Contract: `{_contract_name(payload)}`",
        f"- Contract ID: `{payload.get('contract_id', payload.get('id', 'unknown'))}`",
        f"- Schema: `{payload.get('schema', {}).get('name', 'cbl.contract_audit') if isinstance(payload.get('schema'), dict) else 'cbl.contract_audit'}`",
        "",
        "## Summary",
        "",
    ]

    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")

    if not counts:
        lines.append("- No count payload was emitted.")

    lines.extend(["", "## Failed Rules", ""])
    if errors:
        lines.extend(_violation_line(item) for item in errors)
    else:
        lines.append("- No failed rules.")

    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- No warnings.")

    lines.extend(["", "## Informational Findings", ""])
    if non_errors:
        lines.extend(_violation_line(item) for item in non_errors)
    else:
        lines.append("- No non-error findings.")

    lines.extend(["", "## Passed Rules", ""])
    if not errors:
        lines.append("- Required files, required symbols, and forbidden-import checks produced no error-severity violations.")
    else:
        lines.append("- Some contract rules failed; inspect `contract_audit.json` for exact violation records.")

    lines.extend(["", "## Skipped Rules", ""])
    lines.append("- No explicit skipped-rule model is currently emitted by the contract engine.")

    lines.extend(["", "## Evidence", ""])
    if violations:
        for item in violations[:120]:
            path = item.get("path") or "<repo>"
            line = item.get("line")
            evidence = item.get("evidence") or path
            location = f"{path}:L{line}" if line else str(path)
            lines.append(f"- `{item.get('rule_id', 'unknown-rule')}` → `{location}`; evidence `{evidence}`")
        if len(violations) > 120:
            lines.append(f"- ... {len(violations) - 120} additional evidence records omitted from Markdown; see `contract_audit.json`.")
    else:
        lines.append("- `<repo>:architecture-contract`")

    lines.extend(["", "## Suggested Remediation", ""])
    if errors:
        lines.append("- Repair the failed rules above, then rerun `python -m codebase_lens contract --no-archive`.")
    else:
        lines.append("- No remediation required.")
    lines.append("- For full release validation, run `python .\\scripts\\dev\\audits\\audit_phase25_report_contract_parity.py`.")

    return "\n".join(lines).rstrip() + "\n"


def write_contract_audit_reports(
    layout: OutputLayout,
    payload: dict[str, Any],
) -> dict[str, str]:
    canonical_payload = dict(payload)
    canonical_payload.setdefault("schema", {"name": "cbl.contract_audit", "version": 1})

    write_json_report(layout.latest_dir / "contract_audit.json", canonical_payload)
    write_json_report(layout.latest_dir / "contract_report.json", canonical_payload)

    markdown = render_contract_audit_markdown(canonical_payload)
    (layout.latest_dir / "contract_audit.md").write_text(markdown, encoding="utf-8", newline="\n")

    return {
        "contract_audit_json": ".codecontext/latest/contract_audit.json",
        "contract_audit_md": ".codecontext/latest/contract_audit.md",
        "contract_report_json": ".codecontext/latest/contract_report.json",
    }
'''

SNAPSHOT_HELPERS = r'''
def _git_state_payload(repo_root: Path) -> dict[str, Any]:
    git_info = collect_git_info(repo_root)
    diff_result = collect_changed_files(repo_root, include_untracked=True)

    return {
        "schema": {
            "name": "cbl.git_state",
            "version": 1,
        },
        "git": {
            "available": git_info.available,
            "is_repo": git_info.is_repo,
            "branch": git_info.branch,
            "head": git_info.head,
            "is_dirty": git_info.is_dirty,
            "staged_count": git_info.staged_count,
            "unstaged_count": git_info.unstaged_count,
            "untracked_count": git_info.untracked_count,
            "warnings": list(git_info.warnings),
        },
        "changed_files": [_jsonable(record) for record in diff_result.changed_files],
        "counts": dict(diff_result.counts),
        "warnings": list(diff_result.warnings),
    }


def _write_git_state_report(layout: OutputLayout, repo_root: Path) -> Path:
    return write_json_report(layout.latest_dir / "git_state.json", _git_state_payload(repo_root))


def _read_json_if_present(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _read_text_excerpt(path: Path, *, max_lines: int = 80) -> str:
    if not path.is_file():
        return "(not emitted)"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines] + [f"... {len(lines) - max_lines} additional lines omitted from snapshot markdown."])
    return "\n".join(lines) if lines else "(empty)"


def _extension_summary(universe) -> list[str]:
    counts: dict[str, int] = {}
    for record in getattr(universe, "included_files", ()):
        suffix = Path(str(getattr(record, "path", ""))).suffix.lower() or "<none>"
        counts[suffix] = counts.get(suffix, 0) + 1
    return [f"- `{suffix}`: {count}" for suffix, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:40]]


def _project_markers(root: Path) -> list[str]:
    markers = [
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
    ]
    return [marker for marker in markers if (root / marker).exists()]


def _write_repo_snapshot_markdown(
    layout: OutputLayout,
    repo_root: Path,
    *,
    universe,
    outputs: dict[str, str],
    counts: dict[str, int],
    warnings: list[str],
    changed_only: bool,
    budget: int,
    focus_terms: tuple[str, ...],
) -> Path:
    git_state = _read_json_if_present(layout.latest_dir / "git_state.json")
    budget_report = _read_json_if_present(layout.latest_dir / "budget_report.json")
    omissions = _read_json_if_present(layout.latest_dir / "omissions.json")
    symbols = _read_json_if_present(layout.latest_dir / "symbol_index.json")
    imports = _read_json_if_present(layout.latest_dir / "import_graph.json")
    cli_inventory = _read_json_if_present(layout.latest_dir / "cli_inventory.json")
    tests = _read_json_if_present(layout.latest_dir / "test_inventory.json")

    git_payload = git_state.get("git", {}) if isinstance(git_state.get("git"), dict) else {}
    omission_counts = omissions.get("counts", {}) if isinstance(omissions.get("counts"), dict) else {}
    budget_counts = budget_report.get("counts", {}) if isinstance(budget_report.get("counts"), dict) else {}

    lines: list[str] = [
        "# Repository Snapshot",
        "",
        "## Generation Metadata",
        "",
        f"- Scope: `{'changed' if changed_only else 'full'}`",
        f"- Requested budget tokens: {budget}",
        f"- Focus terms: {list(focus_terms)}",
        f"- Output directory: `.codecontext/latest/`",
        "",
        "## Repository Identity",
        "",
        f"- Repository name: `{repo_root.name}`",
        "- Repository root is redacted from AI-facing Markdown by default.",
        "",
        "## Git State",
        "",
        f"- Git available: {git_payload.get('available')}",
        f"- Git repository: {git_payload.get('is_repo')}",
        f"- Branch: `{git_payload.get('branch') or '(none)'}`",
        f"- Head: `{git_payload.get('head') or '(none)'}`",
        f"- Dirty: {git_payload.get('is_dirty')}",
        f"- Staged: {git_payload.get('staged_count', 0)}",
        f"- Unstaged: {git_payload.get('unstaged_count', 0)}",
        f"- Untracked: {git_payload.get('untracked_count', 0)}",
        "",
        "## Project Markers",
        "",
    ]

    markers = _project_markers(repo_root)
    lines.extend(f"- `{marker}`" for marker in markers)
    if not markers:
        lines.append("- No standard project markers detected.")

    lines.extend(
        [
            "",
            "## File Universe Summary",
            "",
        ]
    )
    universe_counts = getattr(universe, "counts", {})
    if isinstance(universe_counts, dict):
        for key in sorted(universe_counts):
            lines.append(f"- {key}: {universe_counts[key]}")
    else:
        lines.append("- File-universe counts unavailable.")

    lines.extend(
        [
            "",
            "## Top-Level Tree",
            "",
            _read_text_excerpt(layout.latest_dir / "repo_tree.txt", max_lines=80),
            "",
            "## Language/Extension Summary",
            "",
        ]
    )
    extension_lines = _extension_summary(universe)
    lines.extend(extension_lines or ["- No extension summary available."])

    lines.extend(
        [
            "",
            "## Python Package Summary",
            "",
            f"- Python files analyzed: {counts.get('python_files_analyzed', 0)}",
            f"- Symbols: {counts.get('symbols', 0)}",
            f"- Imports: {counts.get('imports', 0)}",
            f"- Routes: {counts.get('routes', 0)}",
            f"- CLI commands: {counts.get('commands', 0)}",
            f"- Test files: {counts.get('test_files', 0)}",
            f"- Test functions: {counts.get('test_functions', 0)}",
            "",
            "## Important Symbols",
            "",
        ]
    )

    symbol_records = symbols.get("symbols", [])
    if isinstance(symbol_records, list) and symbol_records:
        for record in symbol_records[:30]:
            if isinstance(record, dict):
                name = record.get("qualified_name") or record.get("name") or "<unknown>"
                path = record.get("path", "")
                start = record.get("start_line", "?")
                end = record.get("end_line", start)
                kind = record.get("kind", "symbol")
                lines.append(f"- `{name}` ({kind}) — `{path}:L{start}-L{end}`")
    else:
        lines.append("- No symbols emitted.")

    lines.extend(["", "## CLI Inventory Summary", ""])
    cli_counts = cli_inventory.get("counts", {}) if isinstance(cli_inventory.get("counts"), dict) else {}
    if cli_counts:
        for key in sorted(cli_counts):
            lines.append(f"- {key}: {cli_counts[key]}")
    else:
        lines.append("- No CLI inventory counts emitted.")

    lines.extend(["", "## Test Inventory Summary", ""])
    test_counts = tests.get("counts", {}) if isinstance(tests.get("counts"), dict) else {}
    if test_counts:
        for key in sorted(test_counts):
            lines.append(f"- {key}: {test_counts[key]}")
    else:
        lines.append("- No test inventory counts emitted.")

    lines.extend(["", "## Import Graph Summary", ""])
    import_counts = imports.get("counts", {}) if isinstance(imports.get("counts"), dict) else {}
    if import_counts:
        for key in sorted(import_counts):
            lines.append(f"- {key}: {import_counts[key]}")
    else:
        lines.append("- No import graph counts emitted.")

    lines.extend(
        [
            "",
            "## Safety and Redaction Summary",
            "",
            f"- Redaction enabled: {getattr(getattr(universe, 'redaction', None), 'enabled', True)}",
            f"- Redacted occurrences: {getattr(getattr(universe, 'redaction', None), 'redacted_occurrences_count', 0)}",
            f"- Budget estimation method: `{budget_report.get('estimation_method', 'unknown')}`",
            f"- Budget pressure: `{budget_report.get('budget_pressure', 'unknown')}`",
            f"- Ranked files: {budget_counts.get('ranked_files', 0)}",
            "",
            "## Skipped/Omitted Files Summary",
            "",
        ]
    )

    if omission_counts:
        for key in sorted(omission_counts):
            lines.append(f"- {key}: {omission_counts[key]}")
    else:
        lines.append("- No omission counts emitted.")

    if warnings:
        lines.extend(["", "### Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings[:80])

    lines.extend(
        [
            "",
            "## Suggested Follow-Up Commands",
            "",
            "- `python -m codebase_lens pack --issue \"describe task\" --budget 24000 --no-archive`",
            "- `python -m codebase_lens diff --symbols --no-archive`",
            "- `python -m codebase_lens graph --changed --depth 1 --limit 80 --no-archive`",
            "- `python -m codebase_lens contract --no-archive`",
            "",
            "## Generated Outputs",
            "",
        ]
    )

    for key in sorted(outputs):
        lines.append(f"- `{key}` → `{outputs[key]}`")

    destination = layout.latest_dir / "repo_snapshot.md"
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return destination

'''

AUDIT = r'''
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


REQUIRED_SNAPSHOT_SECTIONS = [
    "# Repository Snapshot",
    "## Generation Metadata",
    "## Repository Identity",
    "## Git State",
    "## Project Markers",
    "## File Universe Summary",
    "## Top-Level Tree",
    "## Language/Extension Summary",
    "## Python Package Summary",
    "## Important Symbols",
    "## CLI Inventory Summary",
    "## Test Inventory Summary",
    "## Import Graph Summary",
    "## Safety and Redaction Summary",
    "## Skipped/Omitted Files Summary",
    "## Suggested Follow-Up Commands",
]

REQUIRED_DIFF_SECTIONS = [
    "# Diff Summary",
    "## Git Base",
    "## Staged Changes",
    "## Unstaged Changes",
    "## Untracked Source Files",
    "## Changed Files",
    "## Changed Symbols",
    "## Diff Stats",
    "## Follow-Up Commands",
]

REQUIRED_CONTRACT_SECTIONS = [
    "# Architecture Contract Audit",
    "## Contract Metadata",
    "## Summary",
    "## Failed Rules",
    "## Warnings",
    "## Informational Findings",
    "## Passed Rules",
    "## Skipped Rules",
    "## Evidence",
    "## Suggested Remediation",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def run_cbl(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def make_repo(base: Path) -> Path:
    repo = base / "report_contract_repo"
    package = repo / "src" / "demo_pkg"
    tests = repo / "tests"

    write(
        repo / "pyproject.toml",
        """
[project]
name = 'demo-pkg'
version = '0.0.0'
""",
    )

    write(package / "__init__.py", "")
    write(
        package / "core.py",
        """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().lower()

def build_name(name: str) -> str:
    return normalize_name(name)
""",
    )
    write(
        package / "cli.py",
        """
from __future__ import annotations

import argparse
from demo_pkg.core import build_name

def _run_build(raw: str) -> str:
    return build_name(raw)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command')
    build = sub.add_parser('build')
    build.set_defaults(handler=_run_build)
    return parser
""",
    )
    write(
        tests / "test_core.py",
        """
from demo_pkg.core import normalize_name

def test_normalize_name():
    assert normalize_name(' A ') == 'a'
""",
    )

    init = run_git(repo, "init")
    if init.returncode == 0:
        run_git(repo, "config", "user.email", "fixture@example.invalid")
        run_git(repo, "config", "user.name", "CBL Fixture")
        run_git(repo, "add", ".")
        run_git(repo, "commit", "-m", "initial")
        write(
            package / "core.py",
            """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().casefold()

def build_name(name: str) -> str:
    return normalize_name(name)

def changed_symbol() -> str:
    return build_name('changed')
""",
        )
        write(
            package / "new_file.py",
            """
from __future__ import annotations

def untracked_symbol() -> str:
    return 'new'
""",
        )

    return repo


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def assert_contains(path: Path, required: list[str]) -> None:
    if not path.is_file():
        fail(f"Missing required file: {path}")
    text = path.read_text(encoding="utf-8")
    missing = [item for item in required if item not in text]
    if missing:
        fail(f"{path} is missing required sections/text: {missing}")


def main() -> int:
    for relative in [
        "src/codebase_lens/core/budget.py",
        "src/codebase_lens/reports/snapshot.py",
        "src/codebase_lens/reports/diff.py",
        "src/codebase_lens/reports/contract.py",
        "scripts/dev/audits/audit_phase25_report_contract_parity.py",
    ]:
        assert_parseable(relative)

    snapshot_source = (ROOT / "src/codebase_lens/reports/snapshot.py").read_text(encoding="utf-8")
    if "size_bytes // 4" in snapshot_source:
        fail("Budget token estimation still lives directly in reports/snapshot.py.")

    budget_source = (ROOT / "src/codebase_lens/core/budget.py").read_text(encoding="utf-8")
    if "size_bytes // 4" not in budget_source:
        fail("Budget token estimation was not moved into core/budget.py.")

    with tempfile.TemporaryDirectory(prefix="cbl_report_contract_") as temp_dir:
        repo = make_repo(Path(temp_dir))

        snapshot = run_cbl("snapshot", "--repo", str(repo), "--no-archive")
        if snapshot.returncode != 0:
            fail(f"cbl snapshot failed:\nSTDOUT:\n{snapshot.stdout}\nSTDERR:\n{snapshot.stderr}")

        latest = repo / ".codecontext" / "latest"
        assert_contains(latest / "repo_snapshot.md", REQUIRED_SNAPSHOT_SECTIONS)

        for filename in [
            "git_state.json",
            "repo_snapshot.md",
            "snapshot_index.json",
            "file_inventory.json",
            "symbol_index.json",
            "import_graph.json",
            "cli_inventory.json",
            "test_inventory.json",
            "omissions.json",
        ]:
            if not (latest / filename).is_file():
                fail(f"snapshot did not write required report: {filename}")

        git_state = json.loads((latest / "git_state.json").read_text(encoding="utf-8"))
        if git_state.get("schema", {}).get("name") != "cbl.git_state":
            fail("git_state.json has wrong schema name.")

        diff = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
        if diff.returncode != 0:
            fail(f"cbl diff --symbols failed:\nSTDOUT:\n{diff.stdout}\nSTDERR:\n{diff.stderr}")

        assert_contains(latest / "diff_summary.md", REQUIRED_DIFF_SECTIONS)
        if not (latest / "diff.json").is_file():
            fail("diff did not write diff.json.")
        if "changed_symbols" not in json.loads((latest / "diff.json").read_text(encoding="utf-8")):
            fail("diff --symbols did not include changed_symbols in diff.json.")

    contract = run_cbl("contract", "--repo", str(ROOT), "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    assert_contains(latest / "contract_audit.md", REQUIRED_CONTRACT_SECTIONS)

    for filename in [
        "contract_audit.json",
        "contract_audit.md",
        "contract_report.json",
    ]:
        if not (latest / filename).is_file():
            fail(f"contract did not write required report or compatibility alias: {filename}")

    payload = json.loads((latest / "contract_audit.json").read_text(encoding="utf-8"))
    if payload.get("schema", {}).get("name") != "cbl.contract_audit":
        fail("contract_audit.json has wrong schema name.")

    print("PASS: Phase 25 report contract parity audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST = r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def run_cbl(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    package = repo / "src" / "demo_pkg"
    tests = repo / "tests"

    write(repo / "pyproject.toml", "[project]\nname = 'demo-pkg'\nversion = '0.0.0'\n")
    write(package / "__init__.py", "")
    write(
        package / "core.py",
        """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().lower()

def build_name(name: str) -> str:
    return normalize_name(name)
""",
    )
    write(
        package / "cli.py",
        """
from __future__ import annotations

import argparse

def run() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('build')
""",
    )
    write(
        tests / "test_core.py",
        """
from demo_pkg.core import normalize_name

def test_normalize_name():
    assert normalize_name(' A ') == 'a'
""",
    )
    return repo


def make_git_repo(tmp_path: Path) -> Path:
    repo = make_repo(tmp_path)
    if run_git(repo, "init").returncode != 0:
        return repo
    run_git(repo, "config", "user.email", "fixture@example.invalid")
    run_git(repo, "config", "user.name", "CBL Fixture")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "initial")
    write(
        repo / "src" / "demo_pkg" / "core.py",
        """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().casefold()

def build_name(name: str) -> str:
    return normalize_name(name)

def changed_symbol() -> str:
    return build_name('changed')
""",
    )
    return repo


def test_snapshot_writes_tdd_canonical_reports(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("snapshot", "--repo", str(repo), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"

    assert (latest / "repo_snapshot.md").is_file()
    assert (latest / "git_state.json").is_file()
    assert (latest / "snapshot_index.json").is_file()

    text = (latest / "repo_snapshot.md").read_text(encoding="utf-8")
    for section in [
        "# Repository Snapshot",
        "## Generation Metadata",
        "## Repository Identity",
        "## Git State",
        "## Project Markers",
        "## File Universe Summary",
        "## Top-Level Tree",
        "## Language/Extension Summary",
        "## Python Package Summary",
        "## Important Symbols",
        "## CLI Inventory Summary",
        "## Test Inventory Summary",
        "## Import Graph Summary",
        "## Safety and Redaction Summary",
        "## Skipped/Omitted Files Summary",
        "## Suggested Follow-Up Commands",
    ]:
        assert section in text

    git_state = json.loads((latest / "git_state.json").read_text(encoding="utf-8"))
    assert git_state["schema"]["name"] == "cbl.git_state"


def test_diff_writes_summary_markdown_and_changed_symbols_when_requested(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)

    result = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    assert (latest / "diff.json").is_file()
    assert (latest / "diff_summary.md").is_file()

    text = (latest / "diff_summary.md").read_text(encoding="utf-8")
    for section in [
        "# Diff Summary",
        "## Git Base",
        "## Staged Changes",
        "## Unstaged Changes",
        "## Untracked Source Files",
        "## Changed Files",
        "## Changed Symbols",
        "## Diff Stats",
        "## Follow-Up Commands",
    ]:
        assert section in text

    payload = json.loads((latest / "diff.json").read_text(encoding="utf-8"))
    assert "changed_symbols" in payload


def test_contract_writes_canonical_audit_reports_and_alias() -> None:
    result = run_cbl("contract", "--repo", str(ROOT), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = ROOT / ".codecontext" / "latest"
    assert (latest / "contract_audit.json").is_file()
    assert (latest / "contract_audit.md").is_file()
    assert (latest / "contract_report.json").is_file()

    payload = json.loads((latest / "contract_audit.json").read_text(encoding="utf-8"))
    assert payload["schema"]["name"] == "cbl.contract_audit"

    text = (latest / "contract_audit.md").read_text(encoding="utf-8")
    for section in [
        "# Architecture Contract Audit",
        "## Contract Metadata",
        "## Summary",
        "## Failed Rules",
        "## Warnings",
        "## Informational Findings",
        "## Passed Rules",
        "## Skipped Rules",
        "## Evidence",
        "## Suggested Remediation",
    ]:
        assert section in text


def test_budget_estimation_is_owned_by_core_budget() -> None:
    snapshot_source = (ROOT / "src/codebase_lens/reports/snapshot.py").read_text(encoding="utf-8")
    budget_source = (ROOT / "src/codebase_lens/core/budget.py").read_text(encoding="utf-8")

    assert "size_bytes // 4" not in snapshot_source
    assert "size_bytes // 4" in budget_source
    assert "build_budget_report_payload" in budget_source
'''

def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
    if path.suffix == ".py":
        modified.add(path)


def ensure_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text
    lines = text.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            insert_at = index + 1
    lines.insert(insert_at, import_line)
    return "\n".join(lines) + "\n"


def replace_function_block(text: str, function_name: str, replacement: str, next_function_name: str) -> str:
    pattern = rf"def {re.escape(function_name)}\([\s\S]*?\n(?=def {re.escape(next_function_name)}\()"
    new_text, count = re.subn(pattern, normalize(replacement), text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not replace {function_name}.")
    return new_text


def patch_snapshot(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "snapshot.py"
    text = path.read_text(encoding="utf-8")

    text = ensure_import(text, "from codebase_lens.core.budget import build_budget_report_payload")
    text = ensure_import(text, "from codebase_lens.git.discover import collect_git_info")

    if "from dataclasses import dataclass" in text and "from dataclasses import asdict, dataclass" not in text:
        text = text.replace("from dataclasses import dataclass", "from dataclasses import asdict, dataclass")

    replacement_budget = r'''
def _write_budget_report(
    layout: OutputLayout,
    universe,
    *,
    budget: int,
    focus_terms: tuple[str, ...],
    changed_only: bool,
    python_files: list[str],
) -> Path:
    payload = build_budget_report_payload(
        getattr(universe, "included_files", ()),
        budget=budget,
        focus_terms=focus_terms,
        changed_only=changed_only,
        python_files=python_files,
    )
    return write_json_report(layout.latest_dir / "budget_report.json", payload)

'''
    text = replace_function_block(text, "_write_budget_report", replacement_budget, "_write_snapshot_index")

    if "def _write_git_state_report(" not in text:
        marker = "def _write_snapshot_index("
        index = text.find(marker)
        if index < 0:
            raise RuntimeError("Could not find _write_snapshot_index marker.")
        text = text[:index] + normalize(SNAPSHOT_HELPERS) + "\n" + text[index:]

    if 'outputs["git_state_json"]' not in text:
        needle = '    outputs["repo_tree_txt"] = ".codecontext/latest/repo_tree.txt"\n'
        if needle not in text:
            raise RuntimeError("Could not find repo_tree_txt output assignment.")
        text = text.replace(
            needle,
            needle
            + "\n"
            + "    _write_git_state_report(layout, root)\n"
            + '    outputs["git_state_json"] = ".codecontext/latest/git_state.json"\n',
            1,
        )

    if 'outputs["repo_snapshot_md"]' not in text:
        function_start = text.find("def write_snapshot_bundle(")
        if function_start < 0:
            raise RuntimeError("Could not find write_snapshot_bundle.")
        match = re.search(r"(?m)^    .*_write_snapshot_index\(", text[function_start:])
        if not match:
            raise RuntimeError("Could not find _write_snapshot_index call inside write_snapshot_bundle.")
        insert_at = function_start + match.start()
        insertion = (
            "    _write_repo_snapshot_markdown(\n"
            "        layout,\n"
            "        root,\n"
            "        universe=universe,\n"
            "        outputs=outputs,\n"
            "        counts=counts,\n"
            "        warnings=warnings,\n"
            "        changed_only=changed_only,\n"
            "        budget=budget,\n"
            "        focus_terms=focus_terms,\n"
            "    )\n"
            '    outputs["repo_snapshot_md"] = ".codecontext/latest/repo_snapshot.md"\n'
            "\n"
        )
        text = text[:insert_at] + insertion + text[insert_at:]

    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def patch_cli(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "cli.py"
    text = path.read_text(encoding="utf-8")

    text = ensure_import(text, "from codebase_lens.reports.contract import write_contract_audit_reports")
    text = ensure_import(text, "from codebase_lens.reports.diff import write_diff_reports")

    old_diff = '''        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        diff_path = write_json_report(layout.latest_dir / "diff.json", payload)

        outputs = {
            "manifest_json": ".codecontext/latest/manifest.json",
            "diff_json": ".codecontext/latest/diff.json",
        }
'''
    new_diff = '''        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        outputs = {
            "manifest_json": ".codecontext/latest/manifest.json",
            **write_diff_reports(
                layout,
                diff_result,
                payload,
                changed_symbols_payload=payload.get("changed_symbols") if args.symbols else None,
                base=args.base,
            ),
        }
        diff_path = layout.latest_dir / "diff.json"
'''
    if old_diff in text:
        text = text.replace(old_diff, new_diff, 1)
    elif "write_diff_reports(" not in text:
        raise RuntimeError("Could not patch _run_diff output block.")

    old_contract = '''        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        contract_path = write_json_report(layout.latest_dir / "contract_report.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "contract",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "contract_report_json": ".codecontext/latest/contract_report.json",
                },
            )
        )
'''
    new_contract = '''        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        contract_outputs = write_contract_audit_reports(layout, payload)
        contract_path = layout.latest_dir / "contract_audit.json"

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "contract",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    **contract_outputs,
                },
            )
        )
'''
    if old_contract in text:
        text = text.replace(old_contract, new_contract, 1)
    elif "write_contract_audit_reports(" not in text:
        raise RuntimeError("Could not patch _run_contract output block.")

    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def list_bounds_for_key(text: str, key: str) -> tuple[int, int]:
    match = re.search(rf'(?P<quote>["\']){re.escape(key)}(?P=quote)\s*:\s*\[', text)
    if not match:
        raise RuntimeError(f"Could not find list key {key!r}.")

    open_index = text.find("[", match.start())
    depth = 0
    quote: str | None = None
    escaped = False
    i = open_index

    while i < len(text):
        ch = text[i]

        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch in {"'", '"'}:
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return open_index, i

        i += 1

    raise RuntimeError(f"Could not find closing bracket for {key!r}.")


def insert_before_list_close(text: str, key: str, block: str) -> str:
    _, close = list_bounds_for_key(text, key)
    return text[:close] + block + text[close:]


def patch_contract(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    required_files = [
        "src/codebase_lens/core/budget.py",
        "src/codebase_lens/reports/diff.py",
        "src/codebase_lens/reports/contract.py",
        "scripts/dev/audits/audit_phase25_report_contract_parity.py",
    ]

    for required_file in required_files:
        if f'"{required_file}"' not in text and f"'{required_file}'" not in text:
            text = insert_before_list_close(text, "required_files", f'            "{required_file}",\n')

    symbol_entries = [
        (
            "src/codebase_lens/core/budget.py",
            [
                "estimate_tokens_for_bytes",
                "estimate_tokens_for_text",
                "ranked_budget_file_records",
                "build_budget_report_payload",
            ],
        ),
        (
            "src/codebase_lens/reports/diff.py",
            [
                "render_diff_summary_markdown",
                "write_diff_reports",
            ],
        ),
        (
            "src/codebase_lens/reports/contract.py",
            [
                "render_contract_audit_markdown",
                "write_contract_audit_reports",
            ],
        ),
    ]

    insertions = ""
    for symbol_path, symbols in symbol_entries:
        if f'"path": "{symbol_path}"' in text or f"'path': '{symbol_path}'" in text:
            continue
        rendered_symbols = "\n".join(f'                    "{symbol}",' for symbol in symbols)
        insertions += (
            "            {\n"
            f'                "path": "{symbol_path}",\n'
            '                "symbols": [\n'
            f"{rendered_symbols}\n"
            "                ],\n"
            "            },\n"
        )

    if insertions:
        text = insert_before_list_close(text, "required_symbols", insertions)

    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def assert_parseable(paths: set[Path]) -> None:
    for path in sorted(paths):
        if path.suffix != ".py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise RuntimeError(f"Generated invalid Python in {path}: {exc}") from exc


def main() -> int:
    modified: set[Path] = set()

    write_file("src/codebase_lens/core/budget.py", CORE_BUDGET, modified)
    write_file("src/codebase_lens/reports/diff.py", REPORTS_DIFF, modified)
    write_file("src/codebase_lens/reports/contract.py", REPORTS_CONTRACT, modified)
    write_file("scripts/dev/audits/audit_phase25_report_contract_parity.py", AUDIT, modified)
    write_file("tests/test_report_contract_parity.py", TEST, modified)

    patch_snapshot(modified)
    patch_cli(modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 020 applied: report contract parity restored.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())