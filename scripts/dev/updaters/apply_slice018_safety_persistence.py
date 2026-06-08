from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

AUDIT_ARTIFACTS = r'''
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _safe_audit_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        raise ValueError("Audit artifact name cannot be empty.")
    if not cleaned.endswith(".json"):
        cleaned += ".json"
    return cleaned


def stable_audit_dir(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / ".codecontext" / "audits"


def latest_dir(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / ".codecontext" / "latest"


def write_stable_audit_report(repo_root: str | Path, name: str, payload: dict[str, Any]) -> Path:
    destination = stable_audit_dir(repo_root) / _safe_audit_name(name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def write_latest_audit_report(repo_root: str | Path, name: str, payload: dict[str, Any]) -> Path:
    destination = latest_dir(repo_root) / _safe_audit_name(name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def write_audit_report_pair(repo_root: str | Path, name: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    stable = write_stable_audit_report(repo_root, name, payload)
    latest = write_latest_audit_report(repo_root, name, payload)
    return stable, latest
'''

RELEASE_SAFETY = r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReleaseSafetyIssue:
    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReleaseSafetyAuditResult:
    ok: bool
    duration_seconds: float
    issues: tuple[ReleaseSafetyIssue, ...]
    counts: dict[str, int]
    external_repo: dict[str, Any]


RAW_SECRET_MARKERS = (
    "sk-live-fixture-secret",
    "fixture-password-123",
    "fixture-token-abc",
    "DATABASE_URL=postgres://fixture-secret",
)

AI_FACING_ARTIFACTS = (
    "ai_handoff.md",
    "handoff_projection.md",
    "handoff_projection.json",
    "graph_summary.md",
    "symbol_graph.md",
    "pack_index.json",
    "snapshot_index.json",
)

