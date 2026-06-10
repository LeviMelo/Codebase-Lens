from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from .constants import (
    CODE_SOURCE_EXTENSIONS,
    HARD_EXCLUDED_DIR_NAMES,
    HARD_EXCLUDED_FILE_PATTERNS,
    STRONG_PROJECT_MARKERS,
)
from .errors import PathSafetyError, RootDetectionError


@dataclass(frozen=True)
class RootInfo:
    root: Path
    method: str
    is_git_repo: bool
    git_root: Path | None
    warnings: tuple[str, ...] = ()


def _run_git_show_toplevel(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None

    value = result.stdout.strip()
    if not value:
        return None

    candidate = Path(value).resolve()
    if candidate.is_dir():
        return candidate
    return None


def _walk_upwards(start: Path) -> list[Path]:
    start = start.resolve()
    if start.is_file():
        start = start.parent
    return [start, *start.parents]


def detect_repository_root(
    start: str | Path | None = None,
    explicit_repo: str | Path | None = None,
    *,
    allow_no_root: bool = False,
) -> RootInfo:
    """Detect the repository root according to the CBL precedence contract."""

    if explicit_repo is not None:
        root = Path(explicit_repo).expanduser().resolve()
        if not root.exists():
            raise RootDetectionError(f"Repository override does not exist: {explicit_repo}")
        if not root.is_dir():
            raise RootDetectionError(f"Repository override is not a directory: {explicit_repo}")

        git_root = _run_git_show_toplevel(root)
        is_exact_git_root = git_root is not None and git_root == root
        is_dot_git_root = (root / ".git").exists()

        warnings: list[str] = []
        if git_root is not None and git_root != root:
            warnings.append(
                "Explicit --repo is inside a larger Git work tree; CBL is honoring the explicit directory as analysis root."
            )

        return RootInfo(
            root=root,
            method="explicit",
            is_git_repo=is_exact_git_root or is_dot_git_root,
            git_root=root if is_exact_git_root or is_dot_git_root else None,
            warnings=tuple(warnings),
        )

    start_path = Path.cwd() if start is None else Path(start).expanduser()
    start_path = start_path.resolve()
    if start_path.is_file():
        start_path = start_path.parent

    git_root = _run_git_show_toplevel(start_path)
    if git_root is not None:
        return RootInfo(root=git_root, method="git", is_git_repo=True, git_root=git_root)

    for candidate in _walk_upwards(start_path):
        if (candidate / ".git").exists():
            return RootInfo(root=candidate, method="dot-git", is_git_repo=True, git_root=candidate)

    for candidate in _walk_upwards(start_path):
        for marker in STRONG_PROJECT_MARKERS:
            if (candidate / marker).exists():
                return RootInfo(root=candidate, method=f"marker:{marker}", is_git_repo=False, git_root=None)

    if allow_no_root:
        return RootInfo(
            root=start_path,
            method="allow-no-root",
            is_git_repo=False,
            git_root=None,
            warnings=("No Git or project marker was found; using current directory because --allow-no-root was supplied.",),
        )

    raise RootDetectionError(
        "Could not detect repository root. Run from inside a Git/project directory or pass --repo."
    )


def to_posix_relative(repo_root: Path, path: Path) -> str:
    resolved_root = repo_root.resolve()
    resolved_path = path.resolve(strict=False)
    try:
        rel = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise PathSafetyError(f"Path is outside repository root: {path}") from exc
    return rel.as_posix()


def is_network_path(raw_path: str) -> bool:
    return raw_path.startswith("\\\\") or raw_path.startswith("//")


def has_windows_drive_prefix(raw_path: str) -> bool:
    return re.match(r"^[A-Za-z]:[\\/]", raw_path) is not None


SOURCE_ROOT_DIR_NAMES = frozenset(
    {
        "src",
        "lib",
        "app",
        "apps",
        "packages",
        "pkg",
        "tests",
        "test",
        "scripts",
        "script",
    }
)

# These directory names are often generated artifacts at repository root,
# but they are also common legitimate package/module names. A file such as
# src/pegasus/output/bundle.py is source code and must not be hard-excluded.
SOURCE_PROTECTED_ARTIFACT_DIR_NAMES = frozenset(
    {
        "cache",
        "data",
        "external",
        "log",
        "logs",
        "output",
        "outputs",
        "processed",
        "raw",
        "run",
        "runs",
        "temp",
        "tmp",
        "artifacts",
    }
)


def _is_inside_source_tree(parts: tuple[str, ...], index: int) -> bool:
    return any(part in SOURCE_ROOT_DIR_NAMES for part in parts[:index])


def _has_source_code_suffix(normalized: str) -> bool:
    suffix = PurePosixPath(normalized).suffix.lower()
    return suffix in CODE_SOURCE_EXTENSIONS


def _hard_excluded_dir_applies(parts: tuple[str, ...], index: int, normalized: str) -> bool:
    part = parts[index]
    if part not in HARD_EXCLUDED_DIR_NAMES:
        return False

    if (
        part in SOURCE_PROTECTED_ARTIFACT_DIR_NAMES
        and _is_inside_source_tree(parts, index)
        and _has_source_code_suffix(normalized)
    ):
        return False

    return True


def is_hard_excluded_relative(relative_posix_path: str) -> bool:
    normalized = relative_posix_path.replace("\\", "/").strip("/")
    if not normalized:
        return False

    parts = tuple(part for part in normalized.split("/") if part)
    if not parts:
        return False

    if any(part in HARD_EXCLUDED_DIR_NAMES for part in parts):
        return True

    name = parts[-1]
    safe_dotenv_examples = {
        ".env.example",
        ".env.sample",
        ".env.template",
        ".env.defaults",
    }
    if name in safe_dotenv_examples:
        return False

    pure = PurePosixPath(normalized)
    for pattern in HARD_EXCLUDED_FILE_PATTERNS:
        if fnmatch(name, pattern) or pure.match(pattern):
            return True

    top_level_generated_roots = {
        ".cache",
        "cache",
        "logs",
        "log",
        "tmp",
        "temp",
        "outputs",
        "output",
        "runs",
        "run",
        "data",
        "raw",
        "processed",
        "external",
        "artifacts",
        ".checkpoints",
    }
    if parts[0] in top_level_generated_roots:
        return True

    return False

def resolve_user_path(
    repo_root: str | Path,
    user_path: str | Path,
    *,
    allow_absolute: bool = False,
    allow_hard_excluded: bool = False,
) -> Path:
    """Resolve a user-supplied path with containment and hard-exclusion checks."""

    root = Path(repo_root).resolve()
    raw = str(user_path)

    if is_network_path(raw):
        raise PathSafetyError("Network paths are not allowed by default.")

    candidate = Path(user_path).expanduser()

    if candidate.is_absolute() or has_windows_drive_prefix(raw):
        if not allow_absolute:
            raise PathSafetyError("Absolute user-supplied paths are not allowed by default.")
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (root / candidate).resolve(strict=False)

    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise PathSafetyError(f"Path resolves outside repository root: {user_path}") from exc

    relative_posix = relative.as_posix()
    if not allow_hard_excluded and is_hard_excluded_relative(relative_posix):
        raise PathSafetyError(f"Path is hard-excluded by default: {relative_posix}")

    return resolved


def display_path(repo_root: Path, path: Path, *, absolute: bool = False) -> str:
    if absolute:
        return str(path.resolve())
    try:
        return to_posix_relative(repo_root, path)
    except PathSafetyError:
        return path.name


def gitignore_mentions_codecontext(repo_root: Path) -> bool:
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        return False

    try:
        text = gitignore.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = gitignore.read_text(encoding="utf-8", errors="replace")

    lines = [line.strip() for line in text.splitlines()]
    return ".codecontext/" in lines or ".codecontext" in lines
