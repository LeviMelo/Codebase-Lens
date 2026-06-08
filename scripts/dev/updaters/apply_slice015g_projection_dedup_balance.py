from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()
PROJECTION = ROOT / "src" / "codebase_lens" / "reports" / "handoff_projection.py"


SYMBOL_SCORE = r'''
def _symbol_score(
    node: dict[str, Any],
    incoming: Counter[str],
    outgoing: Counter[str],
    profile: ProjectProfile,
    focus_terms: tuple[str, ...] = (),
) -> float:
    node_id = _node_id(node)
    label = _node_label(node)
    path = _node_path(node)
    span = _span(node)
    connectivity = incoming[node_id] + outgoing[node_id]
    role = _symbol_role(node, profile)

    score = 0.0
    score += min(connectivity, 80) * 2.0
    score += min(span, 160) * 0.45

    if role == "analysis":
        score += 55.0
    elif role == "reporting":
        score += 50.0
    elif role == "cli_surface":
        score += 45.0
    elif role == "io_or_safety":
        score += 30.0
    elif role == "model_or_core":
        score += 25.0

    if not label.startswith("_"):
        score += 40.0

    if label.startswith((
        "write_",
        "build_",
        "collect_",
        "query_",
        "render_",
        "discover_",
        "evaluate_",
        "load_",
        "map_",
        "parse_",
        "scan_",
        "analyze_",
    )):
        score += 45.0

    if label in LOW_VALUE_HELPER_NAMES:
        score -= 120.0

    if label.startswith("_") and span <= 4:
        score -= 60.0

    if _is_low_value_path(path):
        score -= 250.0

    focus_blob = " ".join(focus_terms).lower()
    self_projection_blob = f"{path} {label}".lower()
    focus_mentions_projection = any(term in focus_blob for term in {"handoff", "projection", "pack"})
    if "handoff" in self_projection_blob and "projection" in self_projection_blob and not focus_mentions_projection:
        score -= 90.0

    return score
'''


RANK_PRODUCT_SYMBOLS = r'''
def _rank_product_symbols(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    profile: ProjectProfile,
    *,
    limit: int,
    focus_terms: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    incoming = Counter(str(edge.get("target")) for edge in edges if isinstance(edge, dict) and edge.get("target"))
    outgoing = Counter(str(edge.get("source")) for edge in edges if isinstance(edge, dict) and edge.get("source"))

    symbols = [
        node
        for node in nodes
        if isinstance(node, dict)
        and node.get("kind") == "symbol"
        and _is_product_path(_node_path(node), profile)
    ]

    ranked = sorted(
        symbols,
        key=lambda node: (
            -_symbol_score(node, incoming, outgoing, profile, focus_terms=focus_terms),
            _node_path(node),
            _node_label(node),
        ),
    )
    return ranked[:limit]
'''


