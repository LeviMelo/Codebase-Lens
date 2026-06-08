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
