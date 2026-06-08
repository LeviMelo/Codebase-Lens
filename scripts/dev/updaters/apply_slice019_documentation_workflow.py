from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

README = r'''
# Local Codebase Lens

Local Codebase Lens, abbreviated CBL, is a local-only repository inspection tool for AI-assisted coding work.

CBL does not patch code, generate application changes, upload repository contents, or execute the target application package. Its job is to inspect a local repository and emit structured, evidence-backed reports under `.codecontext/` so a developer can hand current repository context to a chatbot without relying on stale memory.

## Current status

This repository is at the v0.1 release-candidate stage.

The current implementation includes:

- repository root detection with explicit `--repo` support;
- hard-exclusion of `.git`, `.codecontext`, virtual environments, data/output/cache folders, binary artifacts, and sensitive file classes;
- static Python symbol extraction;
- static import extraction with project import resolution;
- static CLI, route, test, caller, changed-file, changed-symbol, symbol-graph, evidence-graph, and graph-query reports;
- AI handoff pack generation;
- handoff projection sidecar reports;
- architecture contract validation;
- command-surface release gate;
- external fixture-matrix release gate;
- hostile safety-fixture release gate;
- stable sanitized audit reports under `.codecontext/audits/`.

## Installation for local development

From the repository root:

~~~powershell
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m codebase_lens --help
~~~

CBL is currently intended to be run from source during development. The canonical module entrypoint is:

~~~powershell
python -m codebase_lens <command> [options]
~~~

## Basic usage

Create a full AI handoff pack for the current repository:

~~~powershell
python -m codebase_lens pack --issue "describe the coding task here" --budget 24000 --no-archive
~~~

Create a changed-scope pack:

~~~powershell
python -m codebase_lens pack --changed --issue "review current uncommitted changes" --budget 24000 --no-archive
~~~

Run the architecture contract:

~~~powershell
python -m codebase_lens contract --no-archive
~~~

Query the evidence graph:

~~~powershell
python -m codebase_lens graph --symbol write_handoff_pack --depth 1 --limit 60 --no-archive
~~~

Run against another local repository:

~~~powershell
python -m codebase_lens pack --repo C:\path\to\other\repo --issue "handoff for external repo" --budget 24000 --no-archive
~~~

## Main outputs

The latest command writes to:

~~~text
.codecontext/latest/
~~~

Important pack outputs include:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/handoff_projection.json
.codecontext/latest/pack_index.json
.codecontext/latest/evidence_graph.json
.codecontext/latest/graph_summary.md
.codecontext/latest/symbol_graph.json
.codecontext/latest/symbol_graph.md
.codecontext/latest/file_inventory.json
.codecontext/latest/manifest.json
~~~

Release audit reports are also persisted under:

~~~text
.codecontext/audits/
~~~

These stable audit reports are sanitized before persistence and should not contain raw local user-home or temp-directory paths.

## Public commands

The current public command surface is:

~~~text
doctor
snapshot
tree
symbols
imports
cli
routes
tests
diff
changed
file
symbol
callers
contract
pack
clean
graph
~~~

The public command stability audit enforces parity between `PUBLIC_COMMANDS` and argparse subcommands.

## Safety model

CBL is intentionally conservative.

By default it rejects paths outside the repository root, refuses hard-excluded paths, avoids scanning `.codecontext`, avoids common data/output/cache directories, skips binary files, skips oversized files, and redacts secret-like assignments in emitted text.

CBL analyzes Python source statically. It must not import or execute the target repository package to discover symbols, CLI handlers, routes, tests, or imports.

## Development doctrine

Production behavior belongs under `src/codebase_lens/`.

Developer scripts under `scripts/dev/` may orchestrate updates and audits, but they must not become the product implementation. Audits should protect architecture and behavior; they should not replace production code.

## Release gates

The current release gate sequence is documented in `docs/RELEASE_CHECKLIST.md`.

For normal development, run:

~~~powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python .\scripts\dev\audits\audit_phase24_documentation_workflow.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
~~~
'''

