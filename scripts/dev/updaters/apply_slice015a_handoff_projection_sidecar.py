from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

HANDOFF_PROJECTION = r'''
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codebase_lens.reports.json import write_json_report
from codebase_lens.reports.manifest import OutputLayout


@dataclass(frozen=True)
class HandoffProjectionResult:
    outputs: dict[str, str]
    counts: dict[str, int]
    warnings: tuple[str, ...]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _node_location(node: dict[str, Any]) -> str:
    path = node.get("path")
    line_range = node.get("line_range")
    if not path:
        return ""

    if isinstance(line_range, list) and len(line_range) == 2:
        return f"{path}:L{line_range[0]}-L{line_range[1]}"

    if isinstance(line_range, tuple) and len(line_range) == 2:
        return f"{path}:L{line_range[0]}-L{line_range[1]}"

    return str(path)


def _edge_evidence(edge: dict[str, Any]) -> str:
    evidence = edge.get("evidence")
    if isinstance(evidence, list) and evidence:
        return str(evidence[0])
    if isinstance(evidence, tuple) and evidence:
        return str(evidence[0])
    return ""


def _node_labels(nodes: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(node.get("id")): str(node.get("label") or node.get("id"))
        for node in nodes
        if isinstance(node, dict)
    }


def _rank_product_symbols(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    incoming = Counter(str(edge.get("target")) for edge in edges if isinstance(edge, dict) and edge.get("target"))
    outgoing = Counter(str(edge.get("source")) for edge in edges if isinstance(edge, dict) and edge.get("source"))

    symbols = [
        node
        for node in nodes
        if isinstance(node, dict)
        and node.get("kind") == "symbol"
        and str(node.get("path") or "").startswith("src/codebase_lens/")
    ]

    def priority(node: dict[str, Any]) -> tuple[int, str, str]:
        node_id = str(node.get("id") or "")
        return (-(incoming[node_id] + outgoing[node_id]), str(node.get("path") or ""), str(node.get("label") or ""))

    return sorted(symbols, key=priority)[:limit]


def _entrypoints(nodes: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    values = [
        node
        for node in nodes
        if isinstance(node, dict) and node.get("kind") in {"cli_command", "route"}
    ]
    return sorted(values, key=lambda node: (str(node.get("kind")), str(node.get("label"))))[:limit]


def _representative_edges(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    labels = _node_labels(nodes)
    selected: list[dict[str, Any]] = []

    preferred = {
        "symbol_calls_symbol",
        "file_imports_module",
        "file_declares_cli_command",
        "file_contains_symbol",
        "module_resolves_to_file",
    }

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("kind") not in preferred:
            continue
        source = labels.get(str(edge.get("source")), str(edge.get("source")))
        target = labels.get(str(edge.get("target")), str(edge.get("target") or edge.get("target_text") or "<unresolved>"))
        selected.append(
            {
                "kind": edge.get("kind"),
                "source": source,
                "target": target,
                "confidence": edge.get("confidence"),
                "evidence": _edge_evidence(edge),
            }
        )
        if len(selected) >= limit:
            break

    return selected


def _unresolved_calls(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    labels = _node_labels(nodes)
    selected: list[dict[str, Any]] = []

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("kind") != "symbol_calls_name":
            continue
        if edge.get("target") is not None:
            continue

        source_id = str(edge.get("source") or "")
        selected.append(
            {
                "source": labels.get(source_id, source_id),
                "target_text": edge.get("target_text"),
                "confidence": edge.get("confidence"),
                "evidence": _edge_evidence(edge),
            }
        )
        if len(selected) >= limit:
            break

    return selected


def _changed_records(layout: OutputLayout, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changed_files = _as_list(_read_json(layout.latest_dir / "changed_files.json").get("changed_files"))
    changed_symbols = _as_list(_read_json(layout.latest_dir / "changed_symbols.json").get("changed_symbols"))

    files = [item for item in changed_files if isinstance(item, dict)][:limit]
    symbols = [item for item in changed_symbols if isinstance(item, dict)][:limit]
    return files, symbols


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
    budget_report = _read_json(layout.latest_dir / "budget_report.json")
    changed_files, changed_symbols = _changed_records(layout, limit=20)

    node_kinds = Counter(str(node.get("kind")) for node in nodes)
    edge_kinds = Counter(str(edge.get("kind")) for edge in edges)

    return {
        "schema": {
            "name": "cbl.handoff_projection",
            "version": 1,
        },
        "issue": issue,
        "scope": "changed" if changed_only else "full",
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
                    "signature": _as_dict(node.get("data")).get("signature"),
                }
                for node in _rank_product_symbols(nodes, edges, limit=12)
            ],
            "entrypoints": [
                {
                    "label": node.get("label"),
                    "kind": node.get("kind"),
                    "location": _node_location(node),
                    "data": _as_dict(node.get("data")),
                }
                for node in _entrypoints(nodes, limit=16)
            ],
            "representative_edges": _representative_edges(nodes, edges, limit=20),
            "unresolved_static_calls": _unresolved_calls(nodes, edges, limit=20),
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


def _bullet(text: str) -> str:
    return f"- {text}"


def _render_projection_markdown(payload: dict[str, Any]) -> str:
    budget = _as_dict(payload.get("budget"))
    counts = _as_dict(payload.get("counts"))
    graph = _as_dict(payload.get("graph"))
    changed_scope = _as_dict(payload.get("changed_scope"))
    artifacts = _as_dict(payload.get("sidecar_artifacts"))

    product_symbols = _as_list(graph.get("high_connectivity_product_symbols"))
    entrypoints = _as_list(graph.get("entrypoints"))
    representative_edges = _as_list(graph.get("representative_edges"))
    unresolved_calls = _as_list(graph.get("unresolved_static_calls"))
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
            label = item.get("label")
            location = item.get("location") or "no direct location"
            signature = item.get("signature") or "signature unavailable"
            lines.append(_bullet(f"`{label}` → `{location}`"))
            lines.append(f"  - Signature: `{signature}`")
    else:
        lines.append("- No product symbols under `src/codebase_lens/` were selected.")

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
    else:
        lines.append("- No representative dependency edges were selected.")

    lines.extend(["", "## Dynamic / Unresolved Calls", ""])
    if unresolved_calls:
        for item in unresolved_calls:
            if not isinstance(item, dict):
                continue
            evidence = f" at `{item.get('evidence')}`" if item.get("evidence") else ""
            lines.append(_bullet(f"`{item.get('source')}` calls `{item.get('target_text')}`{evidence} [{item.get('confidence')}]."))
    else:
        lines.append("- No unresolved static call-name edges were selected.")

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


def write_handoff_projection_reports(
    layout: OutputLayout,
    *,
    issue: str | None,
    changed_only: bool,
    budget: int,
    focus_terms: tuple[str, ...],
    counts: dict[str, int],
    warnings: tuple[str, ...],
) -> dict[str, str]:
    payload = _projection_payload(
        layout,
        issue=issue,
        changed_only=changed_only,
        budget=budget,
        focus_terms=focus_terms,
        counts=counts,
        warnings=warnings,
    )

    write_json_report(layout.latest_dir / "handoff_projection.json", payload)
    (layout.latest_dir / "handoff_projection.md").write_text(
        _render_projection_markdown(payload),
        encoding="utf-8",
        newline="\n",
    )

    return {
        "handoff_projection_json": ".codecontext/latest/handoff_projection.json",
        "handoff_projection_md": ".codecontext/latest/handoff_projection.md",
    }
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


def main() -> int:
    for relative in [
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 13 sidecar projection audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    for name in ["ai_handoff.md", "handoff_projection.md", "handoff_projection.json", "pack_index.json", "evidence_graph.json"]:
        if not (latest / name).is_file():
            fail(f"Missing expected output: {name}")

    legacy = (latest / "ai_handoff.md").read_text(encoding="utf-8")
    projection = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))
    pack_index = json.loads((latest / "pack_index.json").read_text(encoding="utf-8"))

    if "# CBL AI Handoff Pack" not in legacy:
        fail("Legacy ai_handoff.md title was not preserved.")

    required_sections = [
        "# CBL Handoff Projection",
        "## Purpose",
        "## Repository State",
        "## Budget",
        "## Evidence Graph Summary",
        "## Entrypoints",
        "## High-Connectivity Product Symbols",
        "## Representative Dependency Edges",
        "## Dynamic / Unresolved Calls",
        "## Changed Scope",
        "## Follow-Up Commands",
        "## Sidecar Artifacts",
    ]
    for marker in required_sections:
        if marker not in projection:
            fail(f"handoff_projection.md missing section: {marker}")

    required_phrases = [
        "The legacy `ai_handoff.md` is preserved unchanged.",
        "evidence_graph.json",
        "symbol_graph.json",
        "cbl graph --symbol <symbol> --depth 2",
    ]
    for phrase in required_phrases:
        if phrase not in projection:
            fail(f"handoff_projection.md missing phrase: {phrase}")

    if "# CBL Symbol Relationship Graph\n\nEvidence scope:" in projection:
        fail("handoff_projection.md pasted the raw symbol graph.")

    if "C:\\Users\\" in projection:
        fail("handoff_projection.md leaked an absolute Windows user path.")

    if len(projection.splitlines()) > 260:
        fail("handoff_projection.md is too large for a sidecar projection.")

    outputs = pack_index.get("outputs", {})
    for key in ["handoff_projection_md", "handoff_projection_json"]:
        if key not in outputs:
            fail(f"pack_index outputs missing {key}")

    if payload.get("schema", {}).get("name") != "cbl.handoff_projection":
        fail("handoff_projection.json has wrong schema name.")

    if payload.get("counts", {}).get("evidence_graph_nodes", 0) <= 0:
        fail("handoff_projection.json did not capture evidence graph node count.")

    changed = run_cbl("pack", "--changed", "--issue", "phase 13 clean changed projection audit", "--budget", "24000", "--no-archive")
    if changed.returncode != 0:
        fail(f"changed cbl pack failed:\nSTDOUT:\n{changed.stdout}\nSTDERR:\n{changed.stderr}")

    changed_projection = (latest / "handoff_projection.md").read_text(encoding="utf-8")
    if "## Changed Scope" not in changed_projection:
        fail("changed projection missing changed scope section.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 13 handoff projection sidecar audit passed.")
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


def run_cbl(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "projection_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'projection-repo'\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")

    (package / "app.py").write_text(
        "\n".join(
            [
                "from demo.service import transform",
                "",
                "def main() -> int:",
                "    return transform(2)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (package / "service.py").write_text(
        "\n".join(
            [
                "def transform(value: int) -> int:",
                "    return value + 1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_app.py").write_text(
        "\n".join(
            [
                "from demo.app import main",
                "",
                "def test_main():",
                "    assert main() == 3",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_pack_writes_handoff_projection_sidecar_without_rewriting_legacy_handoff(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("pack", "--repo", str(repo), "--issue", "projection sidecar", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    latest = repo / ".codecontext" / "latest"
    handoff = latest / "ai_handoff.md"
    projection_md = latest / "handoff_projection.md"
    projection_json = latest / "handoff_projection.json"
    pack_index = latest / "pack_index.json"

    assert handoff.is_file()
    assert projection_md.is_file()
    assert projection_json.is_file()
    assert pack_index.is_file()

    legacy_text = handoff.read_text(encoding="utf-8")
    projection_text = projection_md.read_text(encoding="utf-8")

    assert "# CBL AI Handoff Pack" in legacy_text
    assert "# CBL Handoff Projection" in projection_text
    assert "The legacy `ai_handoff.md` is preserved unchanged." in projection_text
    assert "evidence_graph.json" in projection_text
    assert "cbl graph --symbol <symbol> --depth 2" in projection_text
    assert "# CBL Symbol Relationship Graph\n\nEvidence scope:" not in projection_text

    payload = json.loads(projection_json.read_text(encoding="utf-8"))
    assert payload["schema"]["name"] == "cbl.handoff_projection"
    assert payload["counts"]["evidence_graph_nodes"] > 0
    assert payload["counts"]["evidence_graph_edges"] > 0

    index = json.loads(pack_index.read_text(encoding="utf-8"))
    assert index["outputs"]["handoff_projection_md"] == ".codecontext/latest/handoff_projection.md"
    assert index["outputs"]["handoff_projection_json"] == ".codecontext/latest/handoff_projection.json"


def test_changed_pack_projection_reports_changed_scope(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, text=True, capture_output=True, check=False)

    result = run_cbl("pack", "--repo", str(repo), "--changed", "--issue", "clean changed projection", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    projection_text = (repo / ".codecontext" / "latest" / "handoff_projection.md").read_text(encoding="utf-8")
    assert "## Changed Scope" in projection_text
    assert "No Git changes detected for this changed-only pack." in projection_text

    payload = json.loads((repo / ".codecontext" / "latest" / "handoff_projection.json").read_text(encoding="utf-8"))
    assert payload["changed_scope"]["empty_changed_scope"] is True
'''


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative_path: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
    if path.suffix == ".py":
        modified.add(path)


