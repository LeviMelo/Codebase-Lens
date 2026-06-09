from __future__ import annotations

import ast
from pathlib import Path


def repo_root() -> Path:
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "codebase_lens" / "cli.py").is_file():
            return candidate
    raise SystemExit("ERROR: Run this updater from inside the CBL repository.")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def replace_backtick_fences(text: str) -> str:
    # The phase-24 documentation contract intentionally forbids triple-backtick
    # fences so CBL docs can be safely embedded inside larger Markdown prompts.
    return text.replace("```", "~~~")


def ensure_contains_block(text: str, *, heading: str, block: str) -> str:
    if block.strip() in text:
        return text
    return text.rstrip() + "\n\n" + heading.rstrip() + "\n\n" + block.strip() + "\n"


def patch_readme(root: Path) -> None:
    path = root / "README.md"
    text = replace_backtick_fences(read(path))

    block = """
CBL writes transient command outputs under `.codecontext/latest/`. Stable audit reports are written under `.codecontext/audits/`. The audits directory is intentionally separate from `latest` so release and safety checks remain available after later commands overwrite the latest output bundle.
""".strip()
    text = ensure_contains_block(text, heading="## Output directories", block=block)

    required = [
        "Local Codebase Lens",
        ".codecontext/latest/",
        ".codecontext/audits/",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"ERROR: README.md still misses required text: {missing}")

    write(path, text)


def patch_ai_handoff_workflow(root: Path) -> None:
    path = root / "docs" / "AI_HANDOFF_WORKFLOW.md"
    text = replace_backtick_fences(read(path))

    phrase = "Treat path and line evidence as more reliable than memory"
    block = """
Treat path and line evidence as more reliable than memory. Exact file paths, symbol definitions, line-numbered excerpts, and generated JSON records are the authority for AI-assisted work. Conversation memory is secondary and must be corrected when it conflicts with CBL evidence.
""".strip()
    if phrase not in text:
        text = ensure_contains_block(text, heading="## Evidence-first rule", block=block)

    write(path, text)


def patch_release_checklist(root: Path) -> None:
    path = root / "docs" / "RELEASE_CHECKLIST.md"
    text = replace_backtick_fences(read(path))

    audits = [
        "audit_phase30_installation_docs.py",
        "audit_phase29_dump_diffdump.py",
        "audit_phase28_manifest_consistency.py",
        "audit_phase27_reliability_corrections.py",
        "audit_phase26_v01_release_closure.py",
        "audit_phase25_report_contract_parity.py",
        "audit_phase24_documentation_workflow.py",
        "audit_phase23_audit_report_sanitization.py",
        "audit_phase22_release_safety.py",
        "audit_phase21_release_fixture_matrix.py",
        "audit_phase20_public_command_stability.py",
    ]

    missing = [audit for audit in audits if audit not in text]
    if missing:
        block_lines = [
            "Run or preserve coverage for the current release audit chain:",
            "",
        ]
        block_lines.extend(f"- `scripts/dev/audits/{audit}`" for audit in audits)
        text = ensure_contains_block(
            text,
            heading="## Current release audit chain",
            block="\n".join(block_lines),
        )

    write(path, text)


def patch_local_workflow(root: Path) -> None:
    path = root / "docs" / "LOCAL_WORKFLOW.md"
    text = replace_backtick_fences(read(path))
    write(path, text)


def patch_installation_doc(root: Path) -> None:
    path = root / "docs" / "INSTALLATION.md"
    if path.is_file():
        text = replace_backtick_fences(read(path))
        write(path, text)


def patch_pyproject_console_script(root: Path) -> None:
    path = root / "pyproject.toml"
    text = read(path)
    if "[project.scripts]" in text and "cbl = \"codebase_lens.cli:main\"" in text:
        return

    addition = '\n[project.scripts]\ncbl = "codebase_lens.cli:main"\n'
    write(path, text.rstrip() + "\n" + addition)


def verify_docs(root: Path) -> None:
    docs = [
        "README.md",
        "docs/LOCAL_WORKFLOW.md",
        "docs/AI_HANDOFF_WORKFLOW.md",
        "docs/RELEASE_CHECKLIST.md",
    ]
    for relative in docs:
        text = read(root / relative)
        if "```" in text:
            raise SystemExit(f"ERROR: {relative} still contains triple-backtick fences.")
        if len(text.strip()) <= 500:
            raise SystemExit(f"ERROR: {relative} is unexpectedly short after repair.")

    readme = read(root / "README.md")
    if ".codecontext/audits/" not in readme:
        raise SystemExit("ERROR: README.md still misses .codecontext/audits/.")

    ai = read(root / "docs" / "AI_HANDOFF_WORKFLOW.md")
    if "Treat path and line evidence as more reliable than memory" not in ai:
        raise SystemExit("ERROR: AI handoff workflow still misses the required evidence-first phrase.")

    release = read(root / "docs" / "RELEASE_CHECKLIST.md")
    for audit in (
        "audit_phase24_documentation_workflow.py",
        "audit_phase23_audit_report_sanitization.py",
        "audit_phase22_release_safety.py",
        "audit_phase21_release_fixture_matrix.py",
        "audit_phase20_public_command_stability.py",
    ):
        if audit not in release:
            raise SystemExit(f"ERROR: release checklist still misses {audit}.")


def parse_modified_python(root: Path) -> None:
    # This repair primarily patches Markdown/TOML. Parse the updater itself if it
    # has been copied into the repository, and parse core Python files that may
    # have been touched by earlier Slice 025 work.
    candidates = [
        root / "src" / "codebase_lens" / "cli.py",
        root / "src" / "codebase_lens" / "contracts" / "architecture.py",
        root / "scripts" / "dev" / "audits" / "audit_phase30_installation_docs.py",
        root / "tests" / "test_installation_docs.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            ast.parse(candidate.read_text(encoding="utf-8"), filename=str(candidate))


def main() -> int:
    root = repo_root()
    patch_pyproject_console_script(root)
    patch_readme(root)
    patch_local_workflow(root)
    patch_ai_handoff_workflow(root)
    patch_release_checklist(root)
    patch_installation_doc(root)
    verify_docs(root)
    parse_modified_python(root)

    print("Slice 025 repair applied: documentation contracts restored.")
    print("Triple-backtick fences were replaced with tilde fences in documentation files.")
    print("Required release-audit and evidence-first documentation markers are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
