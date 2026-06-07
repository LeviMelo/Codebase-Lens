from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/git/diff.py": [
        "ChangedHunk",
        "ChangedFile",
        "ChangedFileSet",
        "collect_changed_files",
    ],
    "src/codebase_lens/analyzers/changed_symbols.py": [
        "ChangedSymbolRecord",
        "ChangedSymbolResult",
        "map_changed_symbols",
        "changed_symbol_result_payload",
    ],
    "src/codebase_lens/reports/json.py": [
        "changed_files_payload",
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


def run_cbl(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def make_changed_repo(base: Path) -> Path:
    repo = base / "changed_repo"
    repo.mkdir()

    init = run_git(repo, "init")
    if init.returncode != 0:
        fail(init.stderr)

    run_git(repo, "config", "user.email", "cbl@example.invalid")
    run_git(repo, "config", "user.name", "CBL Test")

    (repo / ".gitignore").write_text(".codecontext/\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'changed-repo'\n", encoding="utf-8")
    (repo / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    return 1",
                "",
                "def beta():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    run_git(repo, "add", ".")
    commit = run_git(repo, "commit", "-m", "initial")
    if commit.returncode != 0:
        fail(commit.stdout + commit.stderr)

    (repo / "module.py").write_text(
        "\n".join(
            [
                "def alpha():",
                "    value = 10",
                "    return value",
                "",
                "def beta():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo / "new_module.py").write_text(
        "\n".join(
            [
                "def gamma():",
                "    return 3",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def main() -> int:
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    if shutil.which("git") is None:
        fail("Git executable is required for Phase 5 audit.")

    with tempfile.TemporaryDirectory() as tmp:
        repo = make_changed_repo(Path(tmp))

        diff_result = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
        if diff_result.returncode != 0:
            fail(f"cbl diff failed:\nSTDOUT:\n{diff_result.stdout}\nSTDERR:\n{diff_result.stderr}")
        if "CBL diff: OK" not in diff_result.stdout:
            fail("cbl diff did not report success.")
        if "C:\\Users\\" in diff_result.stdout:
            fail("cbl diff leaked an absolute Windows user path.")

        diff_path = repo / ".codecontext" / "latest" / "diff.json"
        manifest_path = repo / ".codecontext" / "latest" / "manifest.json"
        if not diff_path.is_file():
            fail("cbl diff did not write diff.json.")

        diff_payload = json.loads(diff_path.read_text(encoding="utf-8"))
        changed_paths = {record["path"] for record in diff_payload["changed_files"]}
        if not {"module.py", "new_module.py"} <= changed_paths:
            fail(f"diff.json missing expected changed paths: {sorted({'module.py', 'new_module.py'} - changed_paths)}")
        if diff_payload["counts"]["changed_files_count"] < 2:
            fail("diff.json changed file count is invalid.")
        if diff_payload.get("changed_symbols", {}).get("counts", {}).get("total", 0) < 2:
            fail("diff --symbols did not include expected changed symbols.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "diff":
            fail("manifest command.subcommand is not diff after cbl diff.")
        if manifest["outputs"].get("diff_json") != ".codecontext/latest/diff.json":
            fail("manifest does not declare diff_json.")

        changed_result = run_cbl("changed", "--repo", str(repo), "--no-archive")
        if changed_result.returncode != 0:
            fail(f"cbl changed failed:\nSTDOUT:\n{changed_result.stdout}\nSTDERR:\n{changed_result.stderr}")
        if "CBL changed: OK" not in changed_result.stdout:
            fail("cbl changed did not report success.")
        if "C:\\Users\\" in changed_result.stdout:
            fail("cbl changed leaked an absolute Windows user path.")

        changed_files_path = repo / ".codecontext" / "latest" / "changed_files.json"
        changed_symbols_path = repo / ".codecontext" / "latest" / "changed_symbols.json"

        if not changed_files_path.is_file():
            fail("cbl changed did not write changed_files.json.")
        if not changed_symbols_path.is_file():
            fail("cbl changed did not write changed_symbols.json.")

        changed_files = json.loads(changed_files_path.read_text(encoding="utf-8"))
        changed_symbols = json.loads(changed_symbols_path.read_text(encoding="utf-8"))

        changed_file_paths = {record["path"] for record in changed_files["changed_files"]}
        if not {"module.py", "new_module.py"} <= changed_file_paths:
            fail("changed_files.json missing modified or untracked Python file.")

        symbol_names = {record["qualified_name"] for record in changed_symbols["changed_symbols"]}
        if "alpha" not in symbol_names:
            fail("changed_symbols.json missing modified function alpha.")
        if "gamma" not in symbol_names:
            fail("changed_symbols.json missing untracked function gamma.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "changed":
            fail("manifest command.subcommand is not changed after cbl changed.")
        if manifest["outputs"].get("changed_files_json") != ".codecontext/latest/changed_files.json":
            fail("manifest does not declare changed_files_json.")
        if manifest["outputs"].get("changed_symbols_json") != ".codecontext/latest/changed_symbols.json":
            fail("manifest does not declare changed_symbols_json.")

    print("PASS: Phase 5 diff/changed audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
