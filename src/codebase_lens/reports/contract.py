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