def find_function_bounds(text: str, name: str) -> tuple[int, int]:
    match = re.search(rf"^def {re.escape(name)}\(", text, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not find function {name}().")

    start = match.start()
    next_match = re.search(r"^def [A-Za-z_][A-Za-z0-9_]*\(", text[match.end():], flags=re.MULTILINE)
    if not next_match:
        return start, len(text)
    return start, match.end() + next_match.start()


def patch_handoff(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "reports" / "handoff.py"
    text = path.read_text(encoding="utf-8")

    if "write_handoff_projection_reports(" in text:
        return

    start, end = find_function_bounds(text, "write_handoff_pack")
    function_text = text[start:end]

    if "_write_pack_index(" not in function_text:
        raise RuntimeError("Could not find _write_pack_index() call inside write_handoff_pack().")

    insert_relative = function_text.find("_write_pack_index(")
    line_start = function_text.rfind("\n", 0, insert_relative) + 1
    absolute_insert = start + line_start

    block = '''    from codebase_lens.reports.handoff_projection import write_handoff_projection_reports

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

'''

    text = text[:absolute_insert] + block + text[absolute_insert:]
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


def required_symbols_block(path: str, symbols: list[str]) -> str:
    lines = [
        "            {",
        f'                "path": "{path}",',
        '                "symbols": [',
    ]
    for symbol in symbols:
        lines.append(f'                    "{symbol}",')
    lines.extend(
        [
            "                ],",
            "            },",
        ]
    )
    return "\n".join(lines) + "\n"


def patch_contract(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    required_files = [
        "src/codebase_lens/reports/handoff_projection.py",
        "scripts/dev/audits/audit_phase13_handoff_projection_sidecar.py",
    ]
    missing = [item for item in required_files if f'"{item}"' not in text and f"'{item}'" not in text]
    if missing:
        block = "".join(f'            "{item}",\n' for item in missing)
        text = insert_before_list_close(text, "required_files", block)

    symbol_path = "src/codebase_lens/reports/handoff_projection.py"
    if f'"path": "{symbol_path}"' not in text and f"'path': '{symbol_path}'" not in text:
        text = insert_before_list_close(
            text,
            "required_symbols",
            required_symbols_block(
                symbol_path,
                [
                    "HandoffProjectionResult",
                    "write_handoff_projection_reports",
                ],
            ),
        )

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

    write_file("src/codebase_lens/reports/handoff_projection.py", HANDOFF_PROJECTION, modified)
    write_file("scripts/dev/audits/audit_phase13_handoff_projection_sidecar.py", AUDIT, modified)
    write_file("tests/test_handoff_projection_sidecar.py", TEST, modified)

    patch_handoff(modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 015A applied: handoff projection sidecar added without rewriting legacy ai_handoff.md.")
    print("The updater parsed every modified Python file before exiting.")
    print("Run the Phase 13 sidecar audit, prior audits, contract, pytest, and diff checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())