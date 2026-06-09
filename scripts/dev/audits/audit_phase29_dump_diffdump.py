from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json
import os
import shutil
import subprocess
import sys
import tempfile

from codebase_lens.core.audit_artifacts import write_audit_report_pair


@dataclass(frozen=True)
class DumpDiffdumpIssue:
    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DumpDiffdumpResult:
    ok: bool
    issues: tuple[DumpDiffdumpIssue, ...]
    counts: dict[str, int]
    artifacts: dict[str, str]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _src_root() -> Path:
    return _repo_root() / "src"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    src = str(_src_root())
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return env


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "codebase_lens", *args], cwd=cwd, env=_env(), text=True, capture_output=True, check=False, timeout=60)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _make_repo(workspace: Path) -> tuple[Path, str]:
    repo = workspace / "target"
    pkg = repo / "src" / "demo_pkg"
    tests = repo / "tests"
    data = repo / "data"
    pkg.mkdir(parents=True); tests.mkdir(parents=True); data.mkdir(parents=True)
    _write(repo / "pyproject.toml", "[project]\nname = 'demo-pkg'\nversion = '0.0.0'\n")
    _write(repo / "README.md", "# Demo\n")
    _write(repo / "codebase_dump.md", "recursive poison\n")
    _write(data / "large.csv", "a,b\n1,2\n")
    _write(pkg / "__init__.py", "\"\"\"Demo package.\"\"\"\n")
    _write(pkg / "core.py", "\"\"\"Core demo module docstring.\"\"\"\n\nfrom __future__ import annotations\n\n\ndef normalize_name(name: str) -> str:\n    \"\"\"Return a normalized name.\"\"\"\n    return name.strip().lower()\n")
    _write(tests / "test_core.py", "from demo_pkg.core import normalize_name\n\n\ndef test_normalize_name():\n    assert normalize_name(\" A \") == \"a\"\n")
    _git(repo, "init"); _git(repo, "config", "user.email", "fixture@example.invalid"); _git(repo, "config", "user.name", "CBL Fixture")
    _git(repo, "add", ".")
    commit = _git(repo, "commit", "-m", "initial")
    if commit.returncode != 0: raise RuntimeError(commit.stderr or commit.stdout)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _write(pkg / "core.py", "\"\"\"Core demo module docstring.\"\"\"\n\nfrom __future__ import annotations\n\n\ndef normalize_name(name: str) -> str:\n    \"\"\"Return a normalized name.\"\"\"\n    return name.strip().casefold()\n\n\ndef render_name(name: str) -> str:\n    \"\"\"Return a display name.\"\"\"\n    return f\"name={normalize_name(name)}\"\n")
    _git(repo, "add", ".")
    second = _git(repo, "commit", "-m", "change core")
    if second.returncode != 0: raise RuntimeError(second.stderr or second.stdout)
    return repo, base


def run_dump_diffdump_audit() -> DumpDiffdumpResult:
    issues: list[DumpDiffdumpIssue] = []
    artifacts: dict[str, str] = {}
    if shutil.which("git") is None:
        return DumpDiffdumpResult(True, (DumpDiffdumpIssue("warning", "git_unavailable", "Git is unavailable; audit skipped."),), {}, {})
    with tempfile.TemporaryDirectory(prefix="cbl_dump_diffdump_") as temp_dir:
        repo, base = _make_repo(Path(temp_dir))
        dump = _run(["dump", "--repo", str(repo), "--no-archive"], repo)
        if dump.returncode != 0:
            issues.append(DumpDiffdumpIssue("error", "dump_failed", "cbl dump failed.", {"stdout": dump.stdout, "stderr": dump.stderr}))
            return DumpDiffdumpResult(False, tuple(issues), {}, artifacts)
        latest = repo / ".codecontext" / "latest"
        text = (latest / "codebase_dump.md").read_text(encoding="utf-8")
        index = json.loads((latest / "codebase_dump_index.json").read_text(encoding="utf-8"))
        artifacts["dump_md"] = str(latest / "codebase_dump.md")
        checks = {"contains_source_file": "FILE: `src/demo_pkg/core.py`" in text, "contains_docstring": "Core demo module docstring." in text, "contains_symbol": "SYMBOL: `normalize_name`" in text, "contains_full_source": "def render_name" in text, "excludes_data_csv_source": "FILE: `data/large.csv`" not in text and "a,b" not in text, "excludes_recursive_dump": "recursive poison" not in text, "index_has_files": int(index.get("counts", {}).get("included_files", 0)) >= 3}
        for code, ok in checks.items():
            if not ok: issues.append(DumpDiffdumpIssue("error", code, f"Dump invariant failed: {code}"))
        diffdump = _run(["diffdump", "--repo", str(repo), "--from", base, "--to", "HEAD", "--symbols", "--no-archive"], repo)
        if diffdump.returncode != 0:
            issues.append(DumpDiffdumpIssue("error", "diffdump_failed", "cbl diffdump failed.", {"stdout": diffdump.stdout, "stderr": diffdump.stderr}))
            return DumpDiffdumpResult(False, tuple(issues), {}, artifacts)
        latest = repo / ".codecontext" / "latest"
        diff_text = (latest / "diff_dump.md").read_text(encoding="utf-8")
        diff_payload = json.loads((latest / "diff_dump_index.json").read_text(encoding="utf-8"))
        artifacts["diff_dump_md"] = str(latest / "diff_dump.md")
        diff_checks = {"contains_range": f"From: `{base}`" in diff_text and "To: `HEAD`" in diff_text, "contains_patch": "~~~~diff" in diff_text and "+def render_name" in diff_text, "contains_changed_file": "src/demo_pkg/core.py" in diff_text, "index_changed_files": int(diff_payload.get("counts", {}).get("changed_files_count", 0)) >= 1}
        for code, ok in diff_checks.items():
            if not ok: issues.append(DumpDiffdumpIssue("error", code, f"Diffdump invariant failed: {code}"))
    return DumpDiffdumpResult(not any(issue.severity == "error" for issue in issues), tuple(issues), {"issues": len(issues), "errors": sum(1 for issue in issues if issue.severity == "error")}, artifacts)


def main() -> int:
    result = run_dump_diffdump_audit()
    payload = {"schema": {"name": "cbl.audit.dump_diffdump", "version": 1}, "ok": result.ok, "issues": [asdict(issue) for issue in result.issues], "counts": dict(result.counts), "artifacts": dict(result.artifacts)}
    write_audit_report_pair(_repo_root(), "dump_diffdump", payload)
    if result.ok:
        print("PASS: Phase 29 dump and diffdump audit passed."); return 0
    print("FAIL: Phase 29 dump and diffdump audit failed.")
    for issue in result.issues: print(f"{issue.severity.upper()}: {issue.code}: {issue.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
