from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def patch_manifest() -> None:
    path = ROOT / "src/codebase_lens/reports/manifest.py"
    text = path.read_text(encoding="utf-8")

    old = '''        "repo": {
            "name": repo_name,
            "root": str(repo_root.resolve()),
            "root_redacted_for_ai": root_redacted_for_ai,
            "is_git_repo": is_git_repo,
            "detected_project_types": ["python"] if (repo_root / "pyproject.toml").exists() else [],
            "primary_language": "python" if (repo_root / "pyproject.toml").exists() else None,
        },
'''

    new = '''        "repo": {
            "name": repo_name,
            "root": "<redacted>" if root_redacted_for_ai else str(repo_root.resolve()),
            "root_redacted_for_ai": root_redacted_for_ai,
            "is_git_repo": is_git_repo,
            "detected_project_types": ["python"] if (repo_root / "pyproject.toml").exists() else [],
            "primary_language": "python" if (repo_root / "pyproject.toml").exists() else None,
        },
'''

    if old not in text:
        raise RuntimeError("Could not patch manifest.py: expected repo manifest block was not found.")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_phase6_audit() -> None:
    path = ROOT / "scripts/dev/audits/audit_phase6_tests_callers.py"
    text = path.read_text(encoding="utf-8")

    old = '''        if manifest["outputs"].get("callers_json") != ".codecontext/latest/callers.json":
            fail("manifest does not declare callers_json.")

    print("PASS: Phase 6 tests/callers audit passed.")
'''

    new = '''        if manifest["outputs"].get("callers_json") != ".codecontext/latest/callers.json":
            fail("manifest does not declare callers_json.")
        if manifest["repo"].get("root") != "<redacted>":
            fail("manifest repo.root must be redacted when root_redacted_for_ai is true.")

    print("PASS: Phase 6 tests/callers audit passed.")
'''

    if old not in text:
        raise RuntimeError("Could not patch Phase 6 audit: expected manifest assertion block was not found.")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    patch_manifest()
    patch_phase6_audit()
    print("Repair applied: manifest repo.root is redacted when root_redacted_for_ai is true.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())