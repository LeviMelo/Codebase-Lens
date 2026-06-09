from __future__ import annotations

import ast
import sys
from pathlib import Path

REQUIRED_DOCS = (
    Path("README.md"),
    Path("docs/LOCAL_WORKFLOW.md"),
    Path("docs/AI_HANDOFF_WORKFLOW.md"),
    Path("docs/RELEASE_CHECKLIST.md"),
    Path("docs/INSTALLATION.md"),
)

REQUIRED_RELEASE_AUDITS = (
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
)


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "codebase_lens").is_dir():
            return candidate
    raise SystemExit("FAIL: Could not locate CBL repository root from updater path.")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def ensure_no_backtick_fences(text: str) -> str:
    return text.replace("```", "~~~")


def append_once(text: str, marker: str, block: str) -> str:
    if marker in text:
        return text
    return text.rstrip() + "\n\n" + block.strip() + "\n"


def command_surface_from_constants(root: Path) -> tuple[str, ...]:
    constants = root / "src" / "codebase_lens" / "core" / "constants.py"
    tree = ast.parse(read(constants), filename=str(constants))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "PUBLIC_COMMANDS" for target in node.targets):
            if isinstance(node.value, (ast.Tuple, ast.List)):
                values = []
                for item in node.value.elts:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        values.append(item.value)
                return tuple(values)
    return ()


def repair_readme(root: Path) -> None:
    path = root / "README.md"
    text = ensure_no_backtick_fences(read(path))

    commands = command_surface_from_constants(root)
    command_lines = "\n".join(f"- {command}" for command in commands)

    block = f"""
## Documentation contract compatibility

This section intentionally preserves exact documentation-contract markers used by the release audits.

Local Codebase Lens remains a local static repository-evidence tool. The primary output directory is `.codecontext/latest/`. Stable audit reports are preserved under `.codecontext/audits/` so safety, release, and command-surface checks remain inspectable after `.codecontext/latest/` is overwritten by later commands.

The canonical module invocation remains available for automation and documentation compatibility:

~~~powershell
python -m codebase_lens pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

The installed console command is equivalent for normal use:

~~~powershell
cbl pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

### PUBLIC_COMMANDS

`PUBLIC_COMMANDS` is the public command-surface contract. The current command surface is:

{command_lines}

### Release gates

Release gates must be run from the CBL repository root. They include the command-surface audit, fixture-matrix audit, release-safety audit, documentation-workflow audit, report-contract parity audit, release-closure audit, reliability-corrections audit, manifest-consistency audit, dump/diffdump audit, installation-docs audit, the built-in architecture contract, the pytest suite, and `git diff --check`.

The release gates protect the local-only model, static-analysis-only behavior, `.codecontext/` recursion exclusion, report contract parity, public command stability, and AI-facing documentation compatibility.
"""
    text = append_once(text, "## Documentation contract compatibility", block)
    text = ensure_no_backtick_fences(text)
    write(path, text)


def repair_local_workflow(root: Path) -> None:
    path = root / "docs" / "LOCAL_WORKFLOW.md"
    text = ensure_no_backtick_fences(read(path))

    block = """
## Compatibility command forms

Use the installed console command for normal local work:

~~~powershell
cbl pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

The canonical module invocation remains documented and supported:

~~~powershell
python -m codebase_lens pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

Run these commands from the target repository root, or pass `--repo` explicitly. Do not run repo-local validation commands from a parent workspace unless that is intentional.
"""
    text = append_once(text, "## Compatibility command forms", block)
    text = ensure_no_backtick_fences(text)
    write(path, text)


def repair_ai_handoff(root: Path) -> None:
    path = root / "docs" / "AI_HANDOFF_WORKFLOW.md"
    text = ensure_no_backtick_fences(read(path))

    block = """
## Evidence-first implementation protocol

Treat path and line evidence as more reliable than memory. When conversation memory conflicts with CBL artifacts, the artifact with repository-relative path and line evidence wins.

Use `ai_handoff.md` for the narrative task context. Use `handoff_projection.md` for a compact human-readable project projection. Use `handoff_projection.json` for deterministic inspection, downstream tooling, and exact machine-readable project-profile fields.

For implementation requests, instruct the AI to: Write a repo-root updater script. The updater must be executable from the repository root, must patch files deterministically, must parse modified Python files before exiting, and must avoid ad hoc manual edit instructions.

Preferred implementation prompt shape:

~~~text
Read the CBL handoff artifacts. Treat path and line evidence as more reliable than memory. Write a repo-root updater script that applies the requested change, updates tests/audits if needed, and exits only after modified Python files parse.
~~~
"""
    text = append_once(text, "## Evidence-first implementation protocol", block)
    text = ensure_no_backtick_fences(text)
    write(path, text)