PACK_REQUIRED_ARTIFACTS = (
    "manifest.json",
    "handoff_projection.json",
    "handoff_projection.md",
    "ai_handoff.md",
    "evidence_graph.json",
    "graph_summary.md",
    "symbol_graph.json",
    "symbol_graph.md",
    "file_inventory.json",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _src_root() -> Path:
    return _repo_root() / "src"


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    src = str(_src_root())
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return env


def _run_cbl(args: list[str], *, cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        env=_python_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _create_hostile_repo(base: Path) -> Path:
    repo = base / "hostile_safety_repo"
    package = repo / "src" / "safety_pkg"

    _write(
        repo / "pyproject.toml",
        """
[project]
name = 'safety-pkg'
version = '0.0.0'
""",
    )

    _write(
        package / "__init__.py",
        """
raise RuntimeError('CBL imported a hostile fixture package instead of parsing it statically')
""",
    )

    _write(
        package / "core.py",
        """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().lower()

def build_name(name: str) -> str:
    return normalize_name(name)
""",
    )

    _write(
        package / "config.py",
        """
from __future__ import annotations

API_KEY = "sk-live-fixture-secret"
TOKEN = "fixture-token-abc"
PASSWORD = "fixture-password-123"

def public_config() -> dict[str, str]:
    return {"mode": "test"}
""",
    )

    _write(
        repo / ".env",
        """
OPENAI_API_KEY=sk-live-fixture-secret
PASSWORD=fixture-password-123
DATABASE_URL=postgres://fixture-secret
""",
    )

    _write(
        repo / ".codecontext" / "latest" / "poison.py",
        """
def poison_should_not_be_scanned():
    return "poison"
""",
    )

    _write(
        repo / ".codecontext" / "latest" / "poison.md",
        """
This previous-output file must not be recursively scanned.
""",
    )

    _write(
        repo / "data" / "raw" / "poison.py",
        """
def data_poison_should_not_be_scanned():
    return "raw-data"
""",
    )

    _write(
        repo / "outputs" / "poison.py",
        """
def output_poison_should_not_be_scanned():
    return "output"
""",
    )

    _write(
        repo / "node_modules" / "poison.py",
        """
def node_modules_poison_should_not_be_scanned():
    return "node_modules"
""",
    )

    _write(
        package / "large_notes.md",
        "LARGE FILE WITH SECRET sk-live-fixture-secret\n" + ("x" * 120_000),
    )

    _write_bytes(
        package / "binary_payload.bin",
        b"\x00\x01\x02sk-live-fixture-secret\x03\x04",
    )

    return repo


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _graph_node_paths(evidence_graph_path: Path) -> list[str]:
    payload = _load_json(evidence_graph_path)
    nodes = payload.get("nodes", [])
    paths: list[str] = []

    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("path"), str):
                paths.append(node["path"])

    return paths


def _inventory_paths(file_inventory_path: Path) -> list[str]:
    payload = _load_json(file_inventory_path)
    values: list[str] = []

    def collect_from_items(items: Any) -> None:
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    values.append(item["path"])

    collect_from_items(payload.get("included_files"))
    collect_from_items(payload.get("omitted_files"))
    collect_from_items(payload.get("files"))
    return values


def _read_ai_facing_blob(latest: Path) -> str:
    chunks: list[str] = []
    for name in AI_FACING_ARTIFACTS:
        path = latest / name
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _contains_forbidden_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    forbidden_prefixes = (
        ".codecontext/",
        "data/",
        "raw/",
        "processed/",
        "outputs/",
        "output/",
        "node_modules/",
    )
    forbidden_names = {
        ".env",
        "binary_payload.bin",
        "large_notes.md",
    }

    if normalized in forbidden_names:
        return True

    if any(normalized.startswith(prefix) for prefix in forbidden_prefixes):
        return True

    if "/.codecontext/" in normalized:
        return True

    return False


def _validate_pack_outputs(repo: Path, workspace: Path) -> tuple[dict[str, Any], list[ReleaseSafetyIssue]]:
    latest = repo / ".codecontext" / "latest"
    issues: list[ReleaseSafetyIssue] = []

    missing = [name for name in PACK_REQUIRED_ARTIFACTS if not (latest / name).is_file()]
    if missing:
        issues.append(
            ReleaseSafetyIssue(
                severity="error",
                code="missing_pack_artifacts",
                message="Safety pack missed mandatory handoff artifacts.",
                details={"missing": missing},
            )
        )

    projection = _load_json(latest / "handoff_projection.json")
    prefixes = projection.get("project_profile", {}).get("source_prefixes", [])
    if "src/safety_pkg/" not in prefixes:
        issues.append(
            ReleaseSafetyIssue(
                severity="error",
                code="source_prefix_not_inferred",
                message="Safety fixture package source prefix was not inferred.",
                details={"source_prefixes": prefixes},
            )
        )

    graph_paths = _graph_node_paths(latest / "evidence_graph.json")
    scanned_forbidden_paths = [path for path in graph_paths if _contains_forbidden_path(path)]
    if scanned_forbidden_paths:
        issues.append(
            ReleaseSafetyIssue(
                severity="error",
                code="forbidden_paths_scanned_in_graph",
                message="Hard-excluded paths appeared in the evidence graph.",
                details={"paths": scanned_forbidden_paths[:30]},
            )
        )

    inventory_paths = _inventory_paths(latest / "file_inventory.json")
    included_forbidden_paths = [
        path
        for path in inventory_paths
        if path in graph_paths and _contains_forbidden_path(path)
    ]
    if included_forbidden_paths:
        issues.append(
            ReleaseSafetyIssue(
                severity="error",
                code="forbidden_paths_included",
                message="Hard-excluded paths were included in analyzable inventory.",
                details={"paths": included_forbidden_paths[:30]},
            )
        )

    blob = _read_ai_facing_blob(latest)
    leaked_markers = [marker for marker in RAW_SECRET_MARKERS if marker in blob]
    if leaked_markers:
        issues.append(
            ReleaseSafetyIssue(
                severity="error",
                code="raw_secret_leaked",
                message="Raw fixture secret marker leaked into AI-facing artifacts.",
                details={"markers": leaked_markers},
            )
        )

    poison_markers = [
        marker
        for marker in (
            "poison_should_not_be_scanned",
            "data_poison_should_not_be_scanned",
            "output_poison_should_not_be_scanned",
            "node_modules_poison_should_not_be_scanned",
        )
        if marker in blob
    ]
    if poison_markers:
        issues.append(
            ReleaseSafetyIssue(
                severity="error",
                code="poison_output_leaked",
                message="Hard-excluded poison code leaked into AI-facing artifacts.",
                details={"markers": poison_markers},
            )
        )

    normalized_workspace = str(workspace.resolve()).replace("\\", "/")
    normalized_blob = blob.replace("\\", "/")
    if normalized_workspace in normalized_blob:
        issues.append(
            ReleaseSafetyIssue(
                severity="error",
                code="absolute_workspace_path_leaked",
                message="AI-facing artifacts leaked an absolute temp workspace path.",
                details={"workspace": normalized_workspace},
            )
        )

    counts = projection.get("counts", {}) if isinstance(projection.get("counts"), dict) else {}
    if int(counts.get("symbols") or 0) < 2:
        issues.append(
            ReleaseSafetyIssue(
                severity="error",
                code="safety_fixture_not_analyzed",
                message="Safety fixture did not produce enough Python symbol evidence.",
                details={"counts": counts},
            )
        )

    return {
        "latest_dir": str(latest),
        "source_prefixes": prefixes,
        "graph_node_paths": graph_paths,
        "counts": counts,
        "missing_artifacts": missing,
    }, issues


def _validate_unsafe_path_rejection(repo: Path, workspace: Path, runner: Path) -> tuple[dict[str, Any], list[ReleaseSafetyIssue]]:
    outside = workspace / "outside_secret.txt"
    _write(outside, "OUTSIDE_SECRET=fixture-password-123")

    result = _run_cbl(
        [
            "file",
            "--repo",
            str(repo),
            "../outside_secret.txt",
            "--no-archive",
        ],
        cwd=runner,
        timeout=30,
    )

    details = {
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-1000:],
        "stderr_tail": result.stderr[-1000:],
    }

    if result.returncode == 0:
        return details, [
            ReleaseSafetyIssue(
                severity="error",
                code="unsafe_path_not_rejected",
                message="cbl file accepted a path escaping the repository root.",
                details=details,
            )
        ]

    return details, []


