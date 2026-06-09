from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DumpScopeIssue:
    severity: str
    code: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class DumpScopeAuditResult:
    ok: bool
    issues: tuple[DumpScopeIssue, ...]
    counts: dict[str, int]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _env(root: Path) -> dict[str, str]:
    values = os.environ.copy()
    src = str(root / "src")
    current = values.get("PYTHONPATH", "")
    values["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return values


def _run(root: Path, args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd or root,
        env=_env(root),
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )


def _latest_index(root: Path) -> dict[str, Any]:
    return json.loads((root / ".codecontext" / "latest" / "codebase_dump_index.json").read_text(encoding="utf-8"))


def _latest_markdown(root: Path) -> str:
    return (root / ".codecontext" / "latest" / "codebase_dump.md").read_text(encoding="utf-8")


def _check_scoped_dump(root: Path, *, args: list[str], cwd: Path | None = None) -> list[DumpScopeIssue]:
    issues: list[DumpScopeIssue] = []
    result = _run(root, args, cwd=cwd)
    if result.returncode != 0:
        return [DumpScopeIssue("error", "dump_command_failed", "Scoped dump command failed.", {"args": args, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]})]

    text = _latest_markdown(root)
    index = _latest_index(root)
    files = index.get("files", [])

    if "Scope: `src`" not in text:
        issues.append(DumpScopeIssue("error", "scope_marker_missing", "Scoped dump markdown does not declare Scope: `src`.", {"args": args}))
    if "### FILE: `src/codebase_lens/cli.py`" not in text:
        issues.append(DumpScopeIssue("error", "src_file_missing", "Scoped dump did not include an expected src file.", {"args": args}))
    for forbidden in ("### FILE: `README.md`", "### FILE: `docs/", "### FILE: `scripts/"):
        if forbidden in text:
            issues.append(DumpScopeIssue("error", "out_of_scope_file_rendered", "Scoped dump rendered a file outside src/.", {"args": args, "marker": forbidden}))
    if index.get("scope_paths") != ["src"]:
        issues.append(DumpScopeIssue("error", "index_scope_paths_wrong", "Dump index does not record scope_paths=['src'].", {"args": args, "scope_paths": index.get("scope_paths")}))
    if not files:
        issues.append(DumpScopeIssue("error", "empty_scoped_files", "Scoped dump selected no files.", {"args": args}))
    for item in files:
        path = str(item.get("path", "")) if isinstance(item, dict) else ""
        if not path.startswith("src/"):
            issues.append(DumpScopeIssue("error", "index_out_of_scope_file", "Dump index contains a file outside src/.", {"args": args, "path": path}))
            break
    return issues


def run_dump_scoping_audit() -> DumpScopeAuditResult:
    root = _repo_root()
    issues: list[DumpScopeIssue] = []
    issues.extend(_check_scoped_dump(root, args=["dump", "--path", "src", "--no-archive"]))
    issues.extend(_check_scoped_dump(root, args=["dump", "--cwd-scope", "--no-archive"], cwd=root / "src"))

    return DumpScopeAuditResult(
        ok=not any(issue.severity == "error" for issue in issues),
        issues=tuple(issues),
        counts={"issues": len(issues), "errors": sum(1 for issue in issues if issue.severity == "error")},
    )


def main() -> int:
    root = _repo_root()
    result = run_dump_scoping_audit()
    report = {"schema": {"name": "cbl.dump_scoping_audit", "version": 1}, "ok": result.ok, "issues": [asdict(issue) for issue in result.issues], "counts": result.counts}
    stable = root / ".codecontext" / "audits" / "dump_scoping_audit.json"
    stable.parent.mkdir(parents=True, exist_ok=True)
    stable.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.ok:
        print("PASS: Phase 31 dump scoping audit passed.")
        print(f"Stable audit report: {stable}")
        return 0
    for issue in result.issues:
        print(f"FAIL: {issue.code}: {issue.message}")
    print(f"FAIL: Phase 31 dump scoping audit failed. Report: {stable}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