REPRESENTATIVE_HELPERS_AND_FUNCTION = r'''
def _representative_edge_key(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(payload.get("kind") or ""),
        str(payload.get("source") or ""),
        str(payload.get("target") or ""),
        str(payload.get("edge_family") or ""),
    )


def _collapse_representative_edge_candidates(
    ranked_edges: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    profile: ProjectProfile,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for edge in ranked_edges:
        payload = _edge_payload(edge, nodes_by_id, profile)
        key = _representative_edge_key(payload)
        evidence = str(payload.get("evidence") or "")
        score = float(payload.get("relevance_score") or 0.0)

        if key not in groups:
            groups[key] = {
                "payload": payload,
                "best_score": score,
                "evidence_count": 0,
                "sample_evidence": [],
            }

        group = groups[key]
        group["evidence_count"] = int(group["evidence_count"]) + 1

        samples = group["sample_evidence"]
        if evidence and evidence not in samples:
            samples.append(evidence)

        if score > float(group["best_score"]):
            group["payload"] = payload
            group["best_score"] = score

    collapsed: list[dict[str, Any]] = []
    for group in groups.values():
        payload = dict(group["payload"])
        samples = list(group["sample_evidence"])[:5]
        payload["evidence_count"] = int(group["evidence_count"])
        payload["sample_evidence"] = samples
        if samples:
            payload["evidence"] = samples[0]
        collapsed.append(payload)

    return sorted(
        collapsed,
        key=lambda item: (
            -float(item.get("relevance_score") or 0.0),
            -int(item.get("evidence_count") or 0),
            str(item.get("edge_family") or ""),
            str(item.get("source") or ""),
            str(item.get("target") or ""),
        ),
    )


def _representative_edges(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], profile: ProjectProfile, *, limit: int) -> list[dict[str, Any]]:
    nodes_by_id = _node_by_id(nodes)

    allowed = {
        "symbol_calls_symbol",
        "file_declares_cli_command",
        "file_imports_module",
        "module_resolves_to_file",
        "file_contains_symbol",
    }

    raw_candidates: list[dict[str, Any]] = []
    fallback_external_imports: list[dict[str, Any]] = []

    for edge in edges:
        if not isinstance(edge, dict):
            continue

        kind = str(edge.get("kind") or "")
        if kind not in allowed:
            continue

        source = _source_node(edge, nodes_by_id)
        target = _target_node(edge, nodes_by_id)
        source_path = _node_path(source)
        target_path = _node_path(target)

        if not (_is_product_path(source_path, profile) or _is_product_path(target_path, profile)):
            continue

        if kind in {"file_imports_module", "module_resolves_to_file"}:
            if not target_path or not _is_product_path(target_path, profile):
                fallback_external_imports.append(edge)
                continue

        if kind == "file_contains_symbol" and not _is_product_path(source_path, profile):
            continue

        raw_candidates.append(edge)

    if not raw_candidates:
        raw_candidates = fallback_external_imports

    ranked_edges = sorted(
        raw_candidates,
        key=lambda edge: (
            -_edge_relevance_score(edge, nodes_by_id, profile),
            str(edge.get("kind") or ""),
            _edge_evidence(edge),
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
        ),
    )

    ranked = _collapse_representative_edge_candidates(ranked_edges, nodes_by_id, profile)

    family_caps = {
        "cli_to_handler": 3,
        "handler_to_analysis": 4,
        "analysis_to_report": 3,
        "report_to_output_writer": 2,
        "import_dependency": 3,
        "external_import_dependency": 1,
        "analysis_to_model": 3,
        "scanner_or_io_flow": 3,
        "declaration_context": 1,
        "other_product_flow": 3,
    }

    coverage_order = [
        "handler_to_analysis",
        "analysis_to_model",
        "scanner_or_io_flow",
        "analysis_to_report",
        "report_to_output_writer",
        "cli_to_handler",
        "import_dependency",
        "other_product_flow",
        "declaration_context",
        "external_import_dependency",
    ]

    selected_edges: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str, str]] = set()
    family_counts: Counter[str] = Counter()

    def add(payload: dict[str, Any]) -> bool:
        key = _representative_edge_key(payload)
        if key in selected_keys:
            return False

        family = str(payload.get("edge_family") or "")
        if family_counts[family] >= family_caps.get(family, 2):
            return False

        selected_edges.append(payload)
        selected_keys.add(key)
        family_counts[family] += 1
        return True

    for family in coverage_order:
        for payload in ranked:
            if payload.get("edge_family") == family:
                add(payload)
                break
        if len(selected_edges) >= limit:
            break

    for payload in ranked:
        if len(selected_edges) >= limit:
            break
        add(payload)

    return selected_edges[:limit]
'''


