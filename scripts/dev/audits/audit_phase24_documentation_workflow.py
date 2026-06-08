from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path.cwd()


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        fail(f"Required documentation file is missing: {relative}")
    return path.read_text(encoding="utf-8")


def require_contains(relative: str, needles: list[str]) -> None:
    text = read(relative)
    missing = [needle for needle in needles if needle not in text]
    if missing:
        fail(f"{relative} is missing required text: {missing}")


def main() -> int:
    for relative in [
        "scripts/dev/audits/audit_phase24_documentation_workflow.py",
        "tests/test_documentation_workflow.py",
    ]:
        assert_parseable(relative)

    docs = [
        "README.md",
        "docs/LOCAL_WORKFLOW.md",
        "docs/AI_HANDOFF_WORKFLOW.md",
        "docs/RELEASE_CHECKLIST.md",
    ]

    for relative in docs:
        text = read(relative)
        if "```" in text:
            fail(f"{relative} uses backtick code fences; use tilde fences to avoid prompt nesting issues.")
        if "\t" in text:
            fail(f"{relative} contains tab characters.")
        if len(text.strip()) < 500:
            fail(f"{relative} is unexpectedly short.")

    require_contains(
        "README.md",
        [
            "Local Codebase Lens",
            "python -m codebase_lens pack",
            ".codecontext/latest/",
            ".codecontext/audits/",
            "PUBLIC_COMMANDS",
            "Release gates",
        ],
    )

    require_contains(
        "docs/LOCAL_WORKFLOW.md",
        [
            "conda activate cbl-dev",
            "$env:PYTHONPATH",
            "python -m codebase_lens pack",
            "python -m codebase_lens contract --no-archive",
            "git diff --check",
        ],
    )

    require_contains(
        "docs/AI_HANDOFF_WORKFLOW.md",
        [
            "handoff_projection.md",
            "handoff_projection.json",
            "Treat path and line evidence as more reliable than memory",
            "Write a repo-root updater script",
        ],
    )

    require_contains(
        "docs/RELEASE_CHECKLIST.md",
        [
            "audit_phase24_documentation_workflow.py",
            "audit_phase23_audit_report_sanitization.py",
            "audit_phase22_release_safety.py",
            "audit_phase21_release_fixture_matrix.py",
            "audit_phase20_public_command_stability.py",
            "python -m pytest",
            "git diff --check",
        ],
    )

    print("PASS: Phase 24 documentation and workflow audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