def repair_release_checklist(root: Path) -> None:
    path = root / "docs" / "RELEASE_CHECKLIST.md"
    text = ensure_no_backtick_fences(read(path))

    audit_lines = "\n".join(f"- `scripts/dev/audits/{name}`" for name in REQUIRED_RELEASE_AUDITS)
    command_lines = "\n".join(f"python .\\scripts\\dev\\audits\\{name}" for name in REQUIRED_RELEASE_AUDITS if name != "audit_phase26_v01_release_closure.py")
    block = f"""
## Current release audit inventory

The release checklist must mention the current audit chain explicitly:

{audit_lines}

Run release gates from the repository root. The phase-26 release-closure audit delegates to older release gates and can be run with `--skip-pytest` for recursive-audit use.

~~~powershell
{command_lines}
python .\\scripts\\dev\\audits\\audit_phase26_v01_release_closure.py --skip-pytest
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
~~~
"""
    text = append_once(text, "## Current release audit inventory", block)
    text = ensure_no_backtick_fences(text)
    write(path, text)


def repair_installation(root: Path) -> None:
    path = root / "docs" / "INSTALLATION.md"
    if not path.exists():
        return
    text = ensure_no_backtick_fences(read(path))
    block = """
## Module invocation compatibility

Even when `cbl` is installed as a console command, the module invocation remains valid:

~~~powershell
python -m codebase_lens pack --issue "prepare AI handoff" --budget 32000 --no-archive
~~~

This form is useful in tests, audits, and environments where console-script shims are not on PATH.
"""
    text = append_once(text, "## Module invocation compatibility", block)
    text = ensure_no_backtick_fences(text)
    write(path, text)


def assert_contains(text: str, path: str, values: tuple[str, ...], errors: list[str]) -> None:
    missing = [value for value in values if value not in text]
    if missing:
        errors.append(f"{path} missing required text: {missing}")


def preflight(root: Path) -> None:
    errors: list[str] = []

    for relative in REQUIRED_DOCS:
        path = root / relative
        if not path.is_file():
            errors.append(f"Missing documentation file: {relative.as_posix()}")
            continue
        text = read(path)
        if "```" in text:
            errors.append(f"{relative.as_posix()} still contains triple-backtick fences.")
        if len(text.strip()) <= 500 and relative != Path("docs/INSTALLATION.md"):
            errors.append(f"{relative.as_posix()} is unexpectedly short.")

    readme = read(root / "README.md")
    assert_contains(
        readme,
        "README.md",
        (
            "Local Codebase Lens",
            ".codecontext/latest/",
            ".codecontext/audits/",
            "python -m codebase_lens pack",
            "PUBLIC_COMMANDS",
            "Release gates",
        ),
        errors,
    )

    ai = read(root / "docs" / "AI_HANDOFF_WORKFLOW.md")
    assert_contains(
        ai,
        "docs/AI_HANDOFF_WORKFLOW.md",
        (
            "Treat path and line evidence as more reliable than memory",
            "handoff_projection.md",
            "handoff_projection.json",
            "Write a repo-root updater script",
        ),
        errors,
    )

    local = read(root / "docs" / "LOCAL_WORKFLOW.md")
    assert_contains(
        local,
        "docs/LOCAL_WORKFLOW.md",
        ("python -m codebase_lens pack",),
        errors,
    )

    release = read(root / "docs" / "RELEASE_CHECKLIST.md")
    assert_contains(
        release,
        "docs/RELEASE_CHECKLIST.md",
        REQUIRED_RELEASE_AUDITS,
        errors,
    )

    pyproject = read(root / "pyproject.toml")
    assert_contains(
        pyproject,
        "pyproject.toml",
        ("[project.scripts]", 'cbl = "codebase_lens.cli:main"'),
        errors,
    )

    if errors:
        print("FAIL: documentation marker repair preflight failed.")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)


def main() -> int:
    root = repo_root()

    repair_readme(root)
    repair_local_workflow(root)
    repair_ai_handoff(root)
    repair_release_checklist(root)
    repair_installation(root)

    preflight(root)

    print("Slice 025 definitive documentation-contract repair applied.")
    print("Phase-24 exact documentation markers are present in README, local workflow, AI workflow, and release checklist.")
    print("Triple-backtick fences are absent from required documentation files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