PROJECTION_PAYLOAD = r'''
def _projection_payload(
    layout: OutputLayout,
    *,
    issue: str | None,
    changed_only: bool,
    budget: int,
    focus_terms: tuple[str, ...],
    counts: dict[str, int],
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    graph = _read_json(layout.latest_dir / "evidence_graph.json")
    graph_counts = _as_dict(graph.get("counts"))
    nodes = [node for node in _as_list(graph.get("nodes")) if isinstance(node, dict)]
    edges = [edge for edge in _as_list(graph.get("edges")) if isinstance(edge, dict)]
    profile = _infer_project_profile(nodes)
    budget_report = _read_json(layout.latest_dir / "budget_report.json")
    changed_files, changed_symbols = _changed_records(layout, limit=20)

    node_kinds = Counter(str(node.get("kind")) for node in nodes)
    edge_kinds = Counter(str(edge.get("kind")) for edge in edges)
    unresolved_groups = _unresolved_call_groups(nodes, edges, profile, limit=16)

    return {
        "schema": {
            "name": "cbl.handoff_projection",
            "version": 4,
        },
        "issue": issue,
        "scope": "changed" if changed_only else "full",
        "project_profile": {
            "source_prefixes": list(profile.source_prefixes),
            "cli_paths": list(profile.cli_paths),
        },
        "budget": {
            "requested_budget_tokens": budget,
            "budget_pressure": budget_report.get("budget_pressure"),
            "focus_terms": list(focus_terms),
            "estimation_method": budget_report.get("estimation_method"),
        },
        "counts": {
            **counts,
            "evidence_graph_nodes": graph_counts.get("nodes", counts.get("evidence_graph_nodes", 0)),
            "evidence_graph_edges": graph_counts.get("edges", counts.get("evidence_graph_edges", 0)),
            "evidence_graph_unresolved_edges": graph_counts.get("unresolved_edges", counts.get("evidence_graph_unresolved_edges", 0)),
        },
        "graph": {
            "node_kinds": dict(sorted(node_kinds.items())),
            "edge_kinds": dict(sorted(edge_kinds.items())),
            "high_connectivity_product_symbols": [
                {
                    "label": node.get("label"),
                    "kind": node.get("kind"),
                    "location": _node_location(node),
                    "display": _display_node(node),
                    "role": _symbol_role(node, profile),
                    "signature": _node_data(node).get("signature"),
                }
                for node in _rank_product_symbols(nodes, edges, profile, limit=12, focus_terms=focus_terms)
            ],
            "entrypoints": [
                {
                    "label": node.get("label"),
                    "kind": node.get("kind"),
                    "location": _node_location(node),
                    "display": _display_node(node),
                    "data": _node_data(node),
                }
                for node in _entrypoints(nodes, limit=18)
            ],
            "representative_edges": _representative_edges(nodes, edges, profile, limit=20),
            "unresolved_static_calls": unresolved_groups["dynamic_or_dispatch_calls"],
            **unresolved_groups,
        },
        "changed_scope": {
            "changed_only": changed_only,
            "changed_files": changed_files,
            "changed_symbols": changed_symbols,
            "empty_changed_scope": bool(changed_only and not changed_files and not changed_symbols),
        },
        "sidecar_artifacts": {
            "legacy_ai_handoff_md": ".codecontext/latest/ai_handoff.md",
            "handoff_projection_md": ".codecontext/latest/handoff_projection.md",
            "handoff_projection_json": ".codecontext/latest/handoff_projection.json",
            "evidence_graph_json": ".codecontext/latest/evidence_graph.json",
            "graph_summary_md": ".codecontext/latest/graph_summary.md",
            "symbol_graph_json": ".codecontext/latest/symbol_graph.json",
            "symbol_graph_md": ".codecontext/latest/symbol_graph.md",
            "call_graph_json": ".codecontext/latest/call_graph.json",
            "module_graph_json": ".codecontext/latest/module_graph.json",
        },
        "warnings": list(warnings),
    }
'''


