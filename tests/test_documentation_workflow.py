from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_documentation_files_exist_and_are_substantial() -> None:
    for relative in [
        "README.md",
        "docs/LOCAL_WORKFLOW.md",
        "docs/AI_HANDOFF_WORKFLOW.md",
        "docs/RELEASE_CHECKLIST.md",
    ]:
        path = ROOT / relative
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert len(text.strip()) > 500
        assert "```" not in text


def test_readme_documents_core_outputs_and_release_gates() -> None:
    text = read("README.md")

    assert "Local Codebase Lens" in text
    assert ".codecontext/latest/" in text
    assert ".codecontext/audits/" in text
    assert "python -m codebase_lens pack" in text
    assert "python -m codebase_lens contract --no-archive" in text
    assert "Release gates" in text


def test_ai_handoff_workflow_documents_evidence_first_usage() -> None:
    text = read("docs/AI_HANDOFF_WORKFLOW.md")

    assert "Treat path and line evidence as more reliable than memory" in text
    assert "handoff_projection.md" in text
    assert "handoff_projection.json" in text
    assert "Write a repo-root updater script" in text


def test_release_checklist_includes_current_release_audits() -> None:
    text = read("docs/RELEASE_CHECKLIST.md")

    for audit in [
        "audit_phase24_documentation_workflow.py",
        "audit_phase23_audit_report_sanitization.py",
        "audit_phase22_release_safety.py",
        "audit_phase21_release_fixture_matrix.py",
        "audit_phase20_public_command_stability.py",
    ]:
        assert audit in text

    assert "python -m pytest" in text
    assert "git diff --check" in text
