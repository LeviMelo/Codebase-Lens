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
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.fixture_matrix import (
        run_release_fixture_matrix,
        write_release_fixture_matrix_report,
    )

    result = run_release_fixture_matrix(include_git_fixture=True)

    latest = ROOT / ".codecontext" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    report_path = latest / "fixture_matrix_audit.json"
    write_release_fixture_matrix_report(report_path, result)

    payload = json.loads(report_path.read_text(encoding="utf-8"))

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

    print("PASS: Phase 21 release fixture matrix audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