RENDER_PROJECTION_MARKDOWN = r'''
def _render_projection_markdown(payload: dict[str, Any]) -> str:
    budget = _as_dict(payload.get("budget"))
    counts = _as_dict(payload.get("counts"))
    graph = _as_dict(payload.get("graph"))
    changed_scope = _as_dict(payload.get("changed_scope"))
    artifacts = _as_dict(payload.get("sidecar_artifacts"))
    project_profile = _as_dict(payload.get("project_profile"))

    product_symbols = _as_list(graph.get("high_connectivity_product_symbols"))
    entrypoints = _as_list(graph.get("entrypoints"))
    representative_edges = _as_list(graph.get("representative_edges"))
    actual_dispatch_calls = _as_list(graph.get("actual_dispatch_calls") or graph.get("dynamic_or_dispatch_calls"))
    reflective_reads = _as_list(graph.get("reflective_attribute_reads"))
    external_calls = _as_list(graph.get("external_library_calls"))
    attribute_calls = _as_list(graph.get("attribute_or_external_calls"))
    omitted_low_value_count = int(graph.get("omitted_low_value_unresolved_call_count") or 0)
    omitted_reflection_count = int(graph.get("omitted_repetitive_reflection_count") or 0)
    changed_files = _as_list(changed_scope.get("changed_files"))
    changed_symbols = _as_list(changed_scope.get("changed_symbols"))

    lines: list[str] = [
        "# CBL Handoff Projection",
        "",
        "This sidecar is a compact graph-projection view over the CBL evidence artifacts. The legacy `ai_handoff.md` is preserved unchanged.",
        "",
        "## Purpose",
        "",
        "- Provide a lower-noise AI-facing map of the repository without embedding raw source or a full symbol graph dump.",
        "- Point the user or downstream AI toward exact follow-up CBL commands for high-resolution source retrieval.",
        "- Preserve evidence discipline: graph facts are derived from `.codecontext/latest/evidence_graph.json` and related sidecars.",
        "",
        "## Repository State",
        "",
        _bullet(f"Issue/context: `{payload.get('issue') or '(none provided)'}`"),
        _bullet(f"Scope: `{payload.get('scope')}`"),
        _bullet(f"Included files: `{counts.get('included_files', 0)}`"),
        _bullet(f"Python files analyzed: `{counts.get('python_files_analyzed', 0)}`"),
        _bullet(f"Symbols: `{counts.get('symbols', 0)}`"),
        _bullet(f"Imports: `{counts.get('imports', 0)}`"),
        _bullet(f"CLI commands: `{counts.get('commands', 0)}`"),
        _bullet(f"Test functions: `{counts.get('test_functions', 0)}`"),
        "",
        "## Project Profile",
        "",
        _bullet(f"Inferred source prefixes: `{project_profile.get('source_prefixes', [])}`"),
        _bullet(f"CLI paths: `{project_profile.get('cli_paths', [])}`"),
        "",
        "## Budget",
        "",
        _bullet(f"Requested budget tokens: `{budget.get('requested_budget_tokens')}`"),
        _bullet(f"Budget pressure: `{budget.get('budget_pressure')}`"),
        _bullet(f"Focus terms: `{budget.get('focus_terms', [])}`"),
        _bullet(f"Estimation method: `{budget.get('estimation_method')}`"),
        "",
        "## Evidence Graph Summary",
        "",
        _bullet(f"Evidence graph nodes: `{counts.get('evidence_graph_nodes', 0)}`"),
        _bullet(f"Evidence graph edges: `{counts.get('evidence_graph_edges', 0)}`"),
        _bullet(f"Unresolved graph edges: `{counts.get('evidence_graph_unresolved_edges', 0)}`"),
        "",
        "## Entrypoints",
        "",
    ]

    if entrypoints:
        for item in entrypoints:
            if not isinstance(item, dict):
                continue
            location = item.get("location") or "no direct location"
            lines.append(_bullet(f"`{item.get('label')}` ({item.get('kind')}) → `{location}`"))
    else:
        lines.append("- No CLI command or route entrypoints were selected for this projection.")

    lines.extend(["", "## High-Connectivity Product Symbols", ""])
    if product_symbols:
        for item in product_symbols:
            if not isinstance(item, dict):
                continue
            label = item.get("display") or item.get("label")
            location = item.get("location") or "no direct location"
            signature = item.get("signature") or "signature unavailable"
            role = item.get("role") or "unknown"
            lines.append(_bullet(f"`{label}` → `{location}`"))
            lines.append(f"  - Role: `{role}`")
            lines.append(f"  - Signature: `{signature}`")
    else:
        lines.append("- No product symbols were selected.")

    lines.extend(["", "## Representative Dependency Edges", ""])
    if representative_edges:
        for item in representative_edges:
            if not isinstance(item, dict):
                continue
            sample_evidence = _as_list(item.get("sample_evidence"))
            evidence = sample_evidence[0] if sample_evidence else item.get("evidence")
            evidence_count = int(item.get("evidence_count") or (1 if evidence else 0))
            evidence_text = f" Evidence: `{evidence}`." if evidence else ""
            lines.append(
                _bullet(
                    f"`{item.get('kind')}`: `{item.get('source')}` → `{item.get('target')}` "
                    f"[{item.get('confidence')}].{evidence_text}"
                )
            )
            lines.append(
                f"  - Family: `{item.get('edge_family')}`; reason: {item.get('selection_reason')}; "
                f"score: `{item.get('relevance_score')}`; roles: `{item.get('source_role')}` → `{item.get('target_role')}`"
            )
            if evidence_count > 1:
                shown = ", ".join(f"`{value}`" for value in sample_evidence[:3])
                lines.append(f"  - Evidence count: `{evidence_count}`; sample evidence: {shown}")
    else:
        lines.append("- No representative product dependency edges were selected.")

    lines.extend(["", "## Dynamic / Unresolved Calls", ""])
    if actual_dispatch_calls:
        lines.append("Actual dispatch-like unresolved calls:")
        for item in actual_dispatch_calls:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence} [{item.get('confidence')}]."))
    else:
        lines.append("- No actual dynamic dispatch-like unresolved product-code calls were selected.")

    if reflective_reads:
        lines.append("")
        lines.append("Reflective attribute reads, capped as lower-value dynamic evidence:")
        for item in reflective_reads:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence}."))

    if omitted_reflection_count:
        lines.append("")
        lines.append(f"Repetitive reflective reads omitted from Markdown: `{omitted_reflection_count}`.")

    if external_calls:
        lines.append("")
        lines.append("External/library calls summarized, not treated as architectural dispatch:")
        for item in external_calls[:8]:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence}."))

    if attribute_calls:
        lines.append("")
        lines.append(f"Attribute/external unresolved calls retained in JSON: `{len(attribute_calls)}` shown in `handoff_projection.json`.")

    if omitted_low_value_count:
        lines.append("")
        lines.append(f"Low-value builtin/container unresolved calls omitted from Markdown: `{omitted_low_value_count}`.")

    lines.extend(["", "## Changed Scope", ""])
    if changed_scope.get("empty_changed_scope"):
        lines.append("- No Git changes detected for this changed-only pack.")
        lines.append("- Changed-file and changed-symbol lists are intentionally empty.")
    else:
        lines.append(_bullet(f"Changed only: `{changed_scope.get('changed_only')}`"))
        lines.append(_bullet(f"Changed files shown: `{len(changed_files)}`"))
        lines.append(_bullet(f"Changed symbols shown: `{len(changed_symbols)}`"))

    if changed_files:
        lines.append("")
        lines.append("Changed files:")
        for item in changed_files:
            if isinstance(item, dict):
                lines.append(_bullet(f"`{item.get('path')}` [{item.get('status')}, {item.get('origin')}]"))

    if changed_symbols:
        lines.append("")
        lines.append("Changed symbols:")
        for item in changed_symbols:
            if isinstance(item, dict):
                lines.append(_bullet(f"`{item.get('qualified_name')}` → `{item.get('path')}:L{item.get('start_line')}-L{item.get('end_line')}`"))

    lines.extend(
        [
            "",
            "## Follow-Up Commands",
            "",
            "- `cbl graph --symbol <symbol> --depth 2 --budget 24000`",
            "- `cbl graph --path <path> --depth 1 --budget 24000`",
            "- `cbl symbol --name <symbol> --context 80`",
            "- `cbl file --path <path> --lines <start>:<end>`",
            "- `cbl callers --name <symbol>`",
            "- `cbl imports --module <module>`",
            "- `cbl pack --issue \"<issue>\" --budget 24000`",
            "",
            "## Sidecar Artifacts",
            "",
        ]
    )

    for key, value in sorted(artifacts.items()):
        lines.append(_bullet(f"`{key}` → `{value}`"))

    warnings = _as_list(payload.get("warnings"))
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings[:20]:
            lines.append(_bullet(str(warning)))
        if len(warnings) > 20:
            lines.append(_bullet(f"... {len(warnings) - 20} additional warnings omitted."))

    return "\n".join(lines).rstrip() + "\n"
'''


