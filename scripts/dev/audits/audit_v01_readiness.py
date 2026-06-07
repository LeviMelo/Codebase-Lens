from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

COMMANDS = [
    "doctor",
    "tree",
    "file",
    "symbols",
    "symbol",
    "imports",
    "cli",
    "routes",
    "tests",
    "diff",
    "changed",
    "callers",
    "contract",
    "snapshot",
    "pack",
    "clean",
]

SNAPSHOT_REQUIRED = {
    "file_inventory.json",
    "repo_tree.txt",
    "symbols.json",
    "symbol_index.json",
    "imports.json",
    "import_graph.json",
    "commands.json",
    "cli_inventory.json",
    "routes.json",
    "route_inventory.json",
    "tests_inventory.json",
    "test_inventory.json",
    "omissions.json",
    "budget_report.json",
    "snapshot_index.json",
    "manifest.json",
}

PACK_REQUIRED = {
    "ai_handoff.md",
    "pack_index.json",
    "snapshot_index.json",
    "omissions.json",
    "budget_report.json",
    "manifest.json",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


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


def assert_no_windows_path(text: str, context: str) -> None:
    if "C:\\Users\\" in text:
        fail(f"{context} leaked an absolute Windows user path.")


def main() -> int:
    help_result = run_cbl("--help")
    if help_result.returncode != 0:
        fail("cbl --help failed.")

    for command in COMMANDS:
        if command not in help_result.stdout:
            fail(f"cbl --help does not mention command: {command}")

    snapshot = run_cbl("snapshot", "--budget", "24000", "--focus", "contract", "--focus", "pack", "--no-archive")
    if snapshot.returncode != 0:
        fail(f"cbl snapshot failed:\nSTDOUT:\n{snapshot.stdout}\nSTDERR:\n{snapshot.stderr}")
    if "CBL snapshot: OK" not in snapshot.stdout:
        fail("snapshot did not report success.")
    assert_no_windows_path(snapshot.stdout, "snapshot stdout")

    latest = ROOT / ".codecontext" / "latest"
    existing = {item.name for item in latest.iterdir()}
    missing_snapshot = SNAPSHOT_REQUIRED - existing
    if missing_snapshot:
        fail(f"snapshot missing required outputs: {sorted(missing_snapshot)}")

    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))
    if snapshot_index.get("budget") != 24000:
        fail("snapshot_index did not preserve requested budget.")
    if snapshot_index.get("focus_terms") != ["contract", "pack"]:
        fail("snapshot_index did not preserve focus terms.")

    budget = json.loads((latest / "budget_report.json").read_text(encoding="utf-8"))
    if budget.get("requested_budget_tokens") != 24000:
        fail("budget_report did not preserve requested budget.")
    if budget.get("focus_terms") != ["contract", "pack"]:
        fail("budget_report did not preserve focus terms.")
    if "ranked_files" not in budget:
        fail("budget_report missing ranked_files.")

    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    if manifest["repo"]["root"] != "<redacted>":
        fail("snapshot manifest repo.root is not redacted.")
    if manifest["command"]["subcommand"] != "snapshot":
        fail("snapshot manifest subcommand is wrong.")
    if manifest["outputs"].get("symbol_index_json") != ".codecontext/latest/symbol_index.json":
        fail("snapshot manifest missing symbol_index_json alias.")
    if manifest["outputs"].get("omissions_json") != ".codecontext/latest/omissions.json":
        fail("snapshot manifest missing omissions_json.")

    pack = run_cbl(
        "pack",
        "--changed",
        "--budget",
        "12000",
        "--focus",
        "diff",
        "--issue",
        "v0.1 readiness audit",
        "--no-archive",
    )
    if pack.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")
    if "CBL pack: OK" not in pack.stdout:
        fail("pack did not report success.")
    assert_no_windows_path(pack.stdout, "pack stdout")

    existing = {item.name for item in latest.iterdir()}
    missing_pack = PACK_REQUIRED - existing
    if missing_pack:
        fail(f"pack missing required outputs: {sorted(missing_pack)}")

    handoff = (latest / "ai_handoff.md").read_text(encoding="utf-8")
    assert_no_windows_path(handoff, "ai_handoff.md")
    for marker in ["# CBL AI Handoff Pack", "## Budget and Focus", "## Omissions", "v0.1 readiness audit"]:
        if marker not in handoff:
            fail(f"ai_handoff.md missing marker: {marker}")

    pack_index = json.loads((latest / "pack_index.json").read_text(encoding="utf-8"))
    if pack_index.get("scope") != "changed":
        fail("pack_index scope is not changed.")
    if pack_index.get("budget") != 12000:
        fail("pack_index did not preserve requested budget.")
    if pack_index.get("focus_terms") != ["diff"]:
        fail("pack_index did not preserve focus terms.")
    if pack_index["outputs"].get("ai_handoff_md") != ".codecontext/latest/ai_handoff.md":
        fail("pack_index missing ai_handoff_md output.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    clean = run_cbl("clean", "--keep", "999")
    if clean.returncode != 0:
        fail(f"cbl clean failed:\nSTDOUT:\n{clean.stdout}\nSTDERR:\n{clean.stderr}")
    if "CBL clean: OK" not in clean.stdout:
        fail("clean did not report success.")
    assert_no_windows_path(clean.stdout, "clean stdout")

    print("PASS: v0.1 readiness audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