LOCAL_WORKFLOW = r'''
# CBL Local Workflow

This document defines the local workflow for developing and using Local Codebase Lens.

## Environment

Expected development environment:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
~~~

Check the command surface:

~~~powershell
python -m codebase_lens --help
~~~

## Working on CBL itself

Use CBL against its own repository when planning or reviewing implementation work:

~~~powershell
python -m codebase_lens pack --issue "current CBL development task" --budget 24000 --no-archive
~~~

Then inspect:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/handoff_projection.json
.codecontext/latest/evidence_graph.json
.codecontext/latest/graph_summary.md
~~~

## Working on another repository

Use `--repo` rather than changing directories when you want CBL to inspect another local project:

~~~powershell
python -m codebase_lens pack --repo C:\path\to\target\repo --issue "target repo task" --budget 24000 --no-archive
~~~

CBL should write outputs inside the target repository:

~~~text
C:\path\to\target\repo\.codecontext\latest\
~~~

## Common commands

Repository health:

~~~powershell
python -m codebase_lens doctor --no-archive
~~~

Full snapshot:

~~~powershell
python -m codebase_lens snapshot --budget 24000 --no-archive
~~~

AI handoff pack:

~~~powershell
python -m codebase_lens pack --issue "describe the task" --budget 24000 --no-archive
~~~

Changed-scope AI handoff pack:

~~~powershell
python -m codebase_lens pack --changed --issue "review current changes" --budget 24000 --no-archive
~~~

Specific file excerpt:

~~~powershell
python -m codebase_lens file src/codebase_lens/cli.py --lines 1:120 --no-archive
~~~

Symbol excerpt:

~~~powershell
python -m codebase_lens symbol write_handoff_pack --first --no-archive
~~~

Static callers:

~~~powershell
python -m codebase_lens callers write_handoff_pack --no-archive
~~~

Evidence graph query:

~~~powershell
python -m codebase_lens graph --symbol write_handoff_pack --depth 1 --limit 60 --no-archive
~~~

Architecture contract:

~~~powershell
python -m codebase_lens contract --no-archive
~~~

## Output behavior

`.codecontext/latest/` is intentionally transient. Each command may replace it.

`.codecontext/audits/` is stable for release audit reports. These reports are sanitized and are safer to paste into chats than raw temp-path-bearing diagnostics.

## Before committing

Run the relevant new audit first, then the release gate subset:

~~~powershell
python .\scripts\dev\audits\audit_phase24_documentation_workflow.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
~~~
'''

AI_HANDOFF_WORKFLOW = r'''
# AI Handoff Workflow

CBL exists to make chatbot-assisted coding less dependent on memory and more dependent on current local repository evidence.

## Recommended handoff flow

Run:

~~~powershell
python -m codebase_lens pack --issue "precise coding task or review question" --budget 24000 --no-archive
~~~

Then give the chatbot the relevant files from:

~~~text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/handoff_projection.json
.codecontext/latest/graph_summary.md
~~~

Use `ai_handoff.md` for broad project state.

Use `handoff_projection.md` when the chatbot needs a compact dependency-oriented reading plan.

Use `handoff_projection.json` when the chatbot should reason over machine-readable graph edges, roles, source prefixes, unresolved calls, and representative dependencies.

Use `graph_summary.md` when the chatbot needs a repository-level evidence graph overview.

## Changed-scope handoff

For uncommitted work:

~~~powershell
python -m codebase_lens pack --changed --issue "review current uncommitted changes" --budget 24000 --no-archive
~~~

Changed-scope packs are useful for:

- reviewing a patch;
- explaining what changed;
- asking whether a slice respects the architecture;
- generating the next updater script from current repository state.

## Focused graph handoff

For a specific symbol:

~~~powershell
python -m codebase_lens graph --symbol SYMBOL_NAME --depth 1 --limit 60 --no-archive
~~~

For a specific file:

~~~powershell
python -m codebase_lens graph --path src/codebase_lens/path/to/file.py --depth 1 --limit 60 --no-archive
~~~

For changed work:

~~~powershell
python -m codebase_lens graph --changed --depth 1 --limit 80 --no-archive
~~~

## What to tell the chatbot

A good prompt should say:

~~~text
Use the attached CBL output as current repository evidence. Treat path and line evidence as more reliable than memory. Do not assume files or symbols exist unless they appear in the CBL reports. Preserve the architecture contract. Provide changes as updater scripts where possible.
~~~

For implementation slices, prefer:

~~~text
Write a repo-root updater script under scripts/dev/updaters/. The updater must modify production code under src/codebase_lens/ where appropriate, add or update audits/tests, parse every modified Python file before exiting, and provide exact validation commands.
~~~

## What not to do

Do not paste raw source trees when CBL reports are sufficient.

Do not ask a chatbot to infer the current codebase from memory.

Do not treat `.codecontext/latest/` as stable storage. It is overwritten by later commands.

Do not ask the chatbot to weaken the architecture contract to pass tests unless the contract itself is demonstrably wrong.

## Audit reports

Stable release audit reports are written to:

~~~text
.codecontext/audits/
~~~

These are sanitized before persistence. They are intended to be pasteable diagnostics for command-surface, fixture-matrix, and release-safety gates.
'''