AUDIT = r'''
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def run_cbl(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start == -1:
        fail(f"Missing section: {heading}")
    next_start = text.find("\n## ", start + len(marker))
    if next_start == -1:
        return text[start:]
    return text[start:next_start]


def main() -> int:
    for relative in [
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 18 projection dedup audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))
    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])

    if payload.get("schema", {}).get("version") != 4:
        fail("handoff_projection schema version was not advanced to 4.")

    if not edges:
        fail("No representative edges emitted.")

    keys = [
        (
            edge.get("kind"),
            edge.get("source"),
            edge.get("target"),
            edge.get("edge_family"),
        )
        for edge in edges
    ]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        fail(f"Representative edge duplicates remain: {duplicates[:5]}")

    for edge in edges:
        if "evidence_count" not in edge:
            fail(f"Representative edge missing evidence_count: {edge}")
        if "sample_evidence" not in edge:
            fail(f"Representative edge missing sample_evidence: {edge}")
        if int(edge.get("evidence_count") or 0) < 1:
            fail(f"Representative edge has invalid evidence_count: {edge}")
        samples = edge.get("sample_evidence")
        if not isinstance(samples, list):
            fail(f"Representative edge sample_evidence is not a list: {edge}")

    family_counts = Counter(str(edge.get("edge_family")) for edge in edges)
    if family_counts["report_to_output_writer"] > 2:
        fail("report_to_output_writer consumed too many representative slots.")
    if family_counts["declaration_context"] > 1:
        fail("declaration_context consumed too many representative slots.")
    if family_counts["handler_to_analysis"] > 4:
        fail("handler_to_analysis consumed too many representative slots.")

    representative = section(text, "Representative Dependency Edges")
    if "Evidence count:" not in representative:
        fail("Markdown does not surface collapsed evidence counts.")

    report_pairs = [
        (edge.get("source"), edge.get("target"))
        for edge in edges
        if edge.get("edge_family") == "report_to_output_writer"
    ]
    if len(report_pairs) != len(set(report_pairs)):
        fail("Duplicate report writer source-target pairs remain.")

    symbols = graph.get("high_connectivity_product_symbols", [])
    top_six_blob = json.dumps(symbols[:6], sort_keys=True)
    if "handoff_projection.py::_render_projection_markdown" in top_six_blob:
        fail("Projection renderer still appears in the top-six product symbols without projection focus.")

    print("PASS: Phase 18 projection deduplication and coverage audit passed.")
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
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run_cbl(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_projection_deduplicates_edges_and_balances_coverage() -> None:
    result = run_cbl("pack", "--issue", "projection dedup balance test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    assert payload["schema"]["version"] == 4

    edges = payload["graph"]["representative_edges"]
    assert edges

    keys = [
        (
            edge["kind"],
            edge["source"],
            edge["target"],
            edge["edge_family"],
        )
        for edge in edges
    ]
    assert len(keys) == len(set(keys))

    for edge in edges:
        assert "evidence_count" in edge
        assert "sample_evidence" in edge
        assert edge["evidence_count"] >= 1
        assert isinstance(edge["sample_evidence"], list)

    families = Counter(edge["edge_family"] for edge in edges)
    assert families["report_to_output_writer"] <= 2
    assert families["declaration_context"] <= 1
    assert families["handler_to_analysis"] <= 4

    representative = text[text.index("## Representative Dependency Edges"):text.index("## Dynamic / Unresolved Calls")]
    assert "Evidence count:" in representative

    top_six = json.dumps(payload["graph"]["high_connectivity_product_symbols"][:6], sort_keys=True)
    assert "handoff_projection.py::_render_projection_markdown" not in top_six
'''


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def remove_functions(source: str, names: set[str]) -> str:
    tree = ast.parse(source)
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            if node.end_lineno is None:
                raise RuntimeError(f"AST node for {node.name} has no end_lineno.")
            spans.append((node.lineno, node.end_lineno))

    if not spans:
        return source

    lines = source.splitlines()
    remove_lines: set[int] = set()
    for start, end in spans:
        remove_lines.update(range(start, end + 1))

    kept = [line for index, line in enumerate(lines, start=1) if index not in remove_lines]
    return "\n".join(kept).rstrip() + "\n"


