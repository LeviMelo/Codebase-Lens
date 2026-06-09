from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

AUDIT = r'''
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
'''

TEST = r'''
from __future__ import annotations

import json
import os
import shutil
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


def run_cbl(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
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

    write(repo / ".gitignore", ".codecontext/\ndata/\noutputs/\n")
    write(repo / "pyproject.toml", "[project]\nname = 'demo-pkg'\nversion = '0.0.0'\n")
    write(package / "__init__.py", "")
    write(
        package / "core.py",
        """
from __future__ import annotations

def normalize_name(name: str) -> str:
    return name.strip().casefold()

def build_name(name: str) -> str:
    return normalize_name(name)
""",
    )
    write(package / "large_notes.md", "LARGE\n" + ("x" * 4096))
    write(repo / "data" / "ignored_payload.txt", "ignored data")
    write(repo / "outputs" / "ignored_output.txt", "ignored output")
    write(repo / ".codecontext" / "previous" / "ignored_prior_output.txt", "previous output")

    if shutil.which("git"):
        if run_git(repo, "init").returncode == 0:
            run_git(repo, "config", "user.email", "fixture@example.invalid")
            run_git(repo, "config", "user.name", "CBL Fixture")
            run_git(repo, "add", ".")
            run_git(repo, "commit", "-m", "initial")

    return repo


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_manifest_matches_inventory(repo: Path) -> dict:
    latest = repo / ".codecontext" / "latest"
    manifest = load_json(latest / "manifest.json")
    inventory = load_json(latest / "file_inventory.json")
    manifest_counts = manifest["file_universe"]
    inventory_counts = inventory["counts"]

    for key in [
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
    ]:
        assert key in manifest_counts
        assert int(manifest_counts.get(key, 0) or 0) == int(inventory_counts.get(key, 0) or 0)

    return manifest_counts


def test_snapshot_pack_and_graph_manifest_file_universe_matches_file_inventory(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    runner = tmp_path / "runner"
    runner.mkdir()

    snapshot = run_cbl("snapshot", "--repo", str(repo), "--budget", "12000", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert snapshot.returncode == 0, snapshot.stdout + snapshot.stderr
    first_counts = assert_manifest_matches_inventory(repo)

    pack = run_cbl("pack", "--repo", str(repo), "--issue", "manifest consistency test", "--budget", "12000", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert pack.returncode == 0, pack.stdout + pack.stderr
    pack_counts = assert_manifest_matches_inventory(repo)

    graph = run_cbl("graph", "--repo", str(repo), "--symbol", "build_name", "--depth", "1", "--limit", "40", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert graph.returncode == 0, graph.stdout + graph.stderr
    graph_counts = assert_manifest_matches_inventory(repo)

    assert first_counts["included_count"] == pack_counts["included_count"] == graph_counts["included_count"]
    assert first_counts["large_skipped_count"] >= 1


def test_hard_excluded_ignored_files_do_not_make_ignored_count_drift(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    runner = tmp_path / "runner"
    runner.mkdir()

    first = run_cbl("snapshot", "--repo", str(repo), "--budget", "12000", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert first.returncode == 0, first.stdout + first.stderr
    first_counts = assert_manifest_matches_inventory(repo)

    second = run_cbl("snapshot", "--repo", str(repo), "--budget", "12000", "--max-file-bytes", "256", "--no-archive", cwd=runner)
    assert second.returncode == 0, second.stdout + second.stderr
    second_counts = assert_manifest_matches_inventory(repo)

    assert first_counts["ignored_count"] == second_counts["ignored_count"]
    assert first_counts["hard_excluded_ignored_count"] >= 1
    assert second_counts["hard_excluded_ignored_count"] >= first_counts["hard_excluded_ignored_count"]


def test_phase28_manifest_consistency_audit_passes() -> None:
    runner = ROOT / ".codecontext" / "pytest_runner_manifest_consistency"
    runner.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dev" / "audits" / "audit_phase28_manifest_consistency.py")],
        cwd=runner,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Phase 28 manifest consistency audit passed." in result.stdout
'''


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
    if path.suffix == ".py":
        modified.add(path)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not find patch target: {label}")
    return text.replace(old, new, 1)


