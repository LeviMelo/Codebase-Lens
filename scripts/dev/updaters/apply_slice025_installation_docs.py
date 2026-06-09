from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path.cwd().resolve()


def _require_repo_root() -> None:
    required = [
        ROOT / "pyproject.toml",
        ROOT / "src" / "codebase_lens" / "cli.py",
        ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Run this updater from the CBL repository root. Missing: " + ", ".join(missing))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8", newline="\n")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_python(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def patch_pyproject() -> None:
    path = ROOT / "pyproject.toml"
    text = _read(path)

    if "[project]" not in text:
        raise SystemExit("pyproject.toml must contain a [project] table before adding a PEP 621 console script.")

    script_line = 'cbl = "codebase_lens.cli:main"'

    if re.search(r"(?m)^\[project\.scripts\]\s*$", text):
        lines = text.splitlines()
        out: list[str] = []
        in_table = False
        wrote = False
        table_seen = False
        for line in lines:
            stripped = line.strip()
            is_table = stripped.startswith("[") and stripped.endswith("]")
            if is_table:
                if in_table and not wrote:
                    out.append(script_line)
                    wrote = True
                in_table = stripped == "[project.scripts]"
                table_seen = table_seen or in_table
                out.append(line)
                continue
            if in_table and re.match(r"^cbl\s*=", stripped):
                if not wrote:
                    out.append(script_line)
                    wrote = True
                continue
            out.append(line)
        if in_table and not wrote:
            out.append(script_line)
        text = "\n".join(out).rstrip() + "\n"
    else:
        text = text.rstrip() + "\n\n[project.scripts]\n" + script_line + "\n"

    path.write_text(text, encoding="utf-8", newline="\n")

    try:
        import tomllib  # Python 3.11+
    except Exception:
        return
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    scripts = payload.get("project", {}).get("scripts", {})
    if scripts.get("cbl") != "codebase_lens.cli:main":
        raise SystemExit("pyproject.toml parsed, but project.scripts.cbl was not set correctly.")


def documentation_texts() -> dict[Path, str]:
    readme = r'''
# Local Codebase Lens (CBL)

Local Codebase Lens is a local static repository-evidence tool for AI-assisted coding. It scans a repository from the current working directory, builds source-grounded reports, and writes them under `.codecontext/` so a chatbot can inspect the project with less guessing and less stale-memory drift.

CBL is local-only and does not upload your code. Review generated AI handoff reports before sharing them.

## What CBL does

CBL builds an evidence package from local files and Git state. It can produce repository snapshots, source trees, Python symbol indexes, import indexes, static CLI and route inventories, test inventories, changed-file reports, changed-symbol reports, graph neighborhoods, AI handoff packs, full source dumps, and Git diff dumps.

CBL does not import or execute the target repository. It reads text, parses Python with `ast`, runs Git commands, applies hard exclusions, redacts secret-like values before report persistence, and reports omitted files explicitly.

The main commands are:

```text
cbl doctor
cbl snapshot
cbl tree
cbl symbols
cbl imports
cbl cli
cbl routes
cbl tests
cbl diff
cbl changed
cbl file
cbl symbol
cbl callers
cbl contract
cbl pack
cbl clean
cbl graph
cbl dump
cbl diffdump
```

## Installation for PowerShell

The preferred installation is an editable Python package inside the dedicated Conda environment.

```powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
cbl --help
cbl doctor --no-archive
```

After this, `cbl` is available from any directory while `cbl-dev` is active. This is the correct meaning of "global" for this project: the command is installed into the environment's `Scripts` directory, and that directory is placed on `PATH` when the environment is activated.

Use it from another repository like this:

```powershell
cd C:\Users\Galaxy\LEVI\projects\SomeOtherRepo
conda activate cbl-dev
cbl doctor --no-archive
cbl pack --issue "review this codebase for architecture and implementation risks" --budget 32000 --no-archive
```

Without activating the environment, use:

```powershell
conda run -n cbl-dev cbl doctor --no-archive
conda run -n cbl-dev cbl pack --repo C:\path\to\repo --issue "handoff" --budget 32000 --no-archive
```

Do not solve this by copying CBL source files into random PATH folders. The package entry point is the canonical launcher.

## Normal AI handoff workflow

Generate a fresh pack before asking a chatbot to modify or review a project:

```powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl pack --issue "implement the requested change without violating the architecture" --budget 32000 --no-archive
```

Then provide these files to the chatbot:

```text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/manifest.json
```

For larger or retrieval-oriented workflows, also generate a full source dump:

```powershell
cbl dump --no-archive
```

Main output:

```text
.codecontext/latest/codebase_dump.md
.codecontext/latest/codebase_dump_index.json
```

For changes between Git refs:

```powershell
cbl diffdump --from HEAD~1 --to HEAD --symbols --no-archive
```

Main output:

```text
.codecontext/latest/diff_dump.md
.codecontext/latest/diff_dump_index.json
```

## Important commands

`cbl snapshot` writes a broad repository state bundle.

```powershell
cbl snapshot --budget 32000 --no-archive
```

`cbl pack` writes the primary AI handoff pack.

```powershell
cbl pack --issue "describe the intended coding task" --budget 32000 --no-archive
```

`cbl graph` writes a scoped graph neighborhood around a symbol, path, module, or changed files.

```powershell
cbl graph --symbol write_snapshot_bundle --depth 1 --limit 100 --unresolved seed --no-archive
```

`cbl dump` writes a Markdown source corpus. It is source-first and untruncated for included files.

```powershell
cbl dump --no-archive
cbl dump --include-untracked --out-file codebase_dump.md --no-archive
```

`cbl diffdump` writes a Markdown patch corpus for a Git comparison.

```powershell
cbl diffdump --from v0.1.0 --to HEAD --symbols --unified 5 --no-archive
```

`cbl contract` checks CBL against its built-in architecture contract.

```powershell
cbl contract --no-archive
```

## Output layout

CBL writes the current command output to:

```text
.codecontext/latest/
```

Unless `--no-archive` is used, CBL also copies the latest output to:

```text
.codecontext/runs/<timestamp>/
```

During active development, prefer `--no-archive` to avoid noisy local artifacts.

## Safety model

CBL is designed for local personal use. It enforces these rules:

```text
- no target repository import or execution
- no upload behavior
- no recursive scanning of .codecontext/
- hard exclusion of secrets, environments, caches, data, build outputs, and generated artifacts
- binary and unsafe text detection
- redaction before report persistence
- repository-relative paths in AI-facing reports by default
- explicit omitted-file accounting
```

`dump` and `diffdump` intentionally emit more source text than `pack`. Review their outputs before sharing them.

## Development validation

For the CBL repository itself:

```powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path

python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
```

Run slice audits when changing release-gated behavior:

```powershell
python .\scripts\dev\audits\audit_phase30_installation_docs.py
python .\scripts\dev\audits\audit_phase29_dump_diffdump.py
python .\scripts\dev\audits\audit_phase28_manifest_consistency.py
```

## Troubleshooting

If PowerShell says `cbl` is not recognized, the package is not installed into the active environment or the environment is not active. Run:

```powershell
conda activate cbl-dev
python -m pip install -e .
Get-Command cbl
cbl --help
```

If you want to run it without activation:

```powershell
conda run -n cbl-dev cbl --help
```

If CBL detects the wrong repository, pass an explicit root:

```powershell
cbl pack --repo C:\path\to\repo --issue "handoff" --budget 32000 --no-archive
```
'''

    installation = r'''
# CBL Installation and PowerShell Setup

CBL should be installed as a Python console script. The durable implementation remains in `src/codebase_lens`; PowerShell is only a launcher environment.

## Editable development install

Run this once from the CBL repository root:

```powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
```

Verify:

```powershell
Get-Command cbl
cbl --help
cbl doctor --no-archive
```

`pip install -e .` creates a `cbl` console command inside the active environment. On Windows/Conda this means an executable shim is created under the environment's `Scripts` directory. When `conda activate cbl-dev` runs, that directory is added to `PATH`, so `cbl` works from any current directory.

## Use from any repository

```powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl doctor --no-archive
cbl pack --issue "prepare AI handoff" --budget 32000 --no-archive
```

CBL detects the repository root from the current directory. Use `--repo` when you want to run from elsewhere:

```powershell
cbl pack --repo C:\path\to\target\repo --issue "prepare AI handoff" --budget 32000 --no-archive
```

## Use without activating the environment

```powershell
conda run -n cbl-dev cbl doctor --no-archive
conda run -n cbl-dev cbl dump --repo C:\path\to\target\repo --no-archive
```

This is slower than an activated shell but useful for ad hoc calls.

## Optional PowerShell profile helper

A profile function can route calls through the Conda environment:

```powershell
function cblx {
    conda run -n cbl-dev cbl @args
}
```

Then:

```powershell
cblx doctor --repo C:\path\to\target\repo --no-archive
```

Use a different name such as `cblx` to avoid hiding the real `cbl` console command.

## Do not copy source files into PATH

Do not copy `src/codebase_lens` or repository-root scripts into a PATH directory. That creates stale launchers and bypasses the package contract. The supported command is the package entry point:

```toml
[project.scripts]
cbl = "codebase_lens.cli:main"
```

## Reinstall after environment rebuilds

If the Conda environment is recreated, run:

```powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
```
'''

    local_workflow = r'''
# CBL Local Workflow

CBL is local-only and does not upload your code. Review generated AI handoff reports before sharing them.

## Start a shell

```powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
python -m pip install -e .
cbl --help
```

For CBL development, keep `PYTHONPATH` explicit when running tests directly from the checkout:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

## Use CBL on another repository

```powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl doctor --no-archive
cbl pack --issue "explain the requested implementation task" --budget 32000 --no-archive
```

Upload or paste:

```text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/manifest.json
```

When the assistant needs exact searchable source, add:

```powershell
cbl dump --no-archive
```

When the assistant needs a change review between Git refs, add:

```powershell
cbl diffdump --from HEAD~1 --to HEAD --symbols --no-archive
```

## Development validation chain

```powershell
python .\scripts\dev\audits\audit_phase30_installation_docs.py
python .\scripts\dev\audits\audit_phase29_dump_diffdump.py
python .\scripts\dev\audits\audit_phase28_manifest_consistency.py
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
```

## Commit discipline

Do not commit until the relevant slice audit, the contract audit, pytest, and `git diff --check` pass.
'''

    ai_workflow = r'''
# CBL AI Handoff Workflow

CBL exists to make AI-mediated development evidence-driven. Do not rely on a chatbot's memory of a repository when the codebase has changed.

## Standard handoff

```powershell
cd C:\path\to\target\repo
conda activate cbl-dev
cbl pack --issue "state the concrete coding task" --budget 32000 --no-archive
```

Give the assistant:

```text
.codecontext/latest/ai_handoff.md
.codecontext/latest/handoff_projection.md
.codecontext/latest/manifest.json
```

## Large-source search handoff

Use `dump` when the assistant or platform can search a large uploaded file and needs full source text.

```powershell
cbl dump --no-archive
```

Give the assistant:

```text
.codecontext/latest/codebase_dump.md
.codecontext/latest/codebase_dump_index.json
```

The dump is intentionally source-first. Included files are not truncated. Data files, generated dump files, `.codecontext/`, binaries, and hard-excluded paths remain excluded.

## Diff review handoff

Use `diffdump` when the question is about what changed between Git refs.

```powershell
cbl diffdump --from v0.1.0 --to HEAD --symbols --no-archive
```

Give the assistant:

```text
.codecontext/latest/diff_dump.md
.codecontext/latest/diff_dump_index.json
.codecontext/latest/diff.json
```

## Follow-up context

For targeted follow-up:

```powershell
cbl symbol SomeFunction --path src/package/module.py --context 80 --no-archive
cbl file src/package/module.py --lines 1:240 --no-archive
cbl graph --symbol SomeFunction --depth 1 --limit 100 --no-archive
cbl callers SomeFunction --no-archive
```

Treat exact line-numbered excerpts as authoritative. Treat heuristic graph and likely-test findings as provisional.
'''

    checklist = r'''
# CBL Release Checklist

Run from the CBL repository root:

```powershell
cd C:\Users\Galaxy\LEVI\projects\CBL
conda activate cbl-dev
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m pip install -e .
```

## Required gates

```powershell
cbl --help
cbl doctor --no-archive
python .\scripts\dev\audits\audit_phase30_installation_docs.py
python .\scripts\dev\audits\audit_phase29_dump_diffdump.py
python .\scripts\dev\audits\audit_phase28_manifest_consistency.py
python .\scripts\dev\audits\audit_phase27_reliability_corrections.py
python .\scripts\dev\audits\audit_phase26_v01_release_closure.py --skip-pytest
python -m codebase_lens contract --no-archive
python -m pytest
git diff --check
```

## Manual smoke checks

From outside the CBL repository:

```powershell
cd C:\Users\Galaxy\LEVI\projects
cbl doctor --repo C:\Users\Galaxy\LEVI\projects\CBL --no-archive
cbl dump --repo C:\Users\Galaxy\LEVI\projects\CBL --no-archive
cbl diffdump --repo C:\Users\Galaxy\LEVI\projects\CBL --from HEAD~1 --to HEAD --symbols --no-archive
```

## Safety reminders

CBL is local-only and does not upload your code. Review generated AI handoff reports before sharing them. `dump` and `diffdump` intentionally contain more source text than `pack`.
'''

    return {
        ROOT / "README.md": readme,
        ROOT / "docs" / "INSTALLATION.md": installation,
        ROOT / "docs" / "LOCAL_WORKFLOW.md": local_workflow,
        ROOT / "docs" / "AI_HANDOFF_WORKFLOW.md": ai_workflow,
        ROOT / "docs" / "RELEASE_CHECKLIST.md": checklist,
    }


def write_docs() -> None:
    for path, text in documentation_texts().items():
        _write(path, text)


def write_audit() -> None:
    path = ROOT / "scripts" / "dev" / "audits" / "audit_phase30_installation_docs.py"
    _write(
        path,
        r'''
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
''',
    )


def write_tests() -> None:
    path = ROOT / "tests" / "test_installation_docs.py"
    _write(
        path,
        r'''
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_exposes_cbl_console_script() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" in text
    assert 'cbl = "codebase_lens.cli:main"' in text


def test_installation_docs_cover_powershell_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")

    for needle in (
        "python -m pip install -e .",
        "cbl doctor",
        "cbl pack",
        "cbl dump",
        "cbl diffdump",
        "CBL is local-only and does not upload your code.",
        "Review generated AI handoff reports before sharing them.",
    ):
        assert needle in readme

    assert "Get-Command cbl" in installation
    assert "conda run -n cbl-dev cbl" in installation


def test_phase30_audit_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dev" / "audits" / "audit_phase30_installation_docs.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Phase 30 installation and documentation audit passed." in result.stdout
''',
    )


def patch_architecture_contract() -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = _read(path)

    required_files = [
        "docs/INSTALLATION.md",
        "scripts/dev/audits/audit_phase30_installation_docs.py",
        "tests/test_installation_docs.py",
    ]
    for item in required_files:
        if f'"{item}"' not in text:
            anchor = '"scripts/dev/audits/audit_phase29_dump_diffdump.py",'
            fallback = '"scripts/dev/audits/audit_phase28_manifest_consistency.py",'
            if anchor in text:
                text = text.replace(anchor, anchor + f'\n            "{item}",', 1)
            elif fallback in text:
                text = text.replace(fallback, fallback + f'\n            "{item}",', 1)
            else:
                marker = '],\n        "required_symbols": ['
                if marker not in text:
                    raise SystemExit("Could not patch architecture required_files.")
                text = text.replace(marker, f'            "{item}",\n{marker}', 1)

    symbol_block = '''
            {
                "path": "scripts/dev/audits/audit_phase30_installation_docs.py",
                "symbols": [
                    "InstallationDocsIssue",
                    "InstallationDocsAuditResult",
                    "run_installation_docs_audit",
                    "main",
                ],
            },'''
    if '"scripts/dev/audits/audit_phase30_installation_docs.py"' not in text.split('"required_symbols"', 1)[-1]:
        marker = '],\n        "forbidden_imports": ['
        if marker not in text:
            raise SystemExit("Could not patch architecture required_symbols.")
        text = text.replace(marker, symbol_block + f"\n{marker}", 1)

    path.write_text(text, encoding="utf-8", newline="\n")
    _parse_python(path)


def main() -> int:
    _require_repo_root()
    patch_pyproject()
    write_docs()
    write_audit()
    write_tests()
    patch_architecture_contract()

    modified = [
        ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py",
        ROOT / "scripts" / "dev" / "audits" / "audit_phase30_installation_docs.py",
        ROOT / "tests" / "test_installation_docs.py",
    ]
    for path in modified:
        _parse_python(path)

    print("Slice 025 applied: PowerShell installation and documentation hardening added.")
    print("Install/update the editable console command with: python -m pip install -e .")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
