from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/reports/snapshot.py": [
        "SnapshotBundleResult",
        "write_snapshot_bundle",
    ],
    "src/codebase_lens/reports/handoff.py": [
        "HandoffPackResult",
        "write_handoff_pack",
    ],
    "src/codebase_lens/cli.py": [
        "_run_snapshot",
        "_run_pack",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


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


def main() -> int:
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    snapshot = run_cbl("snapshot", "--no-archive")
    if snapshot.returncode != 0:
        fail(f"cbl snapshot failed:\nSTDOUT:\n{snapshot.stdout}\nSTDERR:\n{snapshot.stderr}")
    if "CBL snapshot: OK" not in snapshot.stdout:
        fail("cbl snapshot did not report success.")
    if "C:\\Users\\" in snapshot.stdout:
        fail("cbl snapshot leaked an absolute Windows user path.")

    latest = ROOT / ".codecontext" / "latest"
    snapshot_required = {
        "file_inventory.json",
        "repo_tree.txt",
        "symbols.json",
        "imports.json",
        "commands.json",
        "routes.json",
        "tests_inventory.json",
        "snapshot_index.json",
        "symbol_index.json",
        "import_graph.json",
        "cli_inventory.json",
        "route_inventory.json",
        "test_inventory.json",
        "omissions.json",
        "budget_report.json",
        "manifest.json",
    }
    existing = {item.name for item in latest.iterdir()}
    missing_snapshot = snapshot_required - existing
    if missing_snapshot:
        fail(f"snapshot missing outputs: {sorted(missing_snapshot)}")

    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))
    if snapshot_index["counts"]["included_files"] < 1:
        fail("snapshot_index included_files count is invalid.")
    if snapshot_index["counts"]["python_files_analyzed"] < 1:
        fail("snapshot_index python_files_analyzed count is invalid.")

    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    if manifest["command"]["subcommand"] != "snapshot":
        fail("manifest command.subcommand is not snapshot.")
    if manifest["repo"]["root"] != "<redacted>":
        fail("manifest repo.root is not redacted.")
    if manifest["outputs"].get("snapshot_index_json") != ".codecontext/latest/snapshot_index.json":
        fail("manifest does not declare snapshot_index_json.")

    pack = run_cbl("pack", "--changed", "--issue", "phase 8 audit handoff", "--no-archive")
    if pack.returncode != 0:
        fail(f"cbl pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")
    if "CBL pack: OK" not in pack.stdout:
        fail("cbl pack did not report success.")
    if "C:\\Users\\" in pack.stdout:
        fail("cbl pack leaked an absolute Windows user path.")

    pack_required = {
        "ai_handoff.md",
        "pack_index.json",
        "snapshot_index.json",
        "omissions.json",
        "budget_report.json",
        "manifest.json",
    }
    existing = {item.name for item in latest.iterdir()}
    missing_pack = pack_required - existing
    if missing_pack:
        fail(f"pack missing outputs: {sorted(missing_pack)}")

    handoff = (latest / "ai_handoff.md").read_text(encoding="utf-8")
    if "# CBL AI Handoff Pack" not in handoff:
        fail("ai_handoff.md missing title.")
    if "phase 8 audit handoff" not in handoff:
        fail("ai_handoff.md missing issue context.")
    if "C:\\Users\\" in handoff:
        fail("ai_handoff.md leaked an absolute Windows user path.")

    pack_index = json.loads((latest / "pack_index.json").read_text(encoding="utf-8"))
    if pack_index["outputs"].get("ai_handoff_md") != ".codecontext/latest/ai_handoff.md":
        fail("pack_index does not declare ai_handoff_md.")
    if pack_index["scope"] != "changed":
        fail("pack_index scope should be changed for --changed pack.")

    pack_manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    if pack_manifest["command"]["subcommand"] != "pack":
        fail("manifest command.subcommand is not pack.")
    if pack_manifest["outputs"].get("pack_index_json") != ".codecontext/latest/pack_index.json":
        fail("manifest does not declare pack_index_json.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed after snapshot/pack slice:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 8 snapshot/pack audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