def replace_function(source: str, function_name: str, replacement: str) -> str:
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one function named {function_name}, found {len(matches)}.")

    node = matches[0]
    if node.end_lineno is None:
        raise RuntimeError(f"AST node for {function_name} has no end_lineno.")

    lines = source.splitlines()
    new_lines = lines[: node.lineno - 1] + normalize(replacement).splitlines() + lines[node.end_lineno :]
    return "\n".join(new_lines).rstrip() + "\n"


def write_file(relative: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
    if path.suffix == ".py":
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

    required_file = "scripts/dev/audits/audit_phase18_projection_dedup.py"
    if f'"{required_file}"' not in text and f"'{required_file}'" not in text:
        text = insert_before_list_close(text, "required_files", f'            "{required_file}",\n')

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

    source = PROJECTION.read_text(encoding="utf-8")
    source = remove_functions(
        source,
        {
            "_representative_edge_key",
            "_collapse_representative_edge_candidates",
        },
    )

    replacements = {
        "_symbol_score": SYMBOL_SCORE,
        "_rank_product_symbols": RANK_PRODUCT_SYMBOLS,
        "_representative_edges": REPRESENTATIVE_HELPERS_AND_FUNCTION,
        "_projection_payload": PROJECTION_PAYLOAD,
        "_render_projection_markdown": RENDER_PROJECTION_MARKDOWN,
    }

    for function_name, replacement in replacements.items():
        source = replace_function(source, function_name, replacement)

    PROJECTION.write_text(source, encoding="utf-8", newline="\n")
    modified.add(PROJECTION)

    write_file("scripts/dev/audits/audit_phase18_projection_dedup.py", AUDIT, modified)
    write_file("tests/test_handoff_projection_dedup.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 015G applied: projection representative edges deduplicated and coverage-balanced.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())