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
    "src/codebase_lens/git/status.py": [
        "GitFileSets",
        "collect_git_file_sets",
        "git_tracked_files",
        "git_untracked_nonignored_files",
        "git_ignored_files",
    ],
    "src/codebase_lens/scanners/universe.py": [
        "FileUniverseResult",
        "discover_file_universe",
    ],
    "src/codebase_lens/scanners/inventory.py": [
        "file_universe_to_inventory",
        "write_file_inventory",
    ],
    "src/codebase_lens/scanners/tree.py": [
        "render_tree_report",
        "write_tree_report",
    ],
    "src/codebase_lens/analyzers/excerpts.py": [
        "FileExcerpt",
        "build_file_excerpt",
        "render_excerpt_markdown",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
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

    tree = run_cbl("tree", "--no-archive", "--depth", "4", "--show-skipped")
    if tree.returncode != 0:
        fail(f"cbl tree failed:\nSTDOUT:\n{tree.stdout}\nSTDERR:\n{tree.stderr}")
    if "CBL tree: OK" not in tree.stdout:
        fail("cbl tree did not report success.")
    if "C:\\Users\\" in tree.stdout:
        fail("cbl tree leaked an absolute Windows user path.")

    tree_path = ROOT / ".codecontext" / "latest" / "repo_tree.txt"
    inventory_path = ROOT / ".codecontext" / "latest" / "file_inventory.json"
    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"

    for path in (tree_path, inventory_path, manifest_path):
        if not path.is_file():
            fail(f"Missing expected report: {path}")

    tree_text = tree_path.read_text(encoding="utf-8")
    if ".codecontext/" in tree_text:
        fail("repo_tree.txt includes .codecontext/, which must be hard-excluded.")
    if "src/" not in tree_text:
        fail("repo_tree.txt does not include src/.")

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    paths = [item["path"] for item in inventory["files"]]
    if "src/codebase_lens/cli.py" not in paths:
        fail("file_inventory.json does not include src/codebase_lens/cli.py.")
    if any(path.startswith(".codecontext/") for path in paths):
        fail("file_inventory.json includes .codecontext/.")
    if any("C:\\Users\\" in item.get("absolute_path", "") for item in inventory["files"]):
        fail("file_inventory.json leaked absolute Windows user paths.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["command"]["subcommand"] != "tree":
        fail("manifest command.subcommand is not tree after cbl tree.")
    if manifest["outputs"].get("file_inventory_json") != ".codecontext/latest/file_inventory.json":
        fail("manifest does not declare file_inventory_json output.")
    if manifest["file_universe"].get("included_count", 0) < 1:
        fail("manifest file_universe included_count is invalid.")

    excerpt = run_cbl("file", "README.md", "--lines", "1:5", "--no-archive")
    if excerpt.returncode != 0:
        fail(f"cbl file failed:\nSTDOUT:\n{excerpt.stdout}\nSTDERR:\n{excerpt.stderr}")
    if "Evidence: README.md:L1-L5" not in excerpt.stdout:
        fail("cbl file did not emit expected evidence line.")
    if "0001:" not in excerpt.stdout:
        fail("cbl file did not emit line-numbered content.")
    if "C:\\Users\\" in excerpt.stdout:
        fail("cbl file leaked an absolute Windows user path.")

    excerpt_path = ROOT / ".codecontext" / "latest" / "file_excerpt.md"
    if not excerpt_path.is_file():
        fail("cbl file did not write .codecontext/latest/file_excerpt.md.")

    blocked = run_cbl("file", ".env", "--no-archive")
    if blocked.returncode != 4:
        fail("cbl file .env should fail with path safety exit code 4.")

    print("PASS: Phase 2 file-universe audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
