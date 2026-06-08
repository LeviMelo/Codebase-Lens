from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()
PROJECTION = ROOT / "src" / "codebase_lens" / "reports" / "handoff_projection.py"


EDGE_FAMILY = r'''
def _edge_family(edge: dict[str, Any], source: dict[str, Any] | None, target: dict[str, Any] | None, profile: ProjectProfile) -> str:
    kind = str(edge.get("kind") or "")
    source_role = _symbol_role(source, profile) if isinstance(source, dict) else "unknown"
    target_role = _symbol_role(target, profile) if isinstance(target, dict) else "unknown"
    source_kind = _node_kind(source)
    target_kind = _node_kind(target)
    target_path = _node_path(target)

    if kind == "file_declares_cli_command" or target_kind == "cli_command":
        return "cli_to_handler"

    if kind in {"file_imports_module", "module_resolves_to_file"}:
        if target_path and _is_product_path(target_path, profile):
            return "import_dependency"
        return "external_import_dependency"

    if source_role == "cli_surface" and target_role in {"analysis", "model_or_core", "io_or_safety", "product"}:
        return "handler_to_analysis"
    if source_role in {"analysis", "product"} and target_role == "reporting":
        return "analysis_to_report"
    if source_role == "reporting" and target_role == "reporting":
        return "report_to_output_writer"
    if source_role == "analysis" and target_role == "model_or_core":
        return "analysis_to_model"
    if source_role in {"io_or_safety", "analysis"} and target_role == "io_or_safety":
        return "scanner_or_io_flow"
    if kind == "file_contains_symbol":
        return "declaration_context"
    return "other_product_flow"
'''


EDGE_SELECTION_REASON = r'''
def _edge_selection_reason(edge: dict[str, Any], family: str) -> str:
    kind = str(edge.get("kind") or "")

    if family == "cli_to_handler":
        return "connects command or route declaration to executable surface"
    if family == "handler_to_analysis":
        return "connects command-facing handler to analysis or product logic"
    if family == "analysis_to_report":
        return "connects analysis logic to report generation"
    if family == "report_to_output_writer":
        return "connects reporting layer to output writer or renderer"
    if family == "import_dependency":
        return "shows internal project import or module dependency"
    if family == "external_import_dependency":
        return "shows external import dependency; normally omitted unless no internal alternatives exist"
    if family == "analysis_to_model":
        return "connects analysis logic to model or core structures"
    if family == "scanner_or_io_flow":
        return "connects filesystem, scanner, safety, or I/O flow"
    if kind == "file_contains_symbol":
        return "fallback declaration context for a product symbol"
    return "high-scoring product dependency edge"
'''


EDGE_RELEVANCE_SCORE = r'''
def _edge_relevance_score(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]], profile: ProjectProfile) -> float:
    kind = str(edge.get("kind") or "")
    source = _source_node(edge, nodes_by_id)
    target = _target_node(edge, nodes_by_id)
    source_path = _node_path(source)
    target_path = _node_path(target)
    source_label = _node_label(source) if source else ""
    target_label = _node_label(target) if target else str(edge.get("target_text") or "")
    source_role = _symbol_role(source, profile) if isinstance(source, dict) else "unknown"
    target_role = _symbol_role(target, profile) if isinstance(target, dict) else "unknown"
    family = _edge_family(edge, source, target, profile)

    score = 0.0

    if _is_product_path(source_path, profile):
        score += 100.0
    if _is_product_path(target_path, profile):
        score += 100.0
    if _is_low_value_path(source_path) or _is_low_value_path(target_path):
        score -= 300.0

    if kind == "symbol_calls_symbol":
        score += 150.0
    elif kind == "file_declares_cli_command":
        score += 120.0
    elif kind == "file_imports_module":
        score += 95.0
    elif kind == "module_resolves_to_file":
        score += 80.0
    elif kind == "file_contains_symbol":
        score += 10.0

    family_bonus = {
        "handler_to_analysis": 100.0,
        "analysis_to_report": 90.0,
        "analysis_to_model": 80.0,
        "scanner_or_io_flow": 70.0,
        "cli_to_handler": 65.0,
        "import_dependency": 55.0,
        "report_to_output_writer": 35.0,
        "other_product_flow": 20.0,
        "declaration_context": 0.0,
        "external_import_dependency": -120.0,
    }
    score += family_bonus.get(family, 0.0)

    if source_role in {"analysis", "reporting", "cli_surface"}:
        score += 35.0
    if target_role in {"analysis", "reporting", "model_or_core", "io_or_safety"}:
        score += 35.0

    if source_label in LOW_VALUE_HELPER_NAMES or target_label in LOW_VALUE_HELPER_NAMES:
        score -= 120.0

    if source_label.startswith(("write_", "build_", "collect_", "query_", "render_", "parse_", "scan_", "analyze_")):
        score += 35.0
    if target_label.startswith(("write_", "build_", "collect_", "query_", "render_", "parse_", "scan_", "analyze_")):
        score += 35.0

    return score
'''


