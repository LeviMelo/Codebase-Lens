from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitFileSets:
    tracked: tuple[str, ...]
    untracked_nonignored: tuple[str, ...]
    ignored: tuple[str, ...]
    available: bool
    is_repo: bool
    warning: str | None = None


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


def _split_nul(stdout: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.replace("\\", "/")
            for item in stdout.split("\0")
            if item.strip()
        )
    )


def _git_lines(repo_root: Path, args: list[str]) -> tuple[str, ...]:
    result = _run_git(repo_root, args)
    if result is None or result.returncode != 0:
        return ()
    if "-z" in args:
        return _split_nul(result.stdout)
    return tuple(sorted(line.replace("\\", "/") for line in result.stdout.splitlines() if line.strip()))


def is_git_worktree(repo_root: str | Path) -> bool:
    root = Path(repo_root)
    result = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    return result is not None and result.returncode == 0 and result.stdout.strip().lower() == "true"


def git_tracked_files(repo_root: str | Path) -> tuple[str, ...]:
    return _git_lines(Path(repo_root), ["ls-files", "-z"])


def git_untracked_nonignored_files(repo_root: str | Path) -> tuple[str, ...]:
    return _git_lines(Path(repo_root), ["ls-files", "--others", "--exclude-standard", "-z"])


def git_ignored_files(repo_root: str | Path) -> tuple[str, ...]:
    return _git_lines(Path(repo_root), ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"])


def collect_git_file_sets(repo_root: str | Path) -> GitFileSets:
    root = Path(repo_root)
    probe = _run_git(root, ["--version"])
    if probe is None or probe.returncode != 0:
        return GitFileSets(
            tracked=(),
            untracked_nonignored=(),
            ignored=(),
            available=False,
            is_repo=False,
            warning="Git executable is unavailable; using filesystem discovery.",
        )

    if not is_git_worktree(root):
        return GitFileSets(
            tracked=(),
            untracked_nonignored=(),
            ignored=(),
            available=True,
            is_repo=False,
            warning="Directory is not a Git work tree; using filesystem discovery.",
        )

    return GitFileSets(
        tracked=git_tracked_files(root),
        untracked_nonignored=git_untracked_nonignored_files(root),
        ignored=git_ignored_files(root),
        available=True,
        is_repo=True,
        warning=None,
    )
