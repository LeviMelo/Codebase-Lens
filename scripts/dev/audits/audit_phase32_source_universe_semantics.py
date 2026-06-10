
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def env() -> dict[str, str]:
    root = repo_root()
    payload = os.environ.copy()
    current = payload.get("PYTHONPATH", "")
    src = str(root / "src")
    payload["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return payload


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env(), text=True, capture_output=True, check=False, timeout=60)


def file_headings(markdown: str) -> set[str]:
    return set(re.findall(r"^### FILE: `([^`]+)`", markdown, flags=re.MULTILINE))


def make_target_repo(base: Path) -> Path:
    if shutil.which("git") is None:
        raise SystemExit("git is required for this audit")

    target = base / "target"
    target.mkdir()
    git = run(["git", "init"], cwd=target)
    if git.returncode != 0:
        raise SystemExit(git.stdout + git.stderr)

    write(target / ".gitignore", ".codecontext/\n")
    write(target / "pyproject.toml", "[project]\nname = 'target'\nversion = '0.0.0'\n")
    write(target / "src" / "pkg" / "__init__.py", "")
    write(target / "src" / "pkg" / "output" / "bundle.py", "def bundle():\n    return 1\n")
    write(target / "src" / "pkg" / "r_scripts" / "fetch.R", "cat('ok')\n")
    write(target / "config" / "intents" / "smoke.json", json.dumps({"intent": "smoke"}))
    write(target / "config" / "registries" / "seed.jsonl", '{"id":"seed"}\n')
    write(target / "output" / "generated.py", "def generated():\n    return 0\n")
    write(target / "data" / "script.py", "def data_script():\n    return 0\n")

    added = run(["git", "add", "."], cwd=target)
    if added.returncode != 0:
        raise SystemExit(added.stdout + added.stderr)
    return target


def assert_contains(headings: set[str], path: str) -> None:
    if path not in headings:
        raise AssertionError(f"Expected dumped file heading is absent: {path}")


def assert_absent(headings: set[str], path: str) -> None:
    if path in headings:
        raise AssertionError(f"Unexpected dumped file heading is present: {path}")


def main() -> int:
    root = repo_root()
    with tempfile.TemporaryDirectory(prefix="cbl_phase32_source_universe_") as tmp:
        target = make_target_repo(Path(tmp))

        result = run(
            [
                sys.executable,
                "-m",
                "codebase_lens",
                "dump",
                "--repo",
                str(target),
                "--no-archive",
            ],
            cwd=root,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode

        dump_path = target / ".codecontext" / "latest" / "codebase_dump.md"
        index_path = target / ".codecontext" / "latest" / "codebase_dump_index.json"

        if not dump_path.is_file():
            raise AssertionError(f"Missing dump markdown: {dump_path}")
        if not index_path.is_file():
            raise AssertionError(f"Missing dump index: {index_path}")

        headings = file_headings(dump_path.read_text(encoding="utf-8"))
        assert_contains(headings, "src/pkg/output/bundle.py")
        assert_contains(headings, "src/pkg/r_scripts/fetch.R")
        assert_contains(headings, "config/intents/smoke.json")
        assert_contains(headings, "config/registries/seed.jsonl")
        assert_absent(headings, "output/generated.py")
        assert_absent(headings, "data/script.py")

        payload = json.loads(index_path.read_text(encoding="utf-8"))
        indexed = {item["path"] for item in payload["files"]}
        if indexed != headings:
            raise AssertionError("Dump index file list does not match markdown FILE headings.")

        print("PASS: Phase 32 source universe semantics audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
