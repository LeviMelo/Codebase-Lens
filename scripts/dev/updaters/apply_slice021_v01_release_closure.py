from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

RELEASE_STATUS = r'''
# CBL v0.1 Release Status

Local Codebase Lens is now at v0.1 release-candidate closure.

This release is a local-only repository evidence engine for AI-assisted coding. It inspects a local repository, builds static evidence artifacts, and emits AI handoff reports under `.codecontext/`.

## Release Identity

- Tool name: Local Codebase Lens
- Abbreviation: CBL
- Version target: v0.1
- Execution model: local-only
- Primary entrypoint: `python -m codebase_lens`
- Output root: `.codecontext/`
- Stable audit report root: `.codecontext/audits/`

## Implemented Public Command Surface

The v0.1 public command surface contains 17 commands:

- `doctor`
- `snapshot`
- `tree`
- `symbols`
- `imports`
- `cli`
- `routes`
- `tests`
- `diff`
- `changed`
- `file`
- `symbol`
- `callers`
- `contract`
- `pack`
- `clean`
- `graph`

The command-surface gate enforces exact parity between `PUBLIC_COMMANDS` and argparse subcommands.

## Implemented Evidence Capabilities

CBL v0.1 implements:

- safe repository-root detection;
- explicit `--repo` support for external local repositories;
- hard-excluded path handling;
- binary and oversized-file exclusion;
- redaction of secret-like assignments and private-key blocks;
- static Python symbol extraction;
- static import extraction and project import resolution;
- static CLI command discovery;
- static route discovery;
- test inventory and fixture discovery;
- Git changed-file and changed-symbol mapping;
- file and symbol excerpts;
- static caller search;
- symbol graph generation;
- evidence graph generation;
- scoped graph query;
- AI handoff pack generation;
- handoff projection sidecar reports;
- architecture contract validation;
- stable sanitized release audit reports.

## Canonical v0.1 Report Outputs

The current report contract includes:

- `.codecontext/latest/repo_snapshot.md`
- `.codecontext/latest/git_state.json`
- `.codecontext/latest/snapshot_index.json`
- `.codecontext/latest/file_inventory.json`
- `.codecontext/latest/repo_tree.txt`
- `.codecontext/latest/symbol_index.json`
- `.codecontext/latest/import_graph.json`
- `.codecontext/latest/cli_inventory.json`
- `.codecontext/latest/route_inventory.json`
- `.codecontext/latest/test_inventory.json`
- `.codecontext/latest/omissions.json`
- `.codecontext/latest/budget_report.json`
- `.codecontext/latest/diff.json`
- `.codecontext/latest/diff_summary.md`
- `.codecontext/latest/contract_audit.json`
- `.codecontext/latest/contract_audit.md`
- `.codecontext/latest/contract_report.json`
- `.codecontext/latest/ai_handoff.md`
- `.codecontext/latest/handoff_projection.md`
- `.codecontext/latest/handoff_projection.json`
- `.codecontext/latest/evidence_graph.json`
- `.codecontext/latest/graph_summary.md`
- `.codecontext/latest/symbol_graph.json`
- `.codecontext/latest/symbol_graph.md`
- `.codecontext/latest/graph_query.json`
- `.codecontext/latest/graph_query.md`
- `.codecontext/latest/manifest.json`

`contract_audit.json` is the canonical TDD-aligned contract output. `contract_report.json` is retained as a compatibility alias.

## Safety Invariants

CBL v0.1 must preserve these invariants:

- it must not import or execute the target repository package;
- it must reject paths that resolve outside the repository root;
- it must not recursively scan `.codecontext`;
- it must not scan `.env` files;
- it must not scan common data, output, cache, virtual-environment, or dependency folders;
- it must not leak raw secret markers into AI-facing artifacts;
- it must not write raw local temp or user-home paths into stable audit reports;
- it must keep production behavior under `src/codebase_lens/`;
- it must keep developer scripts as orchestration, not product implementation.

## Release Gates

The v0.1 release closure gate is:

~~~powershell
python .\scripts\dev\audits\audit_phase26_v01_release_closure.py
~~~

For a faster non-recursive test-mode gate:

~~~powershell
python .\scripts\dev\audits\audit_phase26_v01_release_closure.py --skip-pytest
~~~

The release gate validates:

- report contract parity;
- documentation workflow;
- audit report path sanitization;
- release safety hostile fixture;
- external fixture matrix;
- public command stability;
- architecture contract;
- functional snapshot, pack, graph, diff, and contract smoke checks;
- full pytest run unless `--skip-pytest` is supplied;
- `git diff --check`.

## Known v0.1 Boundaries

CBL v0.1 is intentionally static. It does not dynamically import the target project to discover runtime behavior.

The graph is evidence-oriented, not a full program-analysis graph. Dynamic dispatch, reflection, dependency injection, metaprogramming, generated code, and framework-specific runtime registration may be represented as unresolved or heuristic evidence.

Token budgeting is heuristic. The v0.1 estimator uses `max(1, file_size_bytes // 4)` and is intentionally simple.

CBL does not generate code patches. It generates repository evidence and handoff artifacts.

## Release Decision

CBL v0.1 is ready when `audit_phase26_v01_release_closure.py` passes, the architecture contract passes, all pytest tests pass, and `git diff --check` is clean.
'''

