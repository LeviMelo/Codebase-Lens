from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/core/constants.py": r'''
from __future__ import annotations

DEFAULT_BUDGET = 16000
DEFAULT_MAX_FILE_BYTES = 262144
DEFAULT_MAX_EXCERPT_BYTES = 65536
BINARY_SNIFF_BYTES = 8192

PARTIAL_IMPLEMENTATION_MESSAGE = (
    "PARTIAL IMPLEMENTATION: this command exists but is not complete in the current milestone."
)

PUBLIC_COMMANDS = (
    "doctor",
    "snapshot",
    "tree",
    "symbols",
    "imports",
    "cli",
    "routes",
    "tests",
    "diff",
    "changed",
    "file",
    "symbol",
    "callers",
    "contract",
    "pack",
    "clean",
)

EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_INVALID_ARGUMENTS = 2
EXIT_ROOT_DETECTION_FAILURE = 3
EXIT_PATH_SAFETY_VIOLATION = 4
EXIT_CONTRACT_VIOLATION = 5
EXIT_UNSAFE_OPTION_REJECTED = 6
EXIT_OUTPUT_WRITE_FAILURE = 7

STRONG_PROJECT_MARKERS = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
)

HARD_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".codecontext",
        ".venv",
        "venv",
        "env",
        "ENV",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".ipynb_checkpoints",
        "node_modules",
        "dist",
        "build",
        "site-packages",
        ".eggs",
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
)

HARD_EXCLUDED_FILE_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.crt",
    "*.cer",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_rsa.pub",
    "id_ed25519",
    "id_ed25519.pub",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.duckdb",
    "*.parquet",
    "*.feather",
    "*.arrow",
    "*.orc",
    "*.avro",
    "*.dbc",
    "*.csv.gz",
    "*.tsv.gz",
    "*.zip",
    "*.7z",
    "*.rar",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.bz2",
    "*.xz",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.bmp",
    "*.tiff",
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.xls",
    "*.xlsx",
    "*.ppt",
    "*.pptx",
    "*.mp4",
    "*.mkv",
    "*.avi",
    "*.mov",
    "*.mp3",
    "*.wav",
    "*.flac",
    "*.exe",
    "*.dll",
    "*.so",
    "*.dylib",
    "*.pyd",
    "*.bin",
    "*.model",
    "*.onnx",
    "*.pt",
    "*.pth",
    "*.ckpt",
)

DEFAULT_INCLUDED_TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyw",
        ".pyi",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".jsonl",
        ".md",
        ".rst",
        ".txt",
        ".ini",
        ".cfg",
        ".gitignore",
        ".dockerignore",
        ".ps1",
        ".psm1",
        ".bat",
        ".cmd",
        ".sh",
        ".sql",
        ".html",
        ".css",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
    }
)

TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
''',

    "src/codebase_lens/core/errors.py": r'''
from __future__ import annotations


class CblError(Exception):
    """Base class for actionable CBL errors."""


class RootDetectionError(CblError):
    """Raised when CBL cannot detect a valid repository root."""


class PathSafetyError(CblError):
    """Raised when a path escapes the repository root or violates safety policy."""


class OutputWriteError(CblError):
    """Raised when CBL cannot write its output layout."""


class RedactionError(CblError):
    """Raised when safety redaction cannot be performed reliably."""


class TextDecodeError(CblError):
    """Raised when a text file cannot be decoded under the configured policy."""
''',

    "src/codebase_lens/core/paths.py": r'''
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from .constants import HARD_EXCLUDED_DIR_NAMES, HARD_EXCLUDED_FILE_PATTERNS, STRONG_PROJECT_MARKERS
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
        if git_root is not None:
            return RootInfo(root=git_root, method="explicit-git", is_git_repo=True, git_root=git_root)

        return RootInfo(root=root, method="explicit", is_git_repo=(root / ".git").exists(), git_root=None)

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


