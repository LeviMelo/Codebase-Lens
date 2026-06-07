from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/git/diff.py": r'''
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.paths import is_hard_excluded_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class ChangedHunk:
    path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    heading: str | None


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    origin: str
    additions: int | None
    deletions: int | None
    is_binary: bool
    old_path: str | None
    hunks: tuple[ChangedHunk, ...]


@dataclass(frozen=True)
class ChangedFileSet:
    repo_root: Path
    changed_files: tuple[ChangedFile, ...]
    counts: dict[str, int]
    warnings: tuple[str, ...]


HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<heading>.*)$")


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None


def _is_git_repo(repo_root: Path) -> bool:
    result = _run_git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    return result is not None and result.returncode == 0 and result.stdout.strip().lower() == "true"


def _parse_name_status(stdout: str) -> dict[str, tuple[str, str | None]]:
    parsed: dict[str, tuple[str, str | None]] = {}

    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status_token = parts[0]
        status = status_token[0]

        if status == "R" and len(parts) >= 3:
            old_path = parts[1].replace("\\", "/")
            path = parts[2].replace("\\", "/")
            parsed[path] = ("R", old_path)
        elif len(parts) >= 2:
            path = parts[1].replace("\\", "/")
            parsed[path] = (status, None)

    return parsed


def _parse_numstat(stdout: str) -> dict[str, tuple[int | None, int | None, bool]]:
    parsed: dict[str, tuple[int | None, int | None, bool]] = {}

    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue

        raw_additions, raw_deletions, raw_path = parts[0], parts[1], parts[-1]
        path = raw_path.replace("\\", "/")
        is_binary = raw_additions == "-" or raw_deletions == "-"

        additions = None if is_binary else int(raw_additions)
        deletions = None if is_binary else int(raw_deletions)
        parsed[path] = (additions, deletions, is_binary)

    return parsed


def _parse_hunks(stdout: str) -> dict[str, list[ChangedHunk]]:
    hunks_by_path: dict[str, list[ChangedHunk]] = {}
    current_path: str | None = None

    for line in stdout.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[len("+++ b/") :].replace("\\", "/")
            hunks_by_path.setdefault(current_path, [])
            continue

        match = HUNK_RE.match(line)
        if match is None or current_path is None:
            continue

        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        heading = match.group("heading").strip() or None

        hunks_by_path[current_path].append(
            ChangedHunk(
                path=current_path,
                old_start=int(match.group("old_start")),
                old_count=old_count,
                new_start=int(match.group("new_start")),
                new_count=new_count,
                heading=heading,
            )
        )

    return hunks_by_path


def _collect_diff_origin(repo_root: Path, *, origin: str, diff_prefix: list[str]) -> list[ChangedFile]:
    name_status_result = _run_git(repo_root, [*diff_prefix, "--name-status", "--find-renames", "--"])
    numstat_result = _run_git(repo_root, [*diff_prefix, "--numstat", "--find-renames", "--"])
    hunk_result = _run_git(repo_root, [*diff_prefix, "--unified=0", "--"])

    if name_status_result is None or name_status_result.returncode != 0:
        return []

    name_status = _parse_name_status(name_status_result.stdout)
    numstat = _parse_numstat(numstat_result.stdout if numstat_result and numstat_result.returncode == 0 else "")
    hunks_by_path = _parse_hunks(hunk_result.stdout if hunk_result and hunk_result.returncode == 0 else "")

    files: list[ChangedFile] = []
    for path, (status, old_path) in sorted(name_status.items()):
        if is_hard_excluded_relative(path):
            continue

        additions, deletions, is_binary = numstat.get(path, (0, 0, False))
        files.append(
            ChangedFile(
                path=path,
                status=status,
                origin=origin,
                additions=additions,
                deletions=deletions,
                is_binary=is_binary,
                old_path=old_path,
                hunks=tuple(hunks_by_path.get(path, [])),
            )
        )

    return files


