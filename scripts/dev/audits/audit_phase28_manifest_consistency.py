from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
SRC = ROOT / "src"


@dataclass(frozen=True)
class ManifestConsistencyIssue:
    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestConsistencyResult:
    ok: bool
    issues: tuple[ManifestConsistencyIssue, ...]
    counts: dict[str, int]
    fixture: dict[str, Any]


def _env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def _run_cbl(args: list[str], *, cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AssertionError(f"missing JSON artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"JSON artifact is not an object: {path}")
    return value


def _make_fixture_repo(base: Path) -> Path:
    repo = base / "manifest_consistency_repo"
    package = repo / "src" / "demo_pkg"

    _write(repo / ".gitignore", ".codecontext/\ndata/\noutputs/\n")
    _write(
        repo / "pyproject.toml",
        """
[project]
name = 'manifest-consistency-demo'
version = '0.0.0'
""",
    )
    _write(package / "__init__.py", "")
    _write(
        package / "core.py",
        """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().casefold()

def build_name(name: str) -> str:
    return normalize_name(name)
""",
    )
    _write(package / "large_notes.md", "LARGE FILE\n" + ("x" * 4096))
    _write(repo / "data" / "ignored_payload.txt", "ignored hard-excluded data file")
    _write(repo / "outputs" / "ignored_output.txt", "ignored hard-excluded output file")
    _write(repo / ".codecontext" / "previous" / "ignored_prior_output.txt", "prior output")

    if shutil.which("git"):
        init = _run_git(repo, "init")
        if init.returncode == 0:
            _run_git(repo, "config", "user.email", "fixture@example.invalid")
            _run_git(repo, "config", "user.name", "CBL Fixture")
            _run_git(repo, "add", ".")
            _run_git(repo, "commit", "-m", "initial")

    return repo


def _latest(repo: Path) -> Path:
    return repo / ".codecontext" / "latest"


def _manifest_file_universe(repo: Path) -> dict[str, Any]:
    manifest = _load_json(_latest(repo) / "manifest.json")
    file_universe = manifest.get("file_universe")
    if not isinstance(file_universe, dict):
        raise AssertionError("manifest file_universe is not an object")
    return file_universe


def _inventory_counts(repo: Path) -> dict[str, Any]:
    inventory = _load_json(_latest(repo) / "file_inventory.json")
    counts = inventory.get("counts")
    if not isinstance(counts, dict):
        raise AssertionError("file_inventory counts is not an object")
    return counts


def _required_manifest_keys() -> tuple[str, ...]:
    return (
        "tracked_included_count",
        "untracked_included_count",
        "ignored_count",
        "hard_excluded_ignored_count",
        "hard_excluded_count",
        "large_skipped_count",
        "binary_skipped_count",
        "decode_failed_count",
        "redacted_file_count",
        "unsupported_extension_count",
        "included_count",
        "omitted_files_count",
    )


def _assert_manifest_matches_inventory(*, repo: Path, command_name: str, issues: list[ManifestConsistencyIssue]) -> None:
    manifest_counts = _manifest_file_universe(repo)
    inventory_counts = _inventory_counts(repo)

    for key in _required_manifest_keys():
        if key not in manifest_counts:
            issues.append(
                ManifestConsistencyIssue(
                    severity="error",
                    code="manifest_missing_file_universe_key",
                    message=f"Manifest file_universe is missing {key!r} after {command_name}.",
                    details={"command": command_name, "key": key, "manifest_file_universe": manifest_counts},
                )
            )
            continue

        expected = int(inventory_counts.get(key, 0) or 0)
        actual = int(manifest_counts.get(key, 0) or 0)
        if actual != expected:
            issues.append(
                ManifestConsistencyIssue(
                    severity="error",
                    code="manifest_inventory_count_mismatch",
                    message=f"Manifest file_universe {key!r} does not match file_inventory after {command_name}.",
                    details={"command": command_name, "key": key, "expected": expected, "actual": actual},
                )
            )


def _run_and_check(
    *,
    repo: Path,
    runner: Path,
    command_name: str,
    args: list[str],
    issues: list[ManifestConsistencyIssue],
) -> dict[str, Any]:
    result = _run_cbl(args, cwd=runner)
    if result.returncode != 0:
        issues.append(
            ManifestConsistencyIssue(
                severity="error",
                code="cbl_command_failed",
                message=f"cbl {command_name} failed in manifest consistency audit.",
                details={
                    "command": args,
                    "returncode": result.returncode,
                    "stdout_tail": result.stdout[-1500:],
                    "stderr_tail": result.stderr[-1500:],
                },
            )
        )
        return {}

    _assert_manifest_matches_inventory(repo=repo, command_name=command_name, issues=issues)
    return _manifest_file_universe(repo)


def run_manifest_consistency_audit() -> ManifestConsistencyResult:
    issues: list[ManifestConsistencyIssue] = []

    with tempfile.TemporaryDirectory(prefix="cbl_manifest_consistency_") as temp_dir:
        workspace = Path(temp_dir)
        repo = _make_fixture_repo(workspace)
        runner = workspace / "runner"
        runner.mkdir(parents=True, exist_ok=True)

        first_snapshot_counts = _run_and_check(
            repo=repo,
            runner=runner,
            command_name="snapshot:first",
            args=["snapshot", "--repo", str(repo), "--budget", "12000", "--max-file-bytes", "256", "--no-archive"],
            issues=issues,
        )
        second_snapshot_counts = _run_and_check(
            repo=repo,
            runner=runner,
            command_name="snapshot:second",
            args=["snapshot", "--repo", str(repo), "--budget", "12000", "--max-file-bytes", "256", "--no-archive"],
            issues=issues,
        )
        pack_counts = _run_and_check(
            repo=repo,
            runner=runner,
            command_name="pack",
            args=["pack", "--repo", str(repo), "--issue", "manifest consistency audit", "--budget", "12000", "--max-file-bytes", "256", "--no-archive"],
            issues=issues,
        )
        graph_counts = _run_and_check(
            repo=repo,
            runner=runner,
            command_name="graph",
            args=["graph", "--repo", str(repo), "--symbol", "build_name", "--depth", "1", "--limit", "40", "--max-file-bytes", "256", "--no-archive"],
            issues=issues,
        )

        if first_snapshot_counts and second_snapshot_counts:
            first_ignored = int(first_snapshot_counts.get("ignored_count", 0) or 0)
            second_ignored = int(second_snapshot_counts.get("ignored_count", 0) or 0)
            if first_ignored != second_ignored:
                issues.append(
                    ManifestConsistencyIssue(
                        severity="error",
                        code="ignored_count_not_stable_across_repeated_outputs",
                        message="ignored_count changed after CBL generated additional hard-excluded .codecontext outputs.",
                        details={"first": first_ignored, "second": second_ignored},
                    )
                )

            hard_first = int(first_snapshot_counts.get("hard_excluded_ignored_count", 0) or 0)
            hard_second = int(second_snapshot_counts.get("hard_excluded_ignored_count", 0) or 0)
            if hard_first <= 0 or hard_second < hard_first:
                issues.append(
                    ManifestConsistencyIssue(
                        severity="error",
                        code="hard_excluded_ignored_count_missing_or_unstable",
                        message="hard_excluded_ignored_count did not capture ignored hard-excluded files.",
                        details={"first": hard_first, "second": hard_second},
                    )
                )

        fixture = {
            "repo_name": repo.name,
            "first_snapshot_file_universe": first_snapshot_counts,
            "second_snapshot_file_universe": second_snapshot_counts,
            "pack_file_universe": pack_counts,
            "graph_file_universe": graph_counts,
        }

    ok = not any(issue.severity == "error" for issue in issues)
    return ManifestConsistencyResult(
        ok=ok,
        issues=tuple(issues),
        counts={
            "issues": len(issues),
            "errors": sum(1 for issue in issues if issue.severity == "error"),
            "warnings": sum(1 for issue in issues if issue.severity == "warning"),
        },
        fixture=fixture,
    )


def _write_report(result: ManifestConsistencyResult) -> Path:
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    payload = {
        "schema": {
            "name": "cbl.manifest_consistency_audit",
            "version": 1,
        },
        "ok": result.ok,
        "counts": dict(result.counts),
        "issues": [asdict(issue) for issue in result.issues],
        "fixture": result.fixture,
    }
    stable, _latest = write_audit_report_pair(ROOT, "manifest_consistency", payload)
    return stable


def main() -> int:
    result = run_manifest_consistency_audit()
    report = _write_report(result)

    if not result.ok:
        print(f"FAIL: Phase 28 manifest consistency audit failed. Report: {report}")
        for issue in result.issues:
            print(f"- {issue.severity}: {issue.code}: {issue.message}")
        return 1

    print("PASS: Phase 28 manifest consistency audit passed.")
    print(f"Stable audit report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