def patch_universe(modified: set[Path]) -> None:
    relative = "src/codebase_lens/scanners/universe.py"
    text = read(relative)

    if "def _split_ignored_counts(" not in text:
        helper = '''

def _split_ignored_counts(ignored_paths: tuple[str, ...]) -> tuple[int, int]:
    hard_excluded = 0
    ordinary = 0

    for raw_path in ignored_paths:
        relative = raw_path.replace("\\\\", "/").strip("/")
        if not relative:
            continue
        if is_hard_excluded_relative(relative):
            hard_excluded += 1
        else:
            ordinary += 1

    return ordinary, hard_excluded
'''
        text = replace_once(text, "def _empty_counts() -> dict[str, int]:\n", normalize(helper) + "\ndef _empty_counts() -> dict[str, int]:\n", "insert _split_ignored_counts")

    if '"hard_excluded_ignored_count": self.counts.get("hard_excluded_ignored_count", 0),' not in text:
        text = replace_once(
            text,
            '            "ignored_count": self.counts.get("ignored_count", 0),\n',
            '            "ignored_count": self.counts.get("ignored_count", 0),\n'
            '            "hard_excluded_ignored_count": self.counts.get("hard_excluded_ignored_count", 0),\n',
            "manifest_counts hard_excluded_ignored_count",
        )

    if '"omitted_files_count": self.counts.get("omitted_files_count", 0),' not in text:
        text = replace_once(
            text,
            '            "included_count": self.counts.get("included_count", 0),\n',
            '            "included_count": self.counts.get("included_count", 0),\n'
            '            "omitted_files_count": self.counts.get("omitted_files_count", 0),\n',
            "manifest_counts omitted_files_count",
        )

    if '"hard_excluded_ignored_count": 0,' not in text:
        text = replace_once(
            text,
            '        "ignored_count": 0,\n',
            '        "ignored_count": 0,\n'
            '        "hard_excluded_ignored_count": 0,\n',
            "empty_counts hard_excluded_ignored_count",
        )

    if '"omitted_files_count": 0,' not in text:
        text = replace_once(
            text,
            '        "included_count": 0,\n',
            '        "included_count": 0,\n'
            '        "omitted_files_count": 0,\n',
            "empty_counts omitted_files_count",
        )

    old_counts = '''    counts = _empty_counts()
    counts["ignored_count"] = len(git_sets.ignored)

    if git_sets.is_repo:
'''
    new_counts = '''    counts = _empty_counts()
    ignored_count, hard_excluded_ignored_count = _split_ignored_counts(git_sets.ignored)
    counts["ignored_count"] = ignored_count
    counts["hard_excluded_ignored_count"] = hard_excluded_ignored_count

    if git_sets.is_repo:
'''
    if old_counts in text:
        text = text.replace(old_counts, new_counts, 1)
    elif "ignored_count, hard_excluded_ignored_count = _split_ignored_counts(git_sets.ignored)" not in text:
        raise RuntimeError("Could not patch ignored count split in universe.py")

    old_return_counts = '''    counts["included_count"] = len(included)
    counts["redacted_occurrences_count"] = redacted_occurrences_count

    return FileUniverseResult(
'''
    new_return_counts = '''    counts["included_count"] = len(included)
    counts["omitted_files_count"] = len(omitted)
    counts["redacted_occurrences_count"] = redacted_occurrences_count

    return FileUniverseResult(
'''
    if old_return_counts in text:
        text = text.replace(old_return_counts, new_return_counts, 1)
    elif 'counts["omitted_files_count"] = len(omitted)' not in text:
        raise RuntimeError("Could not patch omitted_files_count assignment in universe.py")

    (ROOT / relative).write_text(text, encoding="utf-8", newline="\n")
    modified.add(ROOT / relative)


def patch_manifest(modified: set[Path]) -> None:
    relative = "src/codebase_lens/reports/manifest.py"
    text = read(relative)

    if '"hard_excluded_ignored_count": 0,' not in text:
        text = replace_once(text, '            "ignored_count": 0,\n', '            "ignored_count": 0,\n            "hard_excluded_ignored_count": 0,\n', "manifest default hard_excluded_ignored_count")
    if '"unsupported_extension_count": 0,' not in text:
        text = replace_once(text, '            "redacted_file_count": 0,\n', '            "redacted_file_count": 0,\n            "unsupported_extension_count": 0,\n', "manifest default unsupported_extension_count")
    if '"omitted_files_count": 0,' not in text:
        text = replace_once(text, '            "included_count": 0,\n', '            "included_count": 0,\n            "omitted_files_count": 0,\n', "manifest default omitted_files_count")

    (ROOT / relative).write_text(text, encoding="utf-8", newline="\n")
    modified.add(ROOT / relative)


def patch_snapshot(modified: set[Path]) -> None:
    relative = "src/codebase_lens/reports/snapshot.py"
    text = read(relative)

    if "    file_universe: dict[str, int]\n" not in text:
        text = replace_once(
            text,
            "class SnapshotBundleResult:\n    outputs: dict[str, str]\n    counts: dict[str, int]\n    warnings: tuple[str, ...]\n    changed_only: bool\n",
            "class SnapshotBundleResult:\n    outputs: dict[str, str]\n    counts: dict[str, int]\n    warnings: tuple[str, ...]\n    changed_only: bool\n    file_universe: dict[str, int]\n",
            "SnapshotBundleResult file_universe field",
        )

    if '"omitted_files_count": len(_omitted_files(universe))' not in text:
        text = replace_once(
            text,
            '        "omissions": len(_omitted_files(universe)),\n',
            '        "omissions": len(_omitted_files(universe)),\n        "omitted_files_count": len(_omitted_files(universe)),\n',
            "snapshot omitted_files_count",
        )

    if "file_universe=universe.manifest_counts()," not in text:
        text = replace_once(
            text,
            "        changed_only=changed_only,\n    )\n",
            "        changed_only=changed_only,\n        file_universe=universe.manifest_counts(),\n    )\n",
            "SnapshotBundleResult return file_universe",
        )

    (ROOT / relative).write_text(text, encoding="utf-8", newline="\n")
    modified.add(ROOT / relative)