def _collect_untracked(repo_root: Path) -> list[ChangedFile]:
    result = _run_git(repo_root, ["ls-files", "--others", "--exclude-standard"])
    if result is None or result.returncode != 0:
        return []

    files: list[ChangedFile] = []
    for raw_path in sorted(line.strip() for line in result.stdout.splitlines() if line.strip()):
        path = raw_path.replace("\\", "/")
        if is_hard_excluded_relative(path):
            continue

        target = repo_root / path
        if not target.is_file():
            continue

        read_result = read_text_with_policy(target)
        is_binary = read_result.is_binary or read_result.skipped_reason == "binary_skipped"

        if read_result.text is not None:
            line_count = max(1, len(read_result.text.splitlines()))
            additions: int | None = line_count
            hunks = (
                ChangedHunk(
                    path=path,
                    old_start=0,
                    old_count=0,
                    new_start=1,
                    new_count=line_count,
                    heading="untracked file",
                ),
            )
        else:
            additions = None if is_binary else 0
            hunks = ()

        files.append(
            ChangedFile(
                path=path,
                status="A",
                origin="untracked",
                additions=additions,
                deletions=0 if additions is not None else None,
                is_binary=is_binary,
                old_path=None,
                hunks=hunks,
            )
        )

    return files


def _merge_changed_files(files: list[ChangedFile]) -> tuple[ChangedFile, ...]:
    merged: dict[str, ChangedFile] = {}

    for item in files:
        existing = merged.get(item.path)
        if existing is None:
            merged[item.path] = item
            continue

        origins = sorted(set(existing.origin.split("+")) | set(item.origin.split("+")))
        additions = None if existing.additions is None or item.additions is None else existing.additions + item.additions
        deletions = None if existing.deletions is None or item.deletions is None else existing.deletions + item.deletions

        merged[item.path] = ChangedFile(
            path=item.path,
            status=item.status if item.status != existing.status else existing.status,
            origin="+".join(origins),
            additions=additions,
            deletions=deletions,
            is_binary=existing.is_binary or item.is_binary,
            old_path=existing.old_path or item.old_path,
            hunks=tuple([*existing.hunks, *item.hunks]),
        )

    return tuple(sorted(merged.values(), key=lambda record: record.path))


def _origin_tokens(origin: str) -> set[str]:
    tokens: set[str] = set()
    for part in origin.split("+"):
        tokens.add(part)
        if part.startswith("base:"):
            tokens.add("base")
    return tokens


def _has_origin(item: ChangedFile, origin: str) -> bool:
    return origin in _origin_tokens(item.origin)


def _counts(files: tuple[ChangedFile, ...]) -> dict[str, int]:
    return {
        "changed_files_count": len(files),
        "modified_count": sum(1 for item in files if item.status == "M"),
        "added_count": sum(1 for item in files if item.status == "A"),
        "deleted_count": sum(1 for item in files if item.status == "D"),
        "renamed_count": sum(1 for item in files if item.status == "R"),
        "binary_count": sum(1 for item in files if item.is_binary),
        "staged_count": sum(1 for item in files if _has_origin(item, "staged")),
        "unstaged_count": sum(1 for item in files if _has_origin(item, "unstaged")),
        "untracked_count": sum(1 for item in files if _has_origin(item, "untracked")),
        "base_count": sum(1 for item in files if _has_origin(item, "base")),
        "hunk_count": sum(len(item.hunks) for item in files),
    }


def collect_changed_files(
    repo_root: str | Path,
    *,
    staged: bool = False,
    unstaged: bool = False,
    base: str | None = None,
    include_untracked: bool = True,
) -> ChangedFileSet:
    root = Path(repo_root).resolve()

    if not _is_git_repo(root):
        return ChangedFileSet(
            repo_root=root,
            changed_files=(),
            counts=_counts(()),
            warnings=("Changed-file analysis requires a Git work tree.",),
        )

    files: list[ChangedFile] = []
    warnings: list[str] = []

    if base:
        files.extend(_collect_diff_origin(root, origin=f"base:{base}", diff_prefix=["diff", base]))
    else:
        if staged or not unstaged:
            files.extend(_collect_diff_origin(root, origin="staged", diff_prefix=["diff", "--cached"]))

        if unstaged or not staged:
            files.extend(_collect_diff_origin(root, origin="unstaged", diff_prefix=["diff"]))

        if include_untracked and (unstaged or (not staged and not unstaged)):
            files.extend(_collect_untracked(root))

    changed = _merge_changed_files(files)

    return ChangedFileSet(
        repo_root=root,
        changed_files=changed,
        counts=_counts(changed),
        warnings=tuple(warnings),
    )
''',

    "tests/test_diff_changed_integration.py": r'''
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


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


def make_changed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "changed_repo"
    repo.mkdir()

    run_git(repo, "init")
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
    assert commit.returncode == 0, commit.stdout + commit.stderr

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


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable is not available")
def test_diff_and_changed_commands_integrate_git_hunks_symbols_reports_and_manifest(tmp_path: Path) -> None:
    repo = make_changed_repo(tmp_path)

    diff_result = run_cbl("diff", "--repo", str(repo), "--symbols", "--no-archive")
    assert diff_result.returncode == 0, diff_result.stdout + diff_result.stderr
    assert "CBL diff: OK" in diff_result.stdout
    assert "C:\\Users\\" not in diff_result.stdout

    diff_path = repo / ".codecontext" / "latest" / "diff.json"
    manifest_path = repo / ".codecontext" / "latest" / "manifest.json"
    assert diff_path.is_file()
    assert manifest_path.is_file()

    diff_payload = json.loads(diff_path.read_text(encoding="utf-8"))
    changed_paths = {record["path"] for record in diff_payload["changed_files"]}
    assert "module.py" in changed_paths
    assert "new_module.py" in changed_paths
    assert diff_payload["counts"]["changed_files_count"] >= 2
    assert diff_payload["counts"]["staged_count"] == 0
    assert diff_payload["counts"]["unstaged_count"] >= 1
    assert diff_payload["counts"]["untracked_count"] >= 1
    assert diff_payload["changed_symbols"]["counts"]["total"] >= 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "diff"
    assert manifest["outputs"]["diff_json"] == ".codecontext/latest/diff.json"

    changed_result = run_cbl("changed", "--repo", str(repo), "--no-archive")
    assert changed_result.returncode == 0, changed_result.stdout + changed_result.stderr
    assert "CBL changed: OK" in changed_result.stdout
    assert "C:\\Users\\" not in changed_result.stdout

    changed_files_path = repo / ".codecontext" / "latest" / "changed_files.json"
    changed_symbols_path = repo / ".codecontext" / "latest" / "changed_symbols.json"

    assert changed_files_path.is_file()
    assert changed_symbols_path.is_file()

    changed_files = json.loads(changed_files_path.read_text(encoding="utf-8"))
    changed_symbols = json.loads(changed_symbols_path.read_text(encoding="utf-8"))

    assert {"module.py", "new_module.py"} <= {record["path"] for record in changed_files["changed_files"]}
    assert changed_files["counts"]["staged_count"] == 0
    assert changed_files["counts"]["unstaged_count"] >= 1
    assert changed_files["counts"]["untracked_count"] >= 1

    symbol_names = {record["qualified_name"] for record in changed_symbols["changed_symbols"]}
    assert "alpha" in symbol_names
    assert "gamma" in symbol_names

    changed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert changed_manifest["command"]["subcommand"] == "changed"
    assert changed_manifest["outputs"]["changed_files_json"] == ".codecontext/latest/changed_files.json"
    assert changed_manifest["outputs"]["changed_symbols_json"] == ".codecontext/latest/changed_symbols.json"
''',

    "scripts/dev/audits/audit_phase5_diff_changed.py": r'''
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


def assert_counts_are_not_substring_based(payload: dict[str, object], context: str) -> None:
    counts = payload["counts"]
    if counts["staged_count"] != 0:
        fail(f"{context}: staged_count should be 0 for purely unstaged/untracked fixture.")
    if counts["unstaged_count"] < 1:
        fail(f"{context}: unstaged_count should be at least 1.")
    if counts["untracked_count"] < 1:
        fail(f"{context}: untracked_count should be at least 1.")


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
        assert_counts_are_not_substring_based(diff_payload, "diff.json")
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

        assert_counts_are_not_substring_based(changed_files, "changed_files.json")

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
''',
}


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative_path: str, content: str) -> None:
    target = ROOT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(normalize(content), encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    print("Repair applied: Slice 006 origin counts now distinguish staged from unstaged exactly.")
    print("Re-run diff/changed, Phase 5 audit, pytest, and git diff --check before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())