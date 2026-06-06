from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def test_tree_command_writes_tree_inventory_and_manifest() -> None:
    result = run_cbl("tree", "--no-archive", "--depth", "4", "--show-skipped")

    assert result.returncode == 0, result.stderr
    assert "CBL tree: OK" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    tree_path = ROOT / ".codecontext" / "latest" / "repo_tree.txt"
    inventory_path = ROOT / ".codecontext" / "latest" / "file_inventory.json"
    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"

    assert tree_path.is_file()
    assert inventory_path.is_file()
    assert manifest_path.is_file()

    tree_text = tree_path.read_text(encoding="utf-8")
    assert "CBL Repository Tree" in tree_text
    assert ".codecontext/" not in tree_text
    assert "src/" in tree_text

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in inventory["files"]}
    assert "src/codebase_lens/cli.py" in inventory_paths
    assert all(not path.startswith(".codecontext/") for path in inventory_paths)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "tree"
    assert manifest["outputs"]["repo_tree_txt"] == ".codecontext/latest/repo_tree.txt"
    assert manifest["file_universe"]["included_count"] >= 1