def patch_handoff(modified: set[Path]) -> None:
    relative = "src/codebase_lens/reports/handoff.py"
    text = read(relative)

    if "    file_universe: dict[str, int]\n" not in text:
        text = replace_once(
            text,
            "class HandoffPackResult:\n    outputs: dict[str, str]\n    counts: dict[str, int]\n    warnings: tuple[str, ...]\n",
            "class HandoffPackResult:\n    outputs: dict[str, str]\n    counts: dict[str, int]\n    warnings: tuple[str, ...]\n    file_universe: dict[str, int]\n",
            "HandoffPackResult file_universe field",
        )

    text = text.replace("- `cbl callers --name <symbol>`", "- `cbl callers <symbol>`")

    if "file_universe=dict(snapshot.file_universe)," not in text:
        text = replace_once(
            text,
            "        warnings=tuple(warnings),\n    )\n",
            "        warnings=tuple(warnings),\n        file_universe=dict(snapshot.file_universe),\n    )\n",
            "HandoffPackResult return file_universe",
        )

    (ROOT / relative).write_text(text, encoding="utf-8", newline="\n")
    modified.add(ROOT / relative)


def _function_region(text: str, function_name: str) -> tuple[int, int]:
    start = text.find(f"def {function_name}(")
    if start < 0:
        raise RuntimeError(f"Could not find {function_name}")
    next_match = re.search(r"\ndef _run_[a-zA-Z0-9_]+\(", text[start + 1 :])
    if next_match:
        return start, start + 1 + next_match.start()
    main_match = re.search(r"\ndef main\(", text[start + 1 :])
    if main_match:
        return start, start + 1 + main_match.start()
    return start, len(text)


def _patch_manifest_file_universe_in_function(text: str, *, function_name: str, subcommand: str, expression: str) -> str:
    start, end = _function_region(text, function_name)
    block = text[start:end]
    if f"file_universe={expression}" in block:
        return text
    old = f'                "{subcommand}",\n                outputs,\n            )\n'
    new = f'                "{subcommand}",\n                outputs,\n                file_universe={expression},\n            )\n'
    if old not in block:
        raise RuntimeError(f"Could not patch manifest file_universe in {function_name}")
    block = block.replace(old, new, 1)
    return text[:start] + block + text[end:]


def patch_cli(modified: set[Path]) -> None:
    relative = "src/codebase_lens/cli.py"
    text = read(relative)
    text = _patch_manifest_file_universe_in_function(text, function_name="_run_snapshot", subcommand="snapshot", expression="result.file_universe")
    text = _patch_manifest_file_universe_in_function(text, function_name="_run_graph", subcommand="graph", expression="snapshot_result.file_universe")
    text = _patch_manifest_file_universe_in_function(text, function_name="_run_pack", subcommand="pack", expression="result.file_universe")
    (ROOT / relative).write_text(text, encoding="utf-8", newline="\n")
    modified.add(ROOT / relative)


def _list_bounds_for_key(text: str, key: str) -> tuple[int, int]:
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


def _insert_before_list_close(text: str, key: str, block: str) -> str:
    _, close = _list_bounds_for_key(text, key)
    return text[:close] + block + text[close:]


def patch_architecture(modified: set[Path]) -> None:
    relative = "src/codebase_lens/contracts/architecture.py"
    text = read(relative)
    required_file = "scripts/dev/audits/audit_phase28_manifest_consistency.py"
    if f'"{required_file}"' not in text and f"'{required_file}'" not in text:
        text = _insert_before_list_close(text, "required_files", f'            "{required_file}",\n')
    if '"path": "scripts/dev/audits/audit_phase28_manifest_consistency.py"' not in text:
        block = '''            {
                "path": "scripts/dev/audits/audit_phase28_manifest_consistency.py",
                "symbols": [
                    "ManifestConsistencyIssue",
                    "ManifestConsistencyResult",
                    "run_manifest_consistency_audit",
                    "main",
                ],
            },
'''
        text = _insert_before_list_close(text, "required_symbols", block)
    (ROOT / relative).write_text(text, encoding="utf-8", newline="\n")
    modified.add(ROOT / relative)


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
    write("scripts/dev/audits/audit_phase28_manifest_consistency.py", AUDIT, modified)
    write("tests/test_manifest_consistency.py", TEST, modified)
    patch_universe(modified)
    patch_manifest(modified)
    patch_snapshot(modified)
    patch_handoff(modified)
    patch_cli(modified)
    patch_architecture(modified)
    assert_parseable(modified)
    print("Slice 023 applied: manifest and ignored-count consistency hardened.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