def run_release_safety_audit() -> ReleaseSafetyAuditResult:
    started = time.perf_counter()
    issues: list[ReleaseSafetyIssue] = []
    external_repo_report: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="cbl_release_safety_") as temp_dir:
        workspace = Path(temp_dir)
        repo = _create_hostile_repo(workspace)
        runner = workspace / "runner"
        runner.mkdir(parents=True, exist_ok=True)

        pack_result = _run_cbl(
            [
                "pack",
                "--repo",
                str(repo),
                "--issue",
                "release safety audit hostile fixture",
                "--budget",
                "16000",
                "--max-file-bytes",
                "4096",
                "--no-archive",
            ],
            cwd=runner,
            timeout=60,
        )

        external_repo_report = {
            "target_repo": str(repo),
            "runner_cwd": str(runner),
            "pack_returncode": pack_result.returncode,
            "pack_stdout_tail": pack_result.stdout[-1200:],
            "pack_stderr_tail": pack_result.stderr[-1200:],
        }

        if pack_result.returncode != 0:
            issues.append(
                ReleaseSafetyIssue(
                    severity="error",
                    code="hostile_fixture_pack_failed",
                    message="cbl pack failed for hostile safety fixture.",
                    details=external_repo_report,
                )
            )
        else:
            output_report, output_issues = _validate_pack_outputs(repo, workspace)
            external_repo_report.update(output_report)
            issues.extend(output_issues)

        unsafe_report, unsafe_issues = _validate_unsafe_path_rejection(repo, workspace, runner)
        external_repo_report["unsafe_path_check"] = unsafe_report
        issues.extend(unsafe_issues)

    duration = round(time.perf_counter() - started, 3)
    ok = not any(issue.severity == "error" for issue in issues)

    return ReleaseSafetyAuditResult(
        ok=ok,
        duration_seconds=duration,
        issues=tuple(issues),
        counts={
            "issues": len(issues),
            "errors": sum(1 for issue in issues if issue.severity == "error"),
            "warnings": sum(1 for issue in issues if issue.severity == "warning"),
        },
        external_repo=external_repo_report,
    )