REPRESENTATIVE_EDGES = r'''
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

    ranked = sorted(
        raw_candidates,
        key=lambda edge: (
            -_edge_relevance_score(edge, nodes_by_id, profile),
            str(edge.get("kind") or ""),
            _edge_evidence(edge),
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
        ),
    )

    family_caps = {
        "cli_to_handler": 4,
        "handler_to_analysis": 5,
        "analysis_to_report": 4,
        "report_to_output_writer": 3,
        "import_dependency": 4,
        "external_import_dependency": 1,
        "analysis_to_model": 4,
        "scanner_or_io_flow": 3,
        "declaration_context": 2,
        "other_product_flow": 4,
    }

    selected_edges: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str, str]] = set()
    family_counts: Counter[str] = Counter()

    families_present: list[str] = []
    for edge in ranked:
        source = _source_node(edge, nodes_by_id)
        target = _target_node(edge, nodes_by_id)
        family = _edge_family(edge, source, target, profile)
        if family not in families_present:
            families_present.append(family)

    def add(edge: dict[str, Any]) -> bool:
        payload = _edge_payload(edge, nodes_by_id, profile)
        key = (
            str(payload.get("kind")),
            str(payload.get("source")),
            str(payload.get("target")),
            str(payload.get("evidence")),
        )
        if key in selected_keys:
            return False

        family = str(payload["edge_family"])
        if family_counts[family] >= family_caps.get(family, 3):
            return False

        selected_edges.append(payload)
        selected_keys.add(key)
        family_counts[family] += 1
        return True

    for family in families_present:
        for edge in ranked:
            source = _source_node(edge, nodes_by_id)
            target = _target_node(edge, nodes_by_id)
            if _edge_family(edge, source, target, profile) == family:
                add(edge)
                break
        if len(selected_edges) >= min(limit, len(families_present)):
            break

    for edge in ranked:
        if len(selected_edges) >= limit:
            break
        add(edge)

    return selected_edges[:limit]
'''


CALL_CATEGORY = r'''
def _call_category(target_text: str) -> str:
    leaf = target_text.rsplit(".", 1)[-1]

    if leaf in {"getattr", "hasattr", "setattr", "delattr"}:
        return "reflective_attribute_read"

    if target_text in DYNAMIC_DISPATCH_TERMS or leaf in DYNAMIC_DISPATCH_TERMS:
        return "dynamic_or_dispatch"

    if any(target_text.startswith(prefix) for prefix in EXTERNAL_LIBRARY_PREFIXES):
        return "external_library"

    if _is_low_value_unresolved_call(target_text):
        return "container_or_builtin"

    if "." in target_text:
        return "attribute_or_external"

    return "unclassified_product_call"
'''


UNRESOLVED_CALL_SCORE = r'''
def _unresolved_call_score(edge: dict[str, Any], source: dict[str, Any] | None, profile: ProjectProfile) -> float:
    source_path = _node_path(source)
    source_label = _node_label(source) if source else ""
    target_text = str(edge.get("target_text") or "")
    category = _call_category(target_text)
    source_role = _symbol_role(source, profile) if isinstance(source, dict) else "unknown"

    score = 0.0

    if _is_product_path(source_path, profile):
        score += 100.0
    if source_role == "analysis":
        score += 50.0
    if source_role == "reporting":
        score += 45.0
    if source_role == "cli_surface":
        score += 45.0
    if source_label.startswith(("write_", "build_", "collect_", "query_", "render_", "parse_", "scan_", "analyze_")):
        score += 35.0

    if category == "dynamic_or_dispatch":
        score += 130.0
    elif category == "reflective_attribute_read":
        score += 10.0
    elif category == "attribute_or_external":
        score += 20.0
    elif category == "external_library":
        score -= 10.0
    elif category == "container_or_builtin":
        score -= 160.0

    if _is_low_value_path(source_path):
        score -= 300.0
    if source_label in LOW_VALUE_HELPER_NAMES:
        score -= 100.0

    return score
'''


