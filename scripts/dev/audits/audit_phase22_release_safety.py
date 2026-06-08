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
        "src/codebase_lens/core/audit_artifacts.py",
        "src/codebase_lens/contracts/release_safety.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.release_safety import (
        release_safety_audit_payload,
        run_release_safety_audit,
    )
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    result = run_release_safety_audit()
    payload = release_safety_audit_payload(result)
    stable_path, latest_path = write_audit_report_pair(ROOT, "release_safety_audit", payload)

    if not stable_path.is_file():
        fail(f"Stable safety audit report was not written: {stable_path}")
    if not latest_path.is_file():
        fail(f"Latest safety audit report was not written: {latest_path}")

    loaded = json.loads(stable_path.read_text(encoding="utf-8"))
    if loaded.get("schema", {}).get("name") != "cbl.release_safety_audit":
        fail("Release safety audit report has wrong schema name.")

    if not result.ok:
        formatted = json.dumps(payload.get("issues", []), indent=2, sort_keys=True)
        fail(f"Release safety audit failed:\n{formatted}")

    print("PASS: Phase 22 release safety and audit persistence passed.")
    print(f"Stable audit report: {stable_path}")
    print(f"Latest audit report: {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