def release_safety_audit_payload(result: ReleaseSafetyAuditResult) -> dict[str, Any]:
    return {
        "schema": {
            "name": "cbl.release_safety_audit",
            "version": 1,
        },
        "ok": result.ok,
        "duration_seconds": result.duration_seconds,
        "counts": dict(result.counts),
        "issues": [asdict(issue) for issue in result.issues],
        "external_repo": result.external_repo,
    }
'''

PHASE22_AUDIT = r'''
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def main() -> int:
    sys.path.insert(0, str(SRC))

    for relative in [
        "src/codebase_lens/core/audit_artifacts.py",
        "src/codebase_lens/contracts/release_safety.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.release_safety import (
        release_safety_audit_payload,
        run_release_safety_audit,
    )
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    result = run_release_safety_audit()
    payload = release_safety_audit_payload(result)
    stable_path, latest_path = write_audit_report_pair(ROOT, "release_safety_audit", payload)

    if not stable_path.is_file():
        fail(f"Stable safety audit report was not written: {stable_path}")
    if not latest_path.is_file():
        fail(f"Latest safety audit report was not written: {latest_path}")

    loaded = json.loads(stable_path.read_text(encoding="utf-8"))
    if loaded.get("schema", {}).get("name") != "cbl.release_safety_audit":
        fail("Release safety audit report has wrong schema name.")

    if not result.ok:
        formatted = json.dumps(payload.get("issues", []), indent=2, sort_keys=True)
        fail(f"Release safety audit failed:\n{formatted}")

    print("PASS: Phase 22 release safety and audit persistence passed.")
    print(f"Stable audit report: {stable_path}")
    print(f"Latest audit report: {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PHASE21_AUDIT = r'''
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def main() -> int:
    sys.path.insert(0, str(SRC))

    for relative in [
        "src/codebase_lens/contracts/fixture_matrix.py",
        "src/codebase_lens/contracts/command_surface.py",
        "src/codebase_lens/core/audit_artifacts.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.fixture_matrix import (
        release_fixture_matrix_payload,
        run_release_fixture_matrix,
    )
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    result = run_release_fixture_matrix(include_git_fixture=True)
    payload = release_fixture_matrix_payload(result)
    stable_path, latest_path = write_audit_report_pair(ROOT, "fixture_matrix_audit", payload)

    if payload.get("schema", {}).get("name") != "cbl.release_fixture_matrix":
        fail("Fixture matrix report has wrong schema name.")

    required_cases = {
        "basic_package",
        "argparse_cli_package",
        "route_static_package",
        "safety_redaction_package",
        "codecontext_recursion_package",
    }
    observed_cases = {case.get("name") for case in payload.get("cases", [])}
    missing_cases = sorted(required_cases - observed_cases)
    if missing_cases:
        fail(f"Fixture matrix did not run required cases: {missing_cases}")

    if not result.ok:
        formatted = json.dumps(payload.get("issues", []), indent=2, sort_keys=True)
        fail(f"Release fixture matrix failed:\n{formatted}")

    if payload.get("counts", {}).get("passed", 0) < 5:
        fail(f"Too few fixture cases passed: {payload.get('counts')}")

    if not stable_path.is_file() or not latest_path.is_file():
        fail("Fixture matrix audit report was not written to stable and latest locations.")

    print("PASS: Phase 21 release fixture matrix audit passed.")
    print(f"Stable audit report: {stable_path}")
    print(f"Latest audit report: {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PHASE20_AUDIT = r'''
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def main() -> int:
    sys.path.insert(0, str(SRC))

    for relative in [
        "src/codebase_lens/cli.py",
        "src/codebase_lens/contracts/command_surface.py",
        "src/codebase_lens/core/audit_artifacts.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.command_surface import (
        audit_command_surface,
        command_surface_result_payload,
    )
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    result = audit_command_surface(include_help=True, include_external_pack=True)
    payload = command_surface_result_payload(result)
    stable_path, latest_path = write_audit_report_pair(ROOT, "command_surface_audit", payload)

    if not stable_path.is_file() or not latest_path.is_file():
        fail("command_surface_audit.json was not written to stable and latest locations.")

    if payload.get("schema", {}).get("name") != "cbl.command_surface_audit":
        fail("command surface audit report has wrong schema name.")

    if not result.ok:
        formatted = json.dumps(payload.get("issues", []), indent=2, sort_keys=True)
        fail(f"Public command stability gate failed:\n{formatted}")

    public_commands = set(payload.get("public_commands", []))
    parser_subcommands = set(payload.get("parser_subcommands", []))
    if public_commands != parser_subcommands:
        fail(f"Public command mismatch: public={sorted(public_commands)} parser={sorted(parser_subcommands)}")

    if len(public_commands) < 10:
        fail(f"Unexpectedly small public command surface: {sorted(public_commands)}")

    external = payload.get("external_repo", {})
    if not external.get("manifest_exists"):
        fail("External --repo pack did not write manifest.json.")
    if not external.get("projection_exists"):
        fail("External --repo pack did not write handoff_projection.json.")
    if external.get("missing_core_artifacts"):
        fail(f"External --repo pack missed core artifacts: {external['missing_core_artifacts']}")
    if external.get("scanned_codecontext_paths"):
        fail(f"External --repo pack recursively scanned .codecontext: {external['scanned_codecontext_paths']}")

    print("PASS: Phase 20 public command stability audit passed.")
    print(f"Stable audit report: {stable_path}")
    print(f"Latest audit report: {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST = r'''
from __future__ import annotations

import json
from pathlib import Path

from codebase_lens.contracts.release_safety import (
    release_safety_audit_payload,
    run_release_safety_audit,
)
from codebase_lens.core.audit_artifacts import write_audit_report_pair


def test_release_safety_audit_passes_hostile_fixture() -> None:
    result = run_release_safety_audit()
    payload = release_safety_audit_payload(result)

    assert result.ok, json.dumps(payload["issues"], indent=2, sort_keys=True)
    assert payload["schema"]["name"] == "cbl.release_safety_audit"
    assert payload["counts"]["errors"] == 0

    external = payload["external_repo"]
    assert "src/safety_pkg/" in external["source_prefixes"]
    assert external["pack_returncode"] == 0
    assert external["unsafe_path_check"]["returncode"] != 0


def test_stable_audit_artifact_writer_preserves_reports(tmp_path: Path) -> None:
    payload = {
        "schema": {"name": "test.audit", "version": 1},
        "ok": True,
    }

    stable_path, latest_path = write_audit_report_pair(tmp_path, "release safety audit", payload)

    assert stable_path == tmp_path / ".codecontext" / "audits" / "release_safety_audit.json"
    assert latest_path == tmp_path / ".codecontext" / "latest" / "release_safety_audit.json"
    assert stable_path.is_file()
    assert latest_path.is_file()

    stable_payload = json.loads(stable_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))

    assert stable_payload == payload
    assert latest_payload == payload


def test_release_safety_contract_module_does_not_import_cli_layer() -> None:
    import inspect
    import codebase_lens.contracts.release_safety as release_safety

    source = inspect.getsource(release_safety)

    assert "from codebase_lens import cli" not in source
    assert "import codebase_lens.cli" not in source
    assert "codebase_lens.cli" not in source
'''

def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


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

    additions = [
        "src/codebase_lens/core/audit_artifacts.py",
        "src/codebase_lens/contracts/release_safety.py",
        "scripts/dev/audits/audit_phase22_release_safety.py",
    ]

    for required_file in additions:
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

    write_file("src/codebase_lens/core/audit_artifacts.py", AUDIT_ARTIFACTS, modified)
    write_file("src/codebase_lens/contracts/release_safety.py", RELEASE_SAFETY, modified)
    write_file("scripts/dev/audits/audit_phase22_release_safety.py", PHASE22_AUDIT, modified)
    write_file("scripts/dev/audits/audit_phase21_release_fixture_matrix.py", PHASE21_AUDIT, modified)
    write_file("scripts/dev/audits/audit_phase20_public_command_stability.py", PHASE20_AUDIT, modified)
    write_file("tests/test_release_safety.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 018 applied: release safety audit and stable audit persistence added.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
