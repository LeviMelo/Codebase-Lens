from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InstallationDocsIssue:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class InstallationDocsAuditResult:
    ok: bool
    issues: tuple[InstallationDocsIssue, ...]
    counts: dict[str, int]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _pyproject_has_console_script(root: Path) -> bool:
    text = _read(root / "pyproject.toml")
    return "[project.scripts]" in text and 'cbl = "codebase_lens.cli:main"' in text


def _run_module_help(root: Path) -> tuple[bool, str]:
    env = os.environ.copy()
    src = str(root / "src")
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    result = subprocess.run(
        [sys.executable, "-m", "codebase_lens", "--help"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    return result.returncode == 0 and "usage:" in result.stdout.lower(), result.stdout[-1000:] + result.stderr[-1000:]


def run_installation_docs_audit() -> InstallationDocsAuditResult:
    root = _repo_root()
    issues: list[InstallationDocsIssue] = []

    if not _pyproject_has_console_script(root):
        issues.append(
            InstallationDocsIssue(
                code="missing_console_script",
                message='pyproject.toml must expose [project.scripts] cbl = "codebase_lens.cli:main".',
                path="pyproject.toml",
            )
        )

    help_ok, help_tail = _run_module_help(root)
    if not help_ok:
        issues.append(
            InstallationDocsIssue(
                code="module_help_failed",
                message="python -m codebase_lens --help must work before package installation.",
                path=None,
            )
        )

    required_docs = {
        "README.md": [
            "python -m pip install -e .",
            "cbl doctor",
            "cbl pack",
            "cbl dump",
            "cbl diffdump",
            "CBL is local-only and does not upload your code.",
            "Review generated AI handoff reports before sharing them.",
        ],
        "docs/INSTALLATION.md": [
            "[project.scripts]",
            'cbl = "codebase_lens.cli:main"',
            "conda activate cbl-dev",
            "Get-Command cbl",
            "conda run -n cbl-dev cbl",
        ],
        "docs/LOCAL_WORKFLOW.md": [
            "cbl pack",
            "cbl dump",
            "cbl diffdump",
            "audit_phase30_installation_docs.py",
        ],
        "docs/AI_HANDOFF_WORKFLOW.md": [
            "ai_handoff.md",
            "codebase_dump.md",
            "diff_dump.md",
            "cbl graph",
        ],
        "docs/RELEASE_CHECKLIST.md": [
            "python -m pip install -e .",
            "audit_phase30_installation_docs.py",
            "cbl dump",
            "cbl diffdump",
        ],
    }

    for relative, needles in required_docs.items():
        text = _read(root / relative)
        if not text:
            issues.append(InstallationDocsIssue(code="missing_doc", message=f"Missing documentation file: {relative}", path=relative))
            continue
        for needle in needles:
            if needle not in text:
                issues.append(
                    InstallationDocsIssue(
                        code="missing_doc_phrase",
                        message=f"Documentation file {relative} does not mention required phrase: {needle}",
                        path=relative,
                    )
                )

    return InstallationDocsAuditResult(
        ok=not issues,
        issues=tuple(issues),
        counts={
            "issues": len(issues),
            "docs_checked": len(required_docs),
            "module_help_ok": 1 if help_ok else 0,
        },
    )


def _payload(result: InstallationDocsAuditResult) -> dict[str, Any]:
    return {
        "schema": {"name": "cbl.installation_docs_audit", "version": 1},
        "ok": result.ok,
        "counts": dict(result.counts),
        "issues": [asdict(issue) for issue in result.issues],
    }


def main() -> int:
    result = run_installation_docs_audit()
    latest = _repo_root() / ".codecontext" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "installation_docs_audit.json").write_text(
        json.dumps(_payload(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if result.ok:
        print("PASS: Phase 30 installation and documentation audit passed.")
        return 0

    print("FAIL: Phase 30 installation and documentation audit failed.")
    for issue in result.issues:
        location = f" [{issue.path}]" if issue.path else ""
        print(f"- {issue.code}{location}: {issue.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