UNRESOLVED_CALL_GROUPS = r'''
def _unresolved_call_groups(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], profile: ProjectProfile, *, limit: int) -> dict[str, Any]:
    nodes_by_id = _node_by_id(nodes)

    actual_dispatch: list[dict[str, Any]] = []
    reflective: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    attribute: list[dict[str, Any]] = []
    omitted_low_value_count = 0

    seen: set[tuple[str, str, str]] = set()

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("kind") != "symbol_calls_name":
            continue
        if edge.get("target") is not None:
            continue

        source = _source_node(edge, nodes_by_id)
        source_path = _node_path(source)
        target_text = str(edge.get("target_text") or "")

        if not _is_product_path(source_path, profile):
            continue

        key = (str(edge.get("source") or ""), target_text, _edge_evidence(edge))
        if key in seen:
            continue
        seen.add(key)

        payload = _unresolved_call_payload(edge, nodes_by_id, profile)
        category = str(payload["call_category"])

        if category == "container_or_builtin":
            omitted_low_value_count += 1
        elif category == "external_library":
            external.append(payload)
        elif category == "dynamic_or_dispatch":
            actual_dispatch.append(payload)
        elif category == "reflective_attribute_read":
            reflective.append(payload)
        else:
            attribute.append(payload)

    actual_dispatch = sorted(actual_dispatch, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]
    external = sorted(external, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]
    attribute = sorted(attribute, key=lambda item: (-float(item["relevance_score"]), str(item.get("evidence"))))[:limit]

    reflective_ranked = sorted(reflective, key=lambda item: (-float(item["relevance_score"]), str(item.get("source_path")), str(item.get("evidence"))))
    reflective_selected: list[dict[str, Any]] = []
    reflective_target_counts: Counter[str] = Counter()
    omitted_repetitive_reflection_count = 0

    for item in reflective_ranked:
        target = str(item.get("target_text") or "")
        if len(reflective_selected) >= 3 or reflective_target_counts[target] >= 2:
            omitted_repetitive_reflection_count += 1
            continue
        reflective_selected.append(item)
        reflective_target_counts[target] += 1

    return {
        "dynamic_or_dispatch_calls": actual_dispatch,
        "actual_dispatch_calls": actual_dispatch,
        "reflective_attribute_reads": reflective_selected,
        "external_library_calls": external,
        "attribute_or_external_calls": attribute,
        "omitted_low_value_unresolved_call_count": omitted_low_value_count,
        "omitted_repetitive_reflection_count": omitted_repetitive_reflection_count,
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
            evidence = f" Evidence: `{item.get('evidence')}`." if item.get("evidence") else ""
            lines.append(
                _bullet(
                    f"`{item.get('kind')}`: `{item.get('source')}` → `{item.get('target')}` "
                    f"[{item.get('confidence')}].{evidence}"
                )
            )
            lines.append(
                f"  - Family: `{item.get('edge_family')}`; reason: {item.get('selection_reason')}; "
                f"score: `{item.get('relevance_score')}`; roles: `{item.get('source_role')}` → `{item.get('target_role')}`"
            )
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

    result = run_cbl("pack", "--issue", "phase 17 projection noise audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    representative = section(text, "Representative Dependency Edges")
    unresolved = section(text, "Dynamic / Unresolved Calls")

    if "pathlib" in representative:
        fail("Representative edges still surface stdlib pathlib import.")
    if "`file_imports_module`: `src/" in representative and "target_path\": \"\"" in json.dumps(payload.get("graph", {}).get("representative_edges", [])):
        fail("Representative edges include unresolved/external imports as first-class dependencies.")

    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])
    if not edges:
        fail("No representative edges were emitted.")

    for edge in edges:
        if edge.get("kind") in {"file_imports_module", "module_resolves_to_file"} and not edge.get("target_path"):
            fail(f"External/unresolved import selected as representative edge: {edge}")
        if edge.get("edge_family") == "external_import_dependency":
            fail(f"External import dependency should be fallback-only and absent in this repo: {edge}")

    if "actual_dispatch_calls" not in graph:
        fail("Projection JSON missing actual_dispatch_calls.")
    if "reflective_attribute_reads" not in graph:
        fail("Projection JSON missing reflective_attribute_reads.")
    if "omitted_repetitive_reflection_count" not in graph:
        fail("Projection JSON missing omitted_repetitive_reflection_count.")

    dynamic = graph.get("dynamic_or_dispatch_calls", [])
    actual = graph.get("actual_dispatch_calls", [])
    reflective = graph.get("reflective_attribute_reads", [])

    if dynamic != actual:
        fail("dynamic_or_dispatch_calls should be a compatibility alias for actual_dispatch_calls.")

    for item in actual:
        if item.get("target_text") in {"getattr", "hasattr", "setattr", "delattr"}:
            fail(f"Reflective call leaked into actual dispatch calls: {item}")

    if len(reflective) > 3:
        fail("Reflective attribute reads are not capped.")

    if graph.get("omitted_repetitive_reflection_count", 0) < 1:
        fail("Repetitive reflective reads were not counted as omitted.")

    if "Reflective attribute reads" not in unresolved:
        fail("Markdown does not summarize capped reflective attribute reads.")
    if unresolved.count("getattr") > 3:
        fail("Markdown still over-displays repeated getattr calls.")

    print("PASS: Phase 17 projection noise audit passed.")
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


def test_projection_suppresses_external_import_and_repetitive_reflection_noise() -> None:
    result = run_cbl("pack", "--issue", "projection noise suppression test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = ROOT / ".codecontext" / "latest"
    text = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    representative = text[text.index("## Representative Dependency Edges"):text.index("## Dynamic / Unresolved Calls")]
    unresolved = text[text.index("## Dynamic / Unresolved Calls"):text.index("## Changed Scope")]
    graph = payload["graph"]

    assert "pathlib" not in representative

    for edge in graph["representative_edges"]:
        if edge["kind"] in {"file_imports_module", "module_resolves_to_file"}:
            assert edge["target_path"], edge
        assert edge["edge_family"] != "external_import_dependency"

    assert "actual_dispatch_calls" in graph
    assert "reflective_attribute_reads" in graph
    assert "omitted_repetitive_reflection_count" in graph
    assert graph["dynamic_or_dispatch_calls"] == graph["actual_dispatch_calls"]

    for item in graph["actual_dispatch_calls"]:
        assert item["target_text"] not in {"getattr", "hasattr", "setattr", "delattr"}

    assert len(graph["reflective_attribute_reads"]) <= 3
    assert graph["omitted_repetitive_reflection_count"] >= 1

    assert "Reflective attribute reads" in unresolved
    assert unresolved.count("getattr") <= 3
'''


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


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

    required_file = "scripts/dev/audits/audit_phase17_projection_noise.py"
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
    replacements = {
        "_edge_family": EDGE_FAMILY,
        "_edge_selection_reason": EDGE_SELECTION_REASON,
        "_edge_relevance_score": EDGE_RELEVANCE_SCORE,
        "_representative_edges": REPRESENTATIVE_EDGES,
        "_call_category": CALL_CATEGORY,
        "_unresolved_call_score": UNRESOLVED_CALL_SCORE,
        "_unresolved_call_groups": UNRESOLVED_CALL_GROUPS,
        "_render_projection_markdown": RENDER_PROJECTION_MARKDOWN,
    }

    for function_name, replacement in replacements.items():
        source = replace_function(source, function_name, replacement)

    PROJECTION.write_text(source, encoding="utf-8", newline="\n")
    modified.add(PROJECTION)

    write_file("scripts/dev/audits/audit_phase17_projection_noise.py", AUDIT, modified)
    write_file("tests/test_handoff_projection_noise.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 015F applied: projection noise suppressed for external imports and repetitive reflection.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())