def is_hard_excluded_relative(relative_posix_path: str) -> bool:
    normalized = relative_posix_path.strip("/").replace("\\", "/")
    if not normalized:
        return False

    parts = tuple(part for part in normalized.split("/") if part)
    for part in parts:
        if part in HARD_EXCLUDED_DIR_NAMES:
            return True

    name = parts[-1]
    pure = PurePosixPath(normalized)
    for pattern in HARD_EXCLUDED_FILE_PATTERNS:
        if fnmatch(name, pattern) or pure.match(pattern):
            return True

    if ".dvc/cache" in normalized:
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
''',

    "src/codebase_lens/core/hashing.py": r'''
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
''',

    "src/codebase_lens/core/textio.py": r'''
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import BINARY_SNIFF_BYTES, DEFAULT_MAX_FILE_BYTES, TEXT_ENCODINGS


@dataclass(frozen=True)
class TextReadResult:
    path: Path
    text: str | None
    encoding: str | None
    size_bytes: int
    is_binary: bool
    skipped_reason: str | None


def is_probably_binary(path: str | Path, *, sniff_bytes: int = BINARY_SNIFF_BYTES) -> bool:
    data = Path(path).read_bytes()[:sniff_bytes]
    return b"\x00" in data


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text_with_policy(
    path: str | Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    encodings: tuple[str, ...] = TEXT_ENCODINGS,
) -> TextReadResult:
    target = Path(path)
    size = target.stat().st_size

    if size > max_file_bytes:
        return TextReadResult(target, None, None, size, False, "large_skipped")

    if is_probably_binary(target):
        return TextReadResult(target, None, None, size, True, "binary_skipped")

    data = target.read_bytes()
    for encoding in encodings:
        try:
            return TextReadResult(
                path=target,
                text=normalize_newlines(data.decode(encoding)),
                encoding=encoding,
                size_bytes=size,
                is_binary=False,
                skipped_reason=None,
            )
        except UnicodeDecodeError:
            continue

    return TextReadResult(target, None, None, size, False, "decode_failed")
''',

    "src/codebase_lens/core/redaction.py": r'''
from __future__ import annotations

import re
from dataclasses import dataclass


SECRET_KEYS = (
    "API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "SECRET",
    "TOKEN",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "CLIENT_SECRET",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_CLIENT_SECRET",
    "DATABASE_URL",
    "POSTGRES_URL",
    "MYSQL_URL",
    "REDIS_URL",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "SLACK_TOKEN",
    "DISCORD_TOKEN",
    "JWT_SECRET",
)

PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----.*?-----END (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)

SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?P<prefix>(?P<key>["']?(?:API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|SECRET|TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|CLIENT_SECRET|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AZURE_CLIENT_SECRET|DATABASE_URL|POSTGRES_URL|MYSQL_URL|REDIS_URL|GOOGLE_APPLICATION_CREDENTIALS|GITHUB_TOKEN|GITLAB_TOKEN|SLACK_TOKEN|DISCORD_TOKEN|JWT_SECRET)["']?)\s*(?:=|:)\s*)(?P<quote>["']?)(?P<value>[^"'\s,}\]]+)(?P=quote)""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RedactionStats:
    enabled: bool
    redacted_occurrences_count: int
    patterns_hit: tuple[str, ...]


@dataclass(frozen=True)
class RedactionResult:
    text: str
    stats: RedactionStats


def _canonical_key(raw_key: str) -> str:
    key = raw_key.strip().strip('"').strip("'").upper()
    return key


def redact_text(text: str, *, enabled: bool = True) -> RedactionResult:
    if not enabled:
        return RedactionResult(text=text, stats=RedactionStats(False, 0, ()))

    occurrences = 0
    patterns_hit: set[str] = set()

    def private_key_replacer(match: re.Match[str]) -> str:
        nonlocal occurrences
        occurrences += 1
        patterns_hit.add("PRIVATE_KEY")
        return "<REDACTED_PRIVATE_KEY_BLOCK>"

    redacted = PRIVATE_KEY_BLOCK_RE.sub(private_key_replacer, text)

    def assignment_replacer(match: re.Match[str]) -> str:
        nonlocal occurrences
        value = match.group("value")
        if value in {"<REDACTED>", "<REDACTED_PRIVATE_KEY_BLOCK>"}:
            return match.group(0)

        occurrences += 1
        key = _canonical_key(match.group("key"))
        patterns_hit.add(key)
        return f"{match.group('prefix')}{match.group('quote')}<REDACTED>{match.group('quote')}"

    redacted = SECRET_ASSIGNMENT_RE.sub(assignment_replacer, redacted)

    return RedactionResult(
        text=redacted,
        stats=RedactionStats(
            enabled=True,
            redacted_occurrences_count=occurrences,
            patterns_hit=tuple(sorted(patterns_hit)),
        ),
    )


def redact_console_text(text: str) -> str:
    return redact_text(text).text
''',

    "src/codebase_lens/git/discover.py": r'''
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
''',

    "src/codebase_lens/reports/manifest.py": r'''
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codebase_lens import TOOL_NAME, __version__


@dataclass(frozen=True)
class OutputLayout:
    codecontext_dir: Path
    latest_dir: Path
    runs_dir: Path
    run_dir: Path | None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_run_stamp() -> str:
    return utc_now_iso().replace(":", "-")


def prepare_output_layout(repo_root: str | Path, out_dir: str | Path = ".codecontext", *, archive: bool = True) -> OutputLayout:
    root = Path(repo_root).resolve()
    requested = Path(out_dir)

    codecontext_dir = requested if requested.is_absolute() else root / requested
    codecontext_dir = codecontext_dir.resolve()

    latest_dir = codecontext_dir / "latest"
    runs_dir = codecontext_dir / "runs"

    latest_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    run_dir = None
    if archive:
        run_dir = runs_dir / utc_run_stamp()
        run_dir.mkdir(parents=True, exist_ok=False)

    return OutputLayout(
        codecontext_dir=codecontext_dir,
        latest_dir=latest_dir,
        runs_dir=runs_dir,
        run_dir=run_dir,
    )


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def copy_latest_to_run(layout: OutputLayout) -> None:
    if layout.run_dir is None:
        return

    for source in sorted(layout.latest_dir.iterdir()):
        target = layout.run_dir / source.name
        if source.is_file():
            shutil.copy2(source, target)


def build_manifest(
    *,
    repo_root: Path,
    repo_name: str,
    root_redacted_for_ai: bool,
    is_git_repo: bool,
    git: dict[str, Any],
    argv: list[str],
    subcommand: str,
    budget: int,
    focus: list[str],
    outputs: dict[str, str],
    redaction: dict[str, Any],
    file_universe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tool": {
            "name": TOOL_NAME,
            "command": "cbl",
            "version": __version__,
        },
        "generated_at_utc": utc_now_iso(),
        "repo": {
            "name": repo_name,
            "root": str(repo_root.resolve()),
            "root_redacted_for_ai": root_redacted_for_ai,
            "is_git_repo": is_git_repo,
            "detected_project_types": ["python"] if (repo_root / "pyproject.toml").exists() else [],
            "primary_language": "python" if (repo_root / "pyproject.toml").exists() else None,
        },
        "git": git,
        "command": {
            "argv": argv,
            "subcommand": subcommand,
            "budget": budget,
            "focus": focus,
            "changed_only": "--changed" in argv,
        },
        "file_universe": file_universe
        or {
            "tracked_included_count": 0,
            "untracked_included_count": 0,
            "ignored_count": 0,
            "hard_excluded_count": 0,
            "large_skipped_count": 0,
            "binary_skipped_count": 0,
            "decode_failed_count": 0,
        },
        "safety": {
            "redaction_enabled": redaction.get("enabled", True),
            "redacted_files_count": redaction.get("redacted_files_count", 0),
            "redacted_occurrences_count": redaction.get("redacted_occurrences_count", 0),
            "patterns_hit": redaction.get("patterns_hit", []),
            "absolute_paths_in_ai_reports": False,
        },
        "outputs": outputs,
    }


def write_manifest_bundle(layout: OutputLayout, manifest: dict[str, Any]) -> Path:
    manifest_path = layout.latest_dir / "manifest.json"
    write_json(manifest_path, manifest)

    if layout.run_dir is not None:
        write_json(layout.run_dir / "manifest.json", manifest)

    return manifest_path
''',

    "src/codebase_lens/cli.py": r'''
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from codebase_lens import __version__
from codebase_lens.core.constants import (
    DEFAULT_BUDGET,
    EXIT_GENERAL_ERROR,
    EXIT_INVALID_ARGUMENTS,
    EXIT_OUTPUT_WRITE_FAILURE,
    EXIT_ROOT_DETECTION_FAILURE,
    PUBLIC_COMMANDS,
)
from codebase_lens.core.errors import CblError, OutputWriteError, RootDetectionError
from codebase_lens.core.paths import detect_repository_root, display_path, gitignore_mentions_codecontext
from codebase_lens.core.redaction import redact_console_text
from codebase_lens.core.result import CblCommandResult, emit_result
from codebase_lens.git.discover import collect_git_info
from codebase_lens.reports.manifest import build_manifest, prepare_output_layout, write_manifest_bundle


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="Repository root override. Defaults to current directory.")
    parser.add_argument("--out", default=".codecontext", help="Output directory. Defaults to .codecontext.")
    parser.add_argument("--format", choices=("markdown", "json", "both"), default="both")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--absolute-paths", action="store_true")
    parser.add_argument("--allow-no-root", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--quiet", action="store_true")


def _parent() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    _add_global_options(parser)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parent = _parent()
    parser = argparse.ArgumentParser(
        prog="cbl",
        description="Local Codebase Lens: local repository evidence engine for AI-assisted coding.",
        parents=[parent],
    )
    parser.add_argument("--version", action="version", version=f"codebase-lens {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    doctor = sub.add_parser("doctor", parents=[parent], help="Validate local tool and repository readiness.")
    doctor.set_defaults(handler=_run_doctor)

    snapshot = sub.add_parser("snapshot", parents=[parent], help="Write repository snapshot reports.")
    snapshot.add_argument("--changed", action="store_true")
    snapshot.set_defaults(handler=_run_partial)

    tree = sub.add_parser("tree", parents=[parent], help="Print or write a compact repository tree.")
    tree.add_argument("--depth", type=int, default=4)
    tree.add_argument("--show-skipped", action="store_true")
    tree.add_argument("--show-sizes", action="store_true")
    tree.add_argument("--changed-only", action="store_true")
    tree.set_defaults(handler=_run_partial)

    symbols = sub.add_parser("symbols", parents=[parent], help="List Python symbols.")
    symbols.add_argument("--kind", choices=("function", "class", "method", "all"), default="all")
    symbols.add_argument("--path")
    symbols.add_argument("--query")
    symbols.add_argument("--json", action="store_true")
    symbols.set_defaults(handler=_run_partial)

    imports = sub.add_parser("imports", parents=[parent], help="Summarize import graph.")
    imports.add_argument("--path")
    imports.add_argument("--module")
    imports.add_argument("--reverse", action="store_true")
    imports.add_argument("--cycles", action="store_true")
    imports.set_defaults(handler=_run_partial)

    cli = sub.add_parser("cli", parents=[parent], help="Statically discover CLI commands.")
    cli.add_argument("--framework", choices=("typer", "click", "argparse", "all"), default="all")
    cli.add_argument("--path")
    cli.set_defaults(handler=_run_partial)

    routes = sub.add_parser("routes", parents=[parent], help="Statically discover web routes.")
    routes.add_argument("--framework", choices=("fastapi", "flask", "all"), default="all")
    routes.set_defaults(handler=_run_partial)

    tests = sub.add_parser("tests", parents=[parent], help="Inventory tests.")
    tests.add_argument("--target")
    tests.add_argument("--show-fixtures", action="store_true")
    tests.set_defaults(handler=_run_partial)

    diff = sub.add_parser("diff", parents=[parent], help="Summarize Git diffs.")
    diff.add_argument("--staged", action="store_true")
    diff.add_argument("--unstaged", action="store_true")
    diff.add_argument("--base")
    diff.add_argument("--symbols", action="store_true")
    diff.add_argument("--stat", action="store_true")
    diff.set_defaults(handler=_run_partial)

    changed = sub.add_parser("changed", parents=[parent], help="Summarize changed files and changed symbols.")
    changed.set_defaults(handler=_run_partial)

    file_cmd = sub.add_parser("file", parents=[parent], help="Emit a safe line-numbered excerpt from a file.")
    file_cmd.add_argument("path")
    file_cmd.add_argument("--lines")
    file_cmd.add_argument("--around", type=int)
    file_cmd.add_argument("--context", type=int, default=30)
    file_cmd.set_defaults(handler=_run_partial)

    symbol = sub.add_parser("symbol", parents=[parent], help="Emit one or more symbol excerpts.")
    symbol.add_argument("symbol_name")
    symbol.add_argument("--context", type=int, default=20)
    symbol.add_argument("--path")
    symbol.add_argument("--first", action="store_true")
    symbol.set_defaults(handler=_run_partial)

    callers = sub.add_parser("callers", parents=[parent], help="Find static call sites.")
    callers.add_argument("name")
    callers.set_defaults(handler=_run_partial)

    contract = sub.add_parser("contract", parents=[parent], help="Audit repository against an architecture contract.")
    contract.add_argument("--spec")
    contract.add_argument("--no-fail-exit", action="store_true")
    contract.set_defaults(handler=_run_partial)

    pack = sub.add_parser("pack", parents=[parent], help="Produce an AI handoff pack.")
    pack.add_argument("--changed", action="store_true")
    pack.add_argument("--issue")
    pack.add_argument("--spec")
    pack.set_defaults(handler=_run_partial)

    clean = sub.add_parser("clean", parents=[parent], help="Remove old .codecontext/runs archives.")
    clean.add_argument("--keep", type=int, default=10)
    clean.add_argument("--all", action="store_true")
    clean.set_defaults(handler=_run_partial)

    return parser


def _git_manifest_payload(git_info) -> dict[str, object]:
    return {
        "available": git_info.available,
        "is_repo": git_info.is_repo,
        "branch": git_info.branch,
        "head": git_info.head,
        "is_dirty": git_info.is_dirty,
        "staged_count": git_info.staged_count,
        "unstaged_count": git_info.unstaged_count,
        "untracked_count": git_info.untracked_count,
    }


def _run_doctor(args: argparse.Namespace) -> int:
    try:
        root_info = detect_repository_root(
            explicit_repo=args.repo,
            allow_no_root=args.allow_no_root,
        )
        repo_root = root_info.root
        git_info = collect_git_info(repo_root)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        warnings = list(root_info.warnings)
        warnings.extend(git_info.warnings)

        if not gitignore_mentions_codecontext(repo_root):
            warnings.append("WARNING: .codecontext/ is not ignored by Git. Add it to .gitignore.")

        manifest = build_manifest(
            repo_root=repo_root,
            repo_name=repo_root.name,
            root_redacted_for_ai=True,
            is_git_repo=git_info.is_repo,
            git=_git_manifest_payload(git_info),
            argv=["cbl", *sys.argv[1:]],
            subcommand="doctor",
            budget=args.budget,
            focus=list(args.focus),
            outputs={
                "manifest_json": ".codecontext/latest/manifest.json",
            },
            redaction={
                "enabled": True,
                "redacted_files_count": 0,
                "redacted_occurrences_count": 0,
                "patterns_hit": [],
            },
        )
        manifest_path = write_manifest_bundle(layout, manifest)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not prepare CBL output directory: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL doctor: OK")
        print(f"Repository: {repo_root.name}")
        print(f"Root detection: {root_info.method}")
        print(f"Git available: {git_info.available}")
        print(f"Git repository: {git_info.is_repo}")
        if git_info.branch:
            print(f"Git branch: {git_info.branch}")
        print(f"Git dirty: {git_info.is_dirty}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        if layout.run_dir is not None:
            print(f"Archive run: {display_path(repo_root, layout.run_dir, absolute=args.absolute_paths)}")
        for warning in warnings:
            print(redact_console_text(warning))

    return 0


def _run_partial(args: argparse.Namespace) -> int:
    result = CblCommandResult.partial(
        str(args.command),
        f"The '{args.command}' command is reserved by the command surface but is not implemented yet.",
    )
    emit_result(result, quiet=args.quiet)
    return result.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_INVALID_ARGUMENTS

    if args.command not in PUBLIC_COMMANDS:
        parser.error(f"Unknown command: {args.command}")

    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
''',

    "tests/test_phase0_cli.py": r'''
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from codebase_lens.core.constants import PARTIAL_IMPLEMENTATION_MESSAGE, PUBLIC_COMMANDS

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


def test_top_level_help_renders_command_surface() -> None:
    result = run_cbl("--help")
    assert result.returncode == 0
    for command in ("doctor", "pack", "contract", "changed", "callers"):
        assert command in result.stdout


def test_doctor_is_implemented_after_phase1() -> None:
    result = run_cbl("doctor", "--no-archive")
    assert result.returncode == 0
    assert "CBL doctor: OK" in result.stdout
    assert "PARTIAL IMPLEMENTATION" not in result.stdout
    assert "C:\\Users\\" not in result.stdout


def test_partial_commands_remain_explicit() -> None:
    result = run_cbl("pack")
    assert result.returncode == 1
    assert "CBL command: pack" in result.stdout
    assert PARTIAL_IMPLEMENTATION_MESSAGE in result.stdout


def test_all_public_commands_have_help() -> None:
    for command in PUBLIC_COMMANDS:
        result = run_cbl(command, "--help")
        assert result.returncode == 0, command
''',

    "tests/test_phase1_safety.py": r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codebase_lens.core.paths import (
    detect_repository_root,
    is_hard_excluded_relative,
    resolve_user_path,
)
from codebase_lens.core.errors import PathSafetyError
from codebase_lens.core.redaction import redact_text
from codebase_lens.core.textio import read_text_with_policy
from codebase_lens.reports.manifest import build_manifest, prepare_output_layout, write_manifest_bundle

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


def test_root_detection_uses_project_marker(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "src" / "pkg"
    nested.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    info = detect_repository_root(start=nested)

    assert info.root == repo.resolve()
    assert info.method == "marker:pyproject.toml"
    assert info.is_git_repo is False


def test_path_safety_rejects_traversal_absolute_and_hard_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "safe.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")

    assert resolve_user_path(repo, "safe.py") == (repo / "safe.py").resolve()

    with pytest.raises(PathSafetyError):
        resolve_user_path(repo, ".." / Path("outside.txt"))

    with pytest.raises(PathSafetyError):
        resolve_user_path(repo, str((repo / "safe.py").resolve()))

    with pytest.raises(PathSafetyError):
        resolve_user_path(repo, ".env")


def test_hard_exclusion_patterns_cover_sensitive_and_generated_paths() -> None:
    assert is_hard_excluded_relative(".codecontext/latest/manifest.json")
    assert is_hard_excluded_relative("data/raw/table.parquet")
    assert is_hard_excluded_relative("src/package/__pycache__/x.pyc")
    assert is_hard_excluded_relative(".env")
    assert is_hard_excluded_relative("secret.pem")
    assert not is_hard_excluded_relative("src/codebase_lens/cli.py")


def test_redaction_handles_assignments_json_yaml_and_private_key_blocks() -> None:
    text = "\n".join(
        [
            "OPENAI_API_KEY=sk-real-secret",
            '{"token": "abc123"}',
            "password: hunter2",
            "-----BEGIN RSA PRIVATE KEY-----",
            "private-body",
            "-----END RSA PRIVATE KEY-----",
        ]
    )

    result = redact_text(text)

    assert "sk-real-secret" not in result.text
    assert "abc123" not in result.text
    assert "hunter2" not in result.text
    assert "private-body" not in result.text
    assert "OPENAI_API_KEY=<REDACTED>" in result.text
    assert '"token": "<REDACTED>"' in result.text
    assert "password: <REDACTED>" in result.text
    assert "<REDACTED_PRIVATE_KEY_BLOCK>" in result.text
    assert result.stats.redacted_occurrences_count >= 4


def test_text_policy_detects_binary_large_and_cp1252(tmp_path: Path) -> None:
    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"abc\x00def")
    binary_result = read_text_with_policy(binary)
    assert binary_result.is_binary is True
    assert binary_result.skipped_reason == "binary_skipped"

    large = tmp_path / "large.txt"
    large.write_text("x" * 20, encoding="utf-8")
    large_result = read_text_with_policy(large, max_file_bytes=10)
    assert large_result.skipped_reason == "large_skipped"

    cp1252 = tmp_path / "latin.txt"
    cp1252.write_bytes("ação".encode("cp1252"))
    cp1252_result = read_text_with_policy(cp1252)
    assert cp1252_result.text == "ação"
    assert cp1252_result.encoding in {"cp1252", "latin-1"}


def test_manifest_writer_creates_latest_and_archive(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    layout = prepare_output_layout(repo, ".codecontext", archive=True)
    manifest = build_manifest(
        repo_root=repo,
        repo_name="repo",
        root_redacted_for_ai=True,
        is_git_repo=False,
        git={
            "available": True,
            "is_repo": False,
            "branch": None,
            "head": None,
            "is_dirty": False,
            "staged_count": 0,
            "unstaged_count": 0,
            "untracked_count": 0,
        },
        argv=["cbl", "doctor"],
        subcommand="doctor",
        budget=16000,
        focus=[],
        outputs={"manifest_json": ".codecontext/latest/manifest.json"},
        redaction={
            "enabled": True,
            "redacted_files_count": 0,
            "redacted_occurrences_count": 0,
            "patterns_hit": [],
        },
    )

    manifest_path = write_manifest_bundle(layout, manifest)

    assert manifest_path.is_file()
    assert layout.run_dir is not None
    assert (layout.run_dir / "manifest.json").is_file()

    parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert parsed["repo"]["root_redacted_for_ai"] is True
    assert parsed["command"]["subcommand"] == "doctor"


def test_doctor_writes_manifest_without_absolute_console_path() -> None:
    result = run_cbl("doctor", "--no-archive")

    assert result.returncode == 0, result.stderr
    assert "CBL doctor: OK" in result.stdout
    assert "Output manifest: .codecontext/latest/manifest.json" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "doctor"
    assert manifest["repo"]["root_redacted_for_ai"] is True
''',

    "scripts/dev/audits/audit_phase1_safety.py": r'''
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
    "src/codebase_lens/core/paths.py": [
        "RootInfo",
        "detect_repository_root",
        "resolve_user_path",
        "is_hard_excluded_relative",
        "gitignore_mentions_codecontext",
    ],
    "src/codebase_lens/core/redaction.py": [
        "RedactionStats",
        "RedactionResult",
        "redact_text",
    ],
    "src/codebase_lens/core/textio.py": [
        "TextReadResult",
        "is_probably_binary",
        "read_text_with_policy",
    ],
    "src/codebase_lens/git/discover.py": [
        "GitInfo",
        "collect_git_info",
        "is_git_available",
    ],
    "src/codebase_lens/reports/manifest.py": [
        "OutputLayout",
        "prepare_output_layout",
        "build_manifest",
        "write_manifest_bundle",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


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


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def main() -> int:
    for relative_path, required in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(required) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    doctor = run_cbl("doctor", "--no-archive")
    if doctor.returncode != 0:
        fail(f"doctor failed after Phase 1 implementation:\nSTDOUT:\n{doctor.stdout}\nSTDERR:\n{doctor.stderr}")

    if "PARTIAL IMPLEMENTATION" in doctor.stdout:
        fail("doctor still reports partial implementation after Phase 1.")

    if "C:\\Users\\" in doctor.stdout:
        fail("doctor leaked an absolute Windows user path in default console output.")

    if "Output manifest: .codecontext/latest/manifest.json" not in doctor.stdout:
        fail("doctor did not report the expected relative manifest path.")

    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"
    if not manifest_path.is_file():
        fail("doctor did not write .codecontext/latest/manifest.json.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["command"]["subcommand"] != "doctor":
        fail("manifest command.subcommand is not doctor.")
    if manifest["repo"]["root_redacted_for_ai"] is not True:
        fail("manifest does not mark root_redacted_for_ai true.")
    if manifest["safety"]["redaction_enabled"] is not True:
        fail("manifest does not mark redaction enabled.")
    if manifest["outputs"]["manifest_json"] != ".codecontext/latest/manifest.json":
        fail("manifest output path contract is wrong.")

    redaction_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from codebase_lens.core.redaction import redact_text; r=redact_text('OPENAI_API_KEY=sk-test-secret\\npassword: hunter2'); print(r.text)",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        text=True,
        capture_output=True,
        check=False,
    )
    if redaction_probe.returncode != 0:
        fail(redaction_probe.stderr)
    if "sk-test-secret" in redaction_probe.stdout or "hunter2" in redaction_probe.stdout:
        fail("redaction probe leaked secret values.")

    print("PASS: Phase 1 safety audit passed.")
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

    print("Slice 002 applied: Phase 1 safety foundation implemented.")
    print("Run the Phase 1 audit and pytest before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())