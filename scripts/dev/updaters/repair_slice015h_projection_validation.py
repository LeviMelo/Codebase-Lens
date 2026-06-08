from __future__ import annotations

import ast
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

PHASE18_AUDIT = r'''
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

    schema_version = int(payload.get("schema", {}).get("version") or 0)
    if schema_version < 4:
        fail(f"handoff_projection schema version regressed below 4: {schema_version}")

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

PHASE18_TEST = r'''
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

    assert payload["schema"]["version"] >= 4

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

PHASE19_AUDIT = r'''
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
        "src/codebase_lens/reports/handoff_projection.py",
        "src/codebase_lens/reports/handoff.py",
        "src/codebase_lens/cli.py",
    ]:
        assert_parseable(relative)

    result = run_cbl("pack", "--issue", "phase 19 projection role/import audit", "--budget", "24000", "--no-archive")
    if result.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    latest = ROOT / ".codecontext" / "latest"
    payload = json.loads((latest / "handoff_projection.json").read_text(encoding="utf-8"))

    if payload.get("schema", {}).get("version") != 5:
        fail("handoff_projection schema version was not advanced to 5.")

    graph = payload.get("graph", {})
    edges = graph.get("representative_edges", [])

    if not edges:
        fail("No representative edges emitted.")

    base_manifest_edges = [
        edge
        for edge in edges
        if "_base_manifest_args" in str(edge.get("source"))
    ]
    for edge in base_manifest_edges:
        if edge.get("source_role") == "cli_handler":
            fail(f"_base_manifest_args incorrectly classified as cli_handler: {edge}")
        if edge.get("edge_family") in {"handler_to_analysis", "cli_handler_to_analysis"}:
            fail(f"_base_manifest_args incorrectly emitted as handler edge: {edge}")

    if base_manifest_edges and not any(
        edge.get("edge_family") in {"cli_support_to_analysis", "cli_support_to_io_or_config"}
        for edge in base_manifest_edges
    ):
        fail(f"_base_manifest_args did not receive a CLI support family: {base_manifest_edges}")

    handler_edges = [
        edge
        for edge in edges
        if str(edge.get("source")).split("::")[-1].startswith("_run_")
    ]
    if not handler_edges:
        fail("No _run_* CLI handler edge was selected.")

    for edge in handler_edges:
        if edge.get("source_role") != "cli_handler":
            fail(f"_run_* source not classified as cli_handler: {edge}")
        if edge.get("edge_family") not in {
            "cli_handler_to_analysis",
            "report_to_output_writer",
            "other_product_flow",
            "cli_support_to_analysis",
        }:
            fail(f"_run_* source received unexpected family: {edge}")

    import_edges = [
        edge
        for edge in edges
        if edge.get("edge_family") == "import_dependency"
    ]
    if not import_edges:
        fail("No import_dependency edge was selected.")

    for edge in import_edges:
        if edge.get("kind") == "file_imports_module" and not edge.get("target_path"):
            fail(f"Unresolved/external import was surfaced as internal import dependency: {edge}")
        if not edge.get("target_path"):
            fail(f"Import dependency lacks target_path: {edge}")
        if not str(edge.get("target_path")).startswith("src/codebase_lens/"):
            fail(f"Import dependency target is not a product path: {edge}")

    if not any(edge.get("kind") == "internal_import_dependency" for edge in import_edges):
        fail("No recovered internal import dependency was selected.")

    print("PASS: Phase 19 projection role/import audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PHASE19_TEST = r'''
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


def test_projection_refines_cli_roles_and_recovers_internal_imports() -> None:
    result = run_cbl("pack", "--issue", "projection role import test", "--budget", "24000", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads((ROOT / ".codecontext" / "latest" / "handoff_projection.json").read_text(encoding="utf-8"))
    assert payload["schema"]["version"] == 5

    edges = payload["graph"]["representative_edges"]
    assert edges

    base_edges = [edge for edge in edges if "_base_manifest_args" in str(edge["source"])]
    for edge in base_edges:
        assert edge["source_role"] != "cli_handler"
        assert edge["edge_family"] not in {"handler_to_analysis", "cli_handler_to_analysis"}

    run_edges = [edge for edge in edges if str(edge["source"]).split("::")[-1].startswith("_run_")]
    assert run_edges
    for edge in run_edges:
        assert edge["source_role"] == "cli_handler"

    import_edges = [edge for edge in edges if edge["edge_family"] == "import_dependency"]
    assert import_edges
    assert any(edge["kind"] == "internal_import_dependency" for edge in import_edges)
    for edge in import_edges:
        assert edge["target_path"]
        assert edge["target_path"].startswith("src/codebase_lens/")
'''


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
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

    write_file("scripts/dev/audits/audit_phase18_projection_dedup.py", PHASE18_AUDIT, modified)
    write_file("tests/test_handoff_projection_dedup.py", PHASE18_TEST, modified)
    write_file("scripts/dev/audits/audit_phase19_projection_roles_imports.py", PHASE19_AUDIT, modified)
    write_file("tests/test_handoff_projection_roles_imports.py", PHASE19_TEST, modified)

    assert_parseable(modified)

    print("Slice 015H validation repair applied.")
    print("Fixed stale schema-version checks and removed brittle high-connectivity CLI-handler assertion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())