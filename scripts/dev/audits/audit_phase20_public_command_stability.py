from __future__ import annotations

import ast
import json
import os
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
        "src/codebase_lens/cli.py",
        "src/codebase_lens/contracts/command_surface.py",
        "src/codebase_lens/core/audit_artifacts.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.command_surface import (
        audit_command_surface,
        command_surface_result_payload,
    )
    from codebase_lens.core.audit_artifacts import write_audit_report_pair

    result = audit_command_surface(include_help=True, include_external_pack=True)
    payload = command_surface_result_payload(result)
    stable_path, latest_path = write_audit_report_pair(ROOT, "command_surface_audit", payload)

    if not stable_path.is_file() or not latest_path.is_file():
        fail("command_surface_audit.json was not written to stable and latest locations.")

    if payload.get("schema", {}).get("name") != "cbl.command_surface_audit":
        fail("command surface audit report has wrong schema name.")

    if not result.ok:
        formatted = json.dumps(payload.get("issues", []), indent=2, sort_keys=True)
        fail(f"Public command stability gate failed:\n{formatted}")

    public_commands = set(payload.get("public_commands", []))
    parser_subcommands = set(payload.get("parser_subcommands", []))
    if public_commands != parser_subcommands:
        fail(f"Public command mismatch: public={sorted(public_commands)} parser={sorted(parser_subcommands)}")

    if len(public_commands) < 10:
        fail(f"Unexpectedly small public command surface: {sorted(public_commands)}")

    external = payload.get("external_repo", {})
    if not external.get("manifest_exists"):
        fail("External --repo pack did not write manifest.json.")
    if not external.get("projection_exists"):
        fail("External --repo pack did not write handoff_projection.json.")
    if external.get("missing_core_artifacts"):
        fail(f"External --repo pack missed core artifacts: {external['missing_core_artifacts']}")
    if external.get("scanned_codecontext_paths"):
        fail(f"External --repo pack recursively scanned .codecontext: {external['scanned_codecontext_paths']}")

    print("PASS: Phase 20 public command stability audit passed.")
    print(f"Stable audit report: {stable_path}")
    print(f"Latest audit report: {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