AUDIT = r'''
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
SRC = ROOT / "src"


@dataclass(frozen=True)
class ReleaseCheck:
    name: str
    command: list[str]
    returncode: int
    duration_seconds: float
    stdout_tail: str
    stderr_tail: str


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def run_command(name: str, command: list[str]) -> ReleaseCheck:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )
    duration = round(time.perf_counter() - started, 3)

    return ReleaseCheck(
        name=name,
        command=command,
        returncode=result.returncode,
        duration_seconds=duration,
        stdout_tail=result.stdout[-3000:],
        stderr_tail=result.stderr[-3000:],
    )


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def assert_file_contains(relative: str, required: list[str]) -> None:
    path = ROOT / relative
    if not path.is_file():
        fail(f"Required release file is missing: {relative}")

    text = path.read_text(encoding="utf-8")
    missing = [item for item in required if item not in text]
    if missing:
        fail(f"{relative} is missing required release text: {missing}")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"Expected JSON artifact is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"Expected JSON object in artifact: {path}")
    return value


def write_release_report(checks: list[ReleaseCheck], *, skipped_pytest: bool) -> Path:
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    failures = [check for check in checks if check.returncode != 0]
    payload = {
        "schema": {
            "name": "cbl.v01_release_closure",
            "version": 1,
        },
        "ok": not failures,
        "skipped_pytest": skipped_pytest,
        "counts": {
            "checks": len(checks),
            "failures": len(failures),
            "passed": len(checks) - len(failures),
        },
        "checks": [asdict(check) for check in checks],
    }

    stable_path, _latest_path = write_audit_report_pair(ROOT, "v01_release_closure", payload)
    return stable_path


def assert_latest_artifacts() -> None:
    latest = ROOT / ".codecontext" / "latest"

    required = [
        "manifest.json",
        "contract_audit.json",
        "contract_audit.md",
        "contract_report.json",
    ]

    for filename in required:
        if not (latest / filename).is_file():
            fail(f"Missing latest release artifact after contract check: {filename}")

    payload = load_json(latest / "contract_audit.json")
    if payload.get("schema", {}).get("name") != "cbl.contract_audit":
        fail("contract_audit.json has wrong schema name.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-pytest", action="store_true", help="Skip full pytest run for non-recursive test contexts.")
    args = parser.parse_args(argv)

    for relative in [
        "scripts/dev/audits/audit_phase26_v01_release_closure.py",
        "tests/test_v01_release_closure.py",
    ]:
        assert_parseable(relative)

    assert_file_contains(
        "docs/V0_1_RELEASE_STATUS.md",
        [
            "CBL v0.1 Release Status",
            "Implemented Public Command Surface",
            "Canonical v0.1 Report Outputs",
            "Safety Invariants",
            "Release Gates",
            "Known v0.1 Boundaries",
        ],
    )

    checks: list[ReleaseCheck] = []

    commands: list[tuple[str, list[str]]] = [
        ("phase25_report_contract_parity", [sys.executable, "scripts/dev/audits/audit_phase25_report_contract_parity.py"]),
        ("phase24_documentation_workflow", [sys.executable, "scripts/dev/audits/audit_phase24_documentation_workflow.py"]),
        ("phase23_audit_report_sanitization", [sys.executable, "scripts/dev/audits/audit_phase23_audit_report_sanitization.py"]),
        ("phase22_release_safety", [sys.executable, "scripts/dev/audits/audit_phase22_release_safety.py"]),
        ("phase21_release_fixture_matrix", [sys.executable, "scripts/dev/audits/audit_phase21_release_fixture_matrix.py"]),
        ("phase20_public_command_stability", [sys.executable, "scripts/dev/audits/audit_phase20_public_command_stability.py"]),
        ("contract", [sys.executable, "-m", "codebase_lens", "contract", "--no-archive"]),
        ("snapshot_smoke", [sys.executable, "-m", "codebase_lens", "snapshot", "--budget", "24000", "--no-archive"]),
        ("pack_smoke", [sys.executable, "-m", "codebase_lens", "pack", "--issue", "v0.1 release closure smoke", "--budget", "24000", "--no-archive"]),
        ("graph_smoke", [sys.executable, "-m", "codebase_lens", "graph", "--symbol", "write_handoff_pack", "--depth", "1", "--limit", "60", "--no-archive"]),
        ("diff_smoke", [sys.executable, "-m", "codebase_lens", "diff", "--symbols", "--no-archive"]),
    ]

    if not args.skip_pytest:
        commands.append(("pytest", [sys.executable, "-m", "pytest"]))

    commands.append(("git_diff_check", ["git", "diff", "--check"]))

    for name, command in commands:
        check = run_command(name, command)
        checks.append(check)
        status = "PASS" if check.returncode == 0 else "FAIL"
        print(f"{status}: {name} ({check.duration_seconds}s)")

        if check.returncode != 0:
            print(check.stdout_tail)
            print(check.stderr_tail)
            report_path = write_release_report(checks, skipped_pytest=args.skip_pytest)
            fail(f"Release closure failed at {name}. Report: {report_path}")

    assert_latest_artifacts()
    report_path = write_release_report(checks, skipped_pytest=args.skip_pytest)

    print("PASS: Phase 26 v0.1 release closure audit passed.")
    print(f"Stable release report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST = r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def test_v01_release_status_document_exists_and_names_release_gates() -> None:
    path = ROOT / "docs" / "V0_1_RELEASE_STATUS.md"

    assert path.is_file()
    text = path.read_text(encoding="utf-8")

    for required in [
        "CBL v0.1 Release Status",
        "Implemented Public Command Surface",
        "Canonical v0.1 Report Outputs",
        "Safety Invariants",
        "Release Gates",
        "Known v0.1 Boundaries",
        "audit_phase26_v01_release_closure.py",
    ]:
        assert required in text


def test_v01_release_closure_audit_passes_without_recursive_pytest() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/dev/audits/audit_phase26_v01_release_closure.py",
            "--skip-pytest",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Phase 26 v0.1 release closure audit passed." in result.stdout

    report = ROOT / ".codecontext" / "audits" / "v01_release_closure.json"
    assert report.is_file()

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema"]["name"] == "cbl.v01_release_closure"
    assert payload["ok"] is True
    assert payload["skipped_pytest"] is True
    assert payload["counts"]["failures"] == 0
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
        "docs/V0_1_RELEASE_STATUS.md",
        "scripts/dev/audits/audit_phase26_v01_release_closure.py",
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

    write_file("docs/V0_1_RELEASE_STATUS.md", RELEASE_STATUS, modified)
    write_file("scripts/dev/audits/audit_phase26_v01_release_closure.py", AUDIT, modified)
    write_file("tests/test_v01_release_closure.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 021 applied: v0.1 release closure audit and status document added.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())