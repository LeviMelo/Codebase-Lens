from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from codebase_lens.contracts.command_surface import (
    audit_command_surface,
    command_surface_result_payload,
    inspect_public_command_surface,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run_cbl(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_public_commands_match_argparse_subcommands() -> None:
    public_commands, parser_subcommands, issues = inspect_public_command_surface()

    assert not issues
    assert public_commands
    assert set(public_commands) == set(parser_subcommands)
    assert "pack" in public_commands
    assert "graph" in public_commands
    assert "contract" in public_commands


def test_command_surface_help_and_external_repo_pack_are_stable() -> None:
    result = audit_command_surface(include_help=True, include_external_pack=True)
    payload = command_surface_result_payload(result)

    assert result.ok, json.dumps(payload["issues"], indent=2, sort_keys=True)
    assert payload["schema"]["name"] == "cbl.command_surface_audit"
    assert set(payload["public_commands"]) == set(payload["parser_subcommands"])

    external = payload["external_repo"]
    assert external["manifest_exists"]
    assert external["projection_exists"]
    assert external["evidence_graph_exists"]
    assert not external["missing_core_artifacts"]
    assert not external["scanned_codecontext_paths"]
    assert "src/demo_pkg/" in external["projection_source_prefixes"]


def test_command_surface_contract_module_does_not_import_cli_layer() -> None:
    source = (ROOT / "src" / "codebase_lens" / "contracts" / "command_surface.py").read_text(encoding="utf-8")

    assert "from codebase_lens import cli" not in source
    assert "import codebase_lens.cli" not in source
    assert "codebase_lens.cli" not in source

    contract = run_cbl("contract", "--no-archive")
    assert contract.returncode == 0, contract.stdout + contract.stderr
