from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitInfo:
    available: bool
    is_repo: bool
    branch: str | None
    head: str | None
    is_dirty: bool
    staged_count: int
    unstaged_count: int
    untracked_count: int
    warnings: tuple[str, ...] = ()


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None


def is_git_available(cwd: str | Path) -> bool:
    result = _run_git(["--version"], Path(cwd))
    return result is not None and result.returncode == 0


def collect_git_info(repo_root: str | Path) -> GitInfo:
    root = Path(repo_root)

    version = _run_git(["--version"], root)
    if version is None or version.returncode != 0:
        return GitInfo(
            available=False,
            is_repo=False,
            branch=None,
            head=None,
            is_dirty=False,
            staged_count=0,
            unstaged_count=0,
            untracked_count=0,
            warnings=("Git executable is unavailable; CBL is degraded to filesystem mode.",),
        )

    inside = _run_git(["rev-parse", "--is-inside-work-tree"], root)
    if inside is None or inside.returncode != 0 or inside.stdout.strip().lower() != "true":
        return GitInfo(
            available=True,
            is_repo=False,
            branch=None,
            head=None,
            is_dirty=False,
            staged_count=0,
            unstaged_count=0,
            untracked_count=0,
            warnings=("Repository root is not a valid Git work tree; Git state is unavailable.",),
        )

    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    head_result = _run_git(["rev-parse", "HEAD"], root)
    status_result = _run_git(["status", "--porcelain=v1"], root)

    branch = branch_result.stdout.strip() if branch_result and branch_result.returncode == 0 else None
    head = head_result.stdout.strip() if head_result and head_result.returncode == 0 else None

    staged_count = 0
    unstaged_count = 0
    untracked_count = 0
    status_lines: list[str] = []

    if status_result and status_result.returncode == 0:
        status_lines = [line for line in status_result.stdout.splitlines() if line]
        for line in status_lines:
            if line.startswith("??"):
                untracked_count += 1
                continue
            if len(line) >= 2:
                index_status = line[0]
                worktree_status = line[1]
                if index_status != " ":
                    staged_count += 1
                if worktree_status != " ":
                    unstaged_count += 1

    return GitInfo(
        available=True,
        is_repo=True,
        branch=branch,
        head=head,
        is_dirty=bool(status_lines),
        staged_count=staged_count,
        unstaged_count=unstaged_count,
        untracked_count=untracked_count,
        warnings=(),
    )
