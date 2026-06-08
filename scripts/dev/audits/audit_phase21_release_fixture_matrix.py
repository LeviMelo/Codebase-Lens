from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def main() -> int:
    sys.path.insert(0, str(SRC))

    for relative in [
        "src/codebase_lens/contracts/fixture_matrix.py",
        "src/codebase_lens/contracts/command_surface.py",
        "src/codebase_lens/core/audit_artifacts.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.fixture_matrix import (
        release_fixture_matrix_payload,
        run_release_fixture_matrix,
    )
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    result = run_release_fixture_matrix(include_git_fixture=True)
    payload = release_fixture_matrix_payload(result)
    stable_path, latest_path = write_audit_report_pair(ROOT, "fixture_matrix_audit", payload)

    if payload.get("schema", {}).get("name") != "cbl.release_fixture_matrix":
        fail("Fixture matrix report has wrong schema name.")

    required_cases = {
        "basic_package",
        "argparse_cli_package",
        "route_static_package",
        "safety_redaction_package",
        "codecontext_recursion_package",
    }
    observed_cases = {case.get("name") for case in payload.get("cases", [])}
    missing_cases = sorted(required_cases - observed_cases)
    if missing_cases:
        fail(f"Fixture matrix did not run required cases: {missing_cases}")

    if not result.ok:
        formatted = json.dumps(payload.get("issues", []), indent=2, sort_keys=True)
        fail(f"Release fixture matrix failed:\n{formatted}")

    if payload.get("counts", {}).get("passed", 0) < 5:
        fail(f"Too few fixture cases passed: {payload.get('counts')}")

    if not stable_path.is_file() or not latest_path.is_file():
        fail("Fixture matrix audit report was not written to stable and latest locations.")

    print("PASS: Phase 21 release fixture matrix audit passed.")
    print(f"Stable audit report: {stable_path}")
    print(f"Latest audit report: {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