RELEASE_CHECKLIST = r'''
# CBL Release Checklist

This checklist defines the current v0.1 release gate.

Run from repository root:

~~~powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
~~~

## Phase audits

Run:

~~~powershell
python .\scripts\dev\audits\audit_phase24_documentation_workflow.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python .\scripts\dev\audits\audit_phase19_projection_roles_imports.py
python .\scripts\dev\audits\audit_phase18_projection_dedup.py
python .\scripts\dev\audits\audit_phase17_projection_noise.py
python .\scripts\dev\audits\audit_phase16_projection_generality.py
python .\scripts\dev\audits\audit_phase15_projection_semantics.py
python .\scripts\dev\audits\audit_phase14_projection_relevance.py
python .\scripts\dev\audits\audit_phase13_handoff_projection_sidecar.py
python .\scripts\dev\audits\audit_phase12_graph_query.py
python .\scripts\dev\audits\audit_phase11_evidence_graph.py
python .\scripts\dev\audits\audit_phase10_symbol_graph.py
python .\scripts\dev\audits\audit_v01_readiness.py
python .\scripts\dev\audits\audit_phase8_snapshot_pack.py
~~~

## Contract

Run:

~~~powershell
python -m codebase_lens contract --no-archive
~~~

Expected:

~~~text
CBL contract: OK
Violations: 0
Errors: 0
~~~

## Tests

Run:

~~~powershell
python -m pytest
~~~

Expected: all tests pass.

## Whitespace

Run:

~~~powershell
git diff --check
~~~

Expected: no output.

## Stable release audit reports

Run:

~~~powershell
python .\scripts\dev\audits\audit_phase20_public_command_stability.py
python .\scripts\dev\audits\audit_phase21_release_fixture_matrix.py
python .\scripts\dev\audits\audit_phase22_release_safety.py
python .\scripts\dev\audits\audit_phase23_audit_report_sanitization.py
~~~

Expected stable reports:

~~~text
.codecontext/audits/command_surface_audit.json
.codecontext/audits/fixture_matrix_audit.json
.codecontext/audits/release_safety_audit.json
~~~

These reports must not contain raw local temp or user-home path fragments.

## Functional smoke test

Run:

~~~powershell
python -m codebase_lens pack --issue "v0.1 release smoke" --budget 24000 --no-archive
python -m codebase_lens graph --symbol write_handoff_pack --depth 1 --limit 60 --no-archive
python -m codebase_lens file src/codebase_lens/cli.py --lines 1:80 --no-archive
~~~

Expected:

~~~text
CBL pack: OK
CBL graph: OK
CBL file excerpt emitted with redaction enabled
~~~

## Commit rule

Only commit after:

~~~text
- relevant new audit passes;
- command-surface gate passes;
- fixture matrix passes;
- release safety audit passes;
- audit report sanitization passes;
- architecture contract passes;
- full pytest passes;
- git diff --check is clean.
~~~
'''

AUDIT = r'''
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
'''

TEST = r'''
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
'''

def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
    if path.suffix == ".py":
        modified.add(path)


def list_bounds_for_key(text: str, key: str) -> tuple[int, int]:
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


def insert_before_list_close(text: str, key: str, block: str) -> str:
    _, close = list_bounds_for_key(text, key)
    return text[:close] + block + text[close:]


def patch_contract(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    additions = [
        "README.md",
        "docs/LOCAL_WORKFLOW.md",
        "docs/AI_HANDOFF_WORKFLOW.md",
        "docs/RELEASE_CHECKLIST.md",
        "scripts/dev/audits/audit_phase24_documentation_workflow.py",
    ]

    for required_file in additions:
        if f'"{required_file}"' not in text and f"'{required_file}'" not in text:
            text = insert_before_list_close(text, "required_files", f'            "{required_file}",\n')

    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


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

    write_file("README.md", README, modified)
    write_file("docs/LOCAL_WORKFLOW.md", LOCAL_WORKFLOW, modified)
    write_file("docs/AI_HANDOFF_WORKFLOW.md", AI_HANDOFF_WORKFLOW, modified)
    write_file("docs/RELEASE_CHECKLIST.md", RELEASE_CHECKLIST, modified)
    write_file("scripts/dev/audits/audit_phase24_documentation_workflow.py", AUDIT, modified)
    write_file("tests/test_documentation_workflow.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 019 applied: documentation and local workflow hardening added.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())