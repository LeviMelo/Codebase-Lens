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
