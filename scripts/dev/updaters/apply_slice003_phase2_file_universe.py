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
DEFAULT_MAX_TOTAL_SCAN_BYTES = 50 * 1024 * 1024
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
    "*.egg-info",
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

    "src/codebase_lens/git/status.py": r'''
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
''',

    "src/codebase_lens/scanners/universe.py": r'''
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.constants import (
    DEFAULT_INCLUDED_TEXT_EXTENSIONS,
    DEFAULT_MAX_FILE_BYTES,
)
from codebase_lens.core.hashing import sha256_file
from codebase_lens.core.models import FileRecord, OmissionRecord
from codebase_lens.core.paths import is_hard_excluded_relative, to_posix_relative
from codebase_lens.core.redaction import RedactionStats, redact_text
from codebase_lens.core.textio import read_text_with_policy
from codebase_lens.git.status import collect_git_file_sets


@dataclass(frozen=True)
class FileUniverseResult:
    repo_root: Path
    is_git_repo: bool
    git_available: bool
    included_files: tuple[FileRecord, ...]
    omitted_files: tuple[OmissionRecord, ...]
    counts: dict[str, int]
    redaction: RedactionStats
    warnings: tuple[str, ...]

    def manifest_counts(self) -> dict[str, int]:
        return {
            "tracked_included_count": self.counts.get("tracked_included_count", 0),
            "untracked_included_count": self.counts.get("untracked_included_count", 0),
            "ignored_count": self.counts.get("ignored_count", 0),
            "hard_excluded_count": self.counts.get("hard_excluded_count", 0),
            "large_skipped_count": self.counts.get("large_skipped_count", 0),
            "binary_skipped_count": self.counts.get("binary_skipped_count", 0),
            "decode_failed_count": self.counts.get("decode_failed_count", 0),
            "redacted_file_count": self.counts.get("redacted_file_count", 0),
            "unsupported_extension_count": self.counts.get("unsupported_extension_count", 0),
            "included_count": self.counts.get("included_count", 0),
        }


def _empty_counts() -> dict[str, int]:
    return {
        "tracked_candidate_count": 0,
        "untracked_candidate_count": 0,
        "filesystem_candidate_count": 0,
        "tracked_included_count": 0,
        "untracked_included_count": 0,
        "filesystem_included_count": 0,
        "included_count": 0,
        "ignored_count": 0,
        "hard_excluded_count": 0,
        "large_skipped_count": 0,
        "binary_skipped_count": 0,
        "decode_failed_count": 0,
        "unsupported_extension_count": 0,
        "missing_or_directory_count": 0,
        "redacted_file_count": 0,
        "redacted_occurrences_count": 0,
    }


def _extension_or_name_is_default_text(path: Path) -> bool:
    name = path.name
    suffix = path.suffix.lower()
    if name in DEFAULT_INCLUDED_TEXT_EXTENSIONS:
        return True
    if suffix in DEFAULT_INCLUDED_TEXT_EXTENSIONS:
        return True
    if suffix == "":
        return True
    return False


def _language_for_path(path: Path) -> str | None:
    suffix = path.suffix.lower()
    mapping = {
        ".py": "python",
        ".pyw": "python",
        ".pyi": "python",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".jsonl": "jsonl",
        ".md": "markdown",
        ".rst": "rst",
        ".txt": "text",
        ".ini": "ini",
        ".cfg": "cfg",
        ".ps1": "powershell",
        ".psm1": "powershell",
        ".bat": "batch",
        ".cmd": "batch",
        ".sh": "shell",
        ".sql": "sql",
        ".html": "html",
        ".css": "css",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
    }
    if path.name == ".gitignore":
        return "gitignore"
    if path.name == ".dockerignore":
        return "dockerignore"
    return mapping.get(suffix)


def _filesystem_candidates(repo_root: Path) -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        relative = to_posix_relative(repo_root, path)

        parts = relative.split("/")
        if any(is_hard_excluded_relative("/".join(parts[: index + 1])) for index in range(len(parts))):
            candidates.append((relative, "filesystem"))
            continue

        candidates.append((relative, "filesystem"))

    return tuple(candidates)


def _git_candidates(repo_root: Path) -> tuple[tuple[str, str], ...]:
    file_sets = collect_git_file_sets(repo_root)
    candidates: list[tuple[str, str]] = []

    for relative in file_sets.tracked:
        candidates.append((relative, "tracked"))

    for relative in file_sets.untracked_nonignored:
        candidates.append((relative, "untracked"))

    return tuple(sorted(set(candidates)))


def _candidate_entries(repo_root: Path, is_git_repo: bool) -> tuple[tuple[str, str], ...]:
    if is_git_repo:
        return _git_candidates(repo_root)
    return _filesystem_candidates(repo_root)


def _omit(relative: str, reason: str, size_bytes: int | None, category: str) -> OmissionRecord:
    return OmissionRecord(
        path=relative,
        reason=reason,
        size_bytes=size_bytes,
        category=category,
    )


def discover_file_universe(
    repo_root: str | Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    include_large: bool = False,
    include_binary: bool = False,
) -> FileUniverseResult:
    root = Path(repo_root).resolve()
    git_sets = collect_git_file_sets(root)
    counts = _empty_counts()
    counts["ignored_count"] = len(git_sets.ignored)

    if git_sets.is_repo:
        counts["tracked_candidate_count"] = len(git_sets.tracked)
        counts["untracked_candidate_count"] = len(git_sets.untracked_nonignored)
    else:
        counts["filesystem_candidate_count"] = sum(1 for _ in root.rglob("*") if _.is_file())

    warnings: list[str] = []
    if git_sets.warning:
        warnings.append(git_sets.warning)

    included: list[FileRecord] = []
    omitted: list[OmissionRecord] = []
    redaction_patterns: set[str] = set()
    redacted_occurrences_count = 0

    for relative, origin in _candidate_entries(root, git_sets.is_repo):
        relative = relative.replace("\\", "/").strip("/")
        if not relative:
            continue

        if is_hard_excluded_relative(relative):
            counts["hard_excluded_count"] += 1
            omitted.append(_omit(relative, "hard_excluded", None, "hard_excluded"))
            continue

        path = root / relative
        if not path.exists() or not path.is_file():
            counts["missing_or_directory_count"] += 1
            omitted.append(_omit(relative, "missing_or_directory", None, "missing_or_directory"))
            continue

        size_bytes = path.stat().st_size

        if not _extension_or_name_is_default_text(path):
            counts["unsupported_extension_count"] += 1
            omitted.append(_omit(relative, "unsupported_extension", size_bytes, "unsupported_extension"))
            continue

        read_result = read_text_with_policy(path, max_file_bytes=max_file_bytes)
        if read_result.skipped_reason == "large_skipped" and not include_large:
            counts["large_skipped_count"] += 1
            omitted.append(_omit(relative, "large_skipped", size_bytes, "large_skipped"))
            continue

        if read_result.skipped_reason == "binary_skipped" and not include_binary:
            counts["binary_skipped_count"] += 1
            omitted.append(_omit(relative, "binary_skipped", size_bytes, "binary_skipped"))
            continue

        if read_result.skipped_reason == "decode_failed":
            counts["decode_failed_count"] += 1
            omitted.append(_omit(relative, "decode_failed", size_bytes, "decode_failed"))
            continue

        text = read_result.text or ""
        redacted = redact_text(text)
        if redacted.stats.redacted_occurrences_count:
            counts["redacted_file_count"] += 1
            redacted_occurrences_count += redacted.stats.redacted_occurrences_count
            redaction_patterns.update(redacted.stats.patterns_hit)

        line_count = len(text.splitlines())
        record = FileRecord(
            path=relative,
            absolute_path="<redacted>",
            status="included",
            git_status=origin if git_sets.is_repo else None,
            extension=path.suffix.lower() or None,
            size_bytes=size_bytes,
            sha256=sha256_file(path),
            is_text=True,
            is_binary=False,
            is_large=False,
            is_included=True,
            skip_reason=None,
            language=_language_for_path(path),
            line_count=line_count,
            redacted=bool(redacted.stats.redacted_occurrences_count),
        )
        included.append(record)

        if origin == "tracked":
            counts["tracked_included_count"] += 1
        elif origin == "untracked":
            counts["untracked_included_count"] += 1
        else:
            counts["filesystem_included_count"] += 1

    included = sorted(included, key=lambda record: record.path)
    omitted = sorted(omitted, key=lambda record: record.path)

    counts["included_count"] = len(included)
    counts["redacted_occurrences_count"] = redacted_occurrences_count

    return FileUniverseResult(
        repo_root=root,
        is_git_repo=git_sets.is_repo,
        git_available=git_sets.available,
        included_files=tuple(included),
        omitted_files=tuple(omitted),
        counts=counts,
        redaction=RedactionStats(
            enabled=True,
            redacted_occurrences_count=redacted_occurrences_count,
            patterns_hit=tuple(sorted(redaction_patterns)),
        ),
        warnings=tuple(warnings),
    )
''',

    "src/codebase_lens/scanners/inventory.py": r'''
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from codebase_lens.reports.manifest import OutputLayout, write_json
from codebase_lens.scanners.universe import FileUniverseResult


def file_universe_to_inventory(result: FileUniverseResult) -> dict[str, Any]:
    return {
        "repo": {
            "name": result.repo_root.name,
            "is_git_repo": result.is_git_repo,
            "git_available": result.git_available,
        },
        "counts": dict(result.counts),
        "redaction": {
            "enabled": result.redaction.enabled,
            "redacted_occurrences_count": result.redaction.redacted_occurrences_count,
            "patterns_hit": list(result.redaction.patterns_hit),
        },
        "files": [asdict(record) for record in result.included_files],
        "omissions": [asdict(record) for record in result.omitted_files],
        "warnings": list(result.warnings),
    }


def write_file_inventory(layout: OutputLayout, result: FileUniverseResult) -> Path:
    path = layout.latest_dir / "file_inventory.json"
    write_json(path, file_universe_to_inventory(result))
    return path
''',

    "src/codebase_lens/scanners/tree.py": r'''
from __future__ import annotations

from pathlib import Path

from codebase_lens.core.models import FileRecord, OmissionRecord
from codebase_lens.reports.manifest import OutputLayout
from codebase_lens.scanners.universe import FileUniverseResult


def _trim_path(path: str, max_depth: int) -> str:
    parts = [part for part in path.split("/") if part]
    if max_depth <= 0:
        return path
    if len(parts) <= max_depth:
        return path
    return "/".join([*parts[:max_depth], "..."])


def _tree_lines_from_paths(paths: list[str]) -> list[str]:
    lines = ["."]
    seen: set[str] = set()

    for path in sorted(paths):
        parts = [part for part in path.split("/") if part]
        for index, part in enumerate(parts):
            is_file = index == len(parts) - 1
            prefix = "  " * (index + 1)
            current = "/".join(parts[: index + 1])
            display = part if is_file else f"{part}/"
            if current in seen:
                continue
            seen.add(current)
            lines.append(f"{prefix}{display}")

    return lines


def render_tree_report(
    result: FileUniverseResult,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> str:
    paths: list[str] = []
    size_by_path = {record.path: record.size_bytes for record in result.included_files}

    for record in result.included_files:
        rendered = _trim_path(record.path, max_depth)
        if show_sizes and rendered == record.path:
            rendered = f"{rendered} ({record.size_bytes} bytes)"
        paths.append(rendered)

    lines = [
        "CBL Repository Tree",
        f"Repository: {result.repo_root.name}",
        f"Git repository: {str(result.is_git_repo).lower()}",
        f"Included files: {result.counts.get('included_count', 0)}",
        f"Tracked included: {result.counts.get('tracked_included_count', 0)}",
        f"Untracked included: {result.counts.get('untracked_included_count', 0)}",
        f"Ignored count: {result.counts.get('ignored_count', 0)}",
        f"Hard-excluded count: {result.counts.get('hard_excluded_count', 0)}",
        f"Large skipped count: {result.counts.get('large_skipped_count', 0)}",
        f"Binary skipped count: {result.counts.get('binary_skipped_count', 0)}",
        f"Decode-failed count: {result.counts.get('decode_failed_count', 0)}",
        "",
    ]

    lines.extend(_tree_lines_from_paths(sorted(set(paths))))

    if show_skipped:
        lines.append("")
        lines.append("Skipped and omitted files:")
        if not result.omitted_files:
            lines.append("  <none>")
        for omission in result.omitted_files:
            lines.append(f"  {omission.path} [{omission.reason}]")

    return "\n".join(lines) + "\n"


def write_tree_report(
    layout: OutputLayout,
    result: FileUniverseResult,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> Path:
    path = layout.latest_dir / "repo_tree.txt"
    path.write_text(
        render_tree_report(
            result,
            max_depth=max_depth,
            show_sizes=show_sizes,
            show_skipped=show_skipped,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return path
''',

    "src/codebase_lens/analyzers/excerpts.py": r'''
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.constants import DEFAULT_MAX_EXCERPT_BYTES
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.redaction import RedactionStats, redact_text
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class FileExcerpt:
    path: str
    start_line: int
    end_line: int
    text: str
    redaction: RedactionStats


def parse_line_range(selector: str | None, *, total_lines: int) -> tuple[int, int]:
    if selector is None:
        end = min(total_lines, 200)
        return (1, max(1, end))

    if ":" not in selector:
        try:
            value = int(selector)
        except ValueError as exc:
            raise ValueError("Line selector must be N or START:END.") from exc
        if value < 1:
            raise ValueError("Line numbers are 1-based and must be positive.")
        return (value, min(value, total_lines))

    left, right = selector.split(":", 1)
    start = int(left) if left.strip() else 1
    end = int(right) if right.strip() else total_lines

    if start < 1 or end < 1:
        raise ValueError("Line numbers are 1-based and must be positive.")
    if start > end:
        raise ValueError("Line range start must be less than or equal to end.")

    return (start, min(end, total_lines))


def line_window_around(line: int | None, *, context: int, total_lines: int) -> tuple[int, int] | None:
    if line is None:
        return None
    if line < 1:
        raise ValueError("--around must be a positive 1-based line number.")
    context = max(0, context)
    start = max(1, line - context)
    end = min(total_lines, line + context)
    return (start, end)


def render_numbered_excerpt(
    repo_root: Path,
    path: Path,
    text: str,
    *,
    start_line: int,
    end_line: int,
) -> FileExcerpt:
    lines = text.splitlines()
    if not lines:
        lines = [""]

    start_line = max(1, start_line)
    end_line = min(max(start_line, end_line), len(lines))

    selected_lines = lines[start_line - 1 : end_line]
    selected_text = "\n".join(selected_lines)
    redacted = redact_text(selected_text)
    redacted_lines = redacted.text.splitlines() or [""]

    numbered: list[str] = []
    for offset, line in enumerate(redacted_lines):
        numbered.append(f"{start_line + offset:04d}: {line}")

    relative = to_posix_relative(repo_root, path)
    return FileExcerpt(
        path=relative,
        start_line=start_line,
        end_line=end_line,
        text="\n".join(numbered) + "\n",
        redaction=redacted.stats,
    )


def build_file_excerpt(
    repo_root: str | Path,
    path: str | Path,
    *,
    line_selector: str | None = None,
    around: int | None = None,
    context: int = 30,
    max_file_bytes: int = DEFAULT_MAX_EXCERPT_BYTES,
) -> FileExcerpt:
    root = Path(repo_root).resolve()
    target = Path(path).resolve()

    read_result = read_text_with_policy(target, max_file_bytes=max_file_bytes)
    if read_result.skipped_reason:
        raise ValueError(f"Cannot excerpt file because it was skipped: {read_result.skipped_reason}")

    text = read_result.text or ""
    total_lines = max(1, len(text.splitlines()))

    window = line_window_around(around, context=context, total_lines=total_lines)
    if window is None:
        window = parse_line_range(line_selector, total_lines=total_lines)

    return render_numbered_excerpt(
        root,
        target,
        text,
        start_line=window[0],
        end_line=window[1],
    )


def render_excerpt_markdown(excerpt: FileExcerpt) -> str:
    evidence = f"{excerpt.path}:L{excerpt.start_line}-L{excerpt.end_line}"
    lines = [
        "# CBL File Excerpt",
        "",
        f"Evidence: {evidence}",
        f"Redaction enabled: {str(excerpt.redaction.enabled).lower()}",
        f"Redacted occurrences: {excerpt.redaction.redacted_occurrences_count}",
        "",
        excerpt.text.rstrip("\n"),
        "",
    ]
    return "\n".join(lines)
''',

    "src/codebase_lens/reports/json.py": r'''
from __future__ import annotations

from pathlib import Path
from typing import Any

from codebase_lens.reports.manifest import write_json


def write_json_report(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path)
    write_json(target, payload)
    return target
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


def _clear_directory(directory: Path) -> None:
    if not directory.exists():
        return
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def prepare_output_layout(
    repo_root: str | Path,
    out_dir: str | Path = ".codecontext",
    *,
    archive: bool = True,
    clear_latest: bool = True,
) -> OutputLayout:
    root = Path(repo_root).resolve()
    requested = Path(out_dir)

    codecontext_dir = requested if requested.is_absolute() else root / requested
    codecontext_dir = codecontext_dir.resolve()

    latest_dir = codecontext_dir / "latest"
    runs_dir = codecontext_dir / "runs"

    latest_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    if clear_latest:
        _clear_directory(latest_dir)

    run_dir = None
    if archive:
        base = runs_dir / utc_run_stamp()
        run_dir = base
        suffix = 1
        while run_dir.exists():
            run_dir = Path(f"{base}-{suffix}")
            suffix += 1
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
            "redacted_file_count": 0,
            "included_count": 0,
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
from codebase_lens.analyzers.excerpts import build_file_excerpt, render_excerpt_markdown
from codebase_lens.core.constants import (
    DEFAULT_BUDGET,
    DEFAULT_MAX_EXCERPT_BYTES,
    DEFAULT_MAX_FILE_BYTES,
    EXIT_GENERAL_ERROR,
    EXIT_INVALID_ARGUMENTS,
    EXIT_OUTPUT_WRITE_FAILURE,
    EXIT_PATH_SAFETY_VIOLATION,
    EXIT_ROOT_DETECTION_FAILURE,
    PUBLIC_COMMANDS,
)
from codebase_lens.core.errors import CblError, PathSafetyError, RootDetectionError
from codebase_lens.core.paths import detect_repository_root, display_path, gitignore_mentions_codecontext, resolve_user_path
from codebase_lens.core.redaction import redact_console_text
from codebase_lens.core.result import CblCommandResult, emit_result
from codebase_lens.git.discover import collect_git_info
from codebase_lens.reports.manifest import build_manifest, copy_latest_to_run, prepare_output_layout, write_manifest_bundle
from codebase_lens.scanners.inventory import write_file_inventory
from codebase_lens.scanners.tree import write_tree_report
from codebase_lens.scanners.universe import discover_file_universe


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=None, help="Repository root override. Defaults to detected current repository.")
    parser.add_argument("--out", default=".codecontext", help="Output directory. Defaults to .codecontext.")
    parser.add_argument("--format", choices=("markdown", "json", "both"), default="both")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--absolute-paths", action="store_true")
    parser.add_argument("--allow-no-root", action="store_true")
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
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
    tree.set_defaults(handler=_run_tree)

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
    file_cmd.set_defaults(handler=_run_file)

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


def _detect_root(args: argparse.Namespace):
    return detect_repository_root(
        explicit_repo=args.repo,
        allow_no_root=args.allow_no_root,
    )


def _base_manifest_args(args: argparse.Namespace, repo_root: Path, subcommand: str, outputs: dict[str, str], file_universe=None, redaction=None) -> dict[str, object]:
    git_info = collect_git_info(repo_root)
    redaction_payload = redaction or {
        "enabled": True,
        "redacted_files_count": 0,
        "redacted_occurrences_count": 0,
        "patterns_hit": [],
    }

    return {
        "repo_root": repo_root,
        "repo_name": repo_root.name,
        "root_redacted_for_ai": True,
        "is_git_repo": git_info.is_repo,
        "git": _git_manifest_payload(git_info),
        "argv": ["cbl", *sys.argv[1:]],
        "subcommand": subcommand,
        "budget": args.budget,
        "focus": list(args.focus),
        "outputs": outputs,
        "redaction": redaction_payload,
        "file_universe": file_universe,
    }


def _run_doctor(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        git_info = collect_git_info(repo_root)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        warnings = list(root_info.warnings)
        warnings.extend(git_info.warnings)

        if not gitignore_mentions_codecontext(repo_root):
            warnings.append("WARNING: .codecontext/ is not ignored by Git. Add it to .gitignore.")

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "doctor",
                {"manifest_json": ".codecontext/latest/manifest.json"},
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

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


def _run_tree(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        universe = discover_file_universe(repo_root, max_file_bytes=args.max_file_bytes)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)

        inventory_path = write_file_inventory(layout, universe)
        tree_path = write_tree_report(
            layout,
            universe,
            max_depth=args.depth,
            show_sizes=args.show_sizes,
            show_skipped=args.show_skipped,
        )

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "tree",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "file_inventory_json": ".codecontext/latest/file_inventory.json",
                    "repo_tree_txt": ".codecontext/latest/repo_tree.txt",
                },
                file_universe=universe.manifest_counts(),
                redaction={
                    "enabled": True,
                    "redacted_files_count": universe.counts.get("redacted_file_count", 0),
                    "redacted_occurrences_count": universe.redaction.redacted_occurrences_count,
                    "patterns_hit": list(universe.redaction.patterns_hit),
                },
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not write tree report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL tree: OK")
        print(f"Repository: {repo_root.name}")
        print(f"Included files: {universe.counts.get('included_count', 0)}")
        print(f"Tracked included: {universe.counts.get('tracked_included_count', 0)}")
        print(f"Untracked included: {universe.counts.get('untracked_included_count', 0)}")
        print(f"Ignored count: {universe.counts.get('ignored_count', 0)}")
        print(f"Hard-excluded count: {universe.counts.get('hard_excluded_count', 0)}")
        print(f"Tree report: {display_path(repo_root, tree_path, absolute=args.absolute_paths)}")
        print(f"File inventory: {display_path(repo_root, inventory_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for warning in universe.warnings:
            print(redact_console_text(f"WARNING: {warning}"))

    return 0


def _run_file(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        target = resolve_user_path(
            repo_root,
            args.path,
            allow_absolute=False,
            allow_hard_excluded=False,
        )

        excerpt = build_file_excerpt(
            repo_root,
            target,
            line_selector=args.lines,
            around=args.around,
            context=args.context,
            max_file_bytes=min(args.max_file_bytes, DEFAULT_MAX_EXCERPT_BYTES),
        )

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        excerpt_path = layout.latest_dir / "file_excerpt.md"
        excerpt_markdown = render_excerpt_markdown(excerpt)
        excerpt_path.write_text(excerpt_markdown + "\n", encoding="utf-8", newline="\n")

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "file",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "file_excerpt_md": ".codecontext/latest/file_excerpt.md",
                },
                redaction={
                    "enabled": True,
                    "redacted_files_count": 1 if excerpt.redaction.redacted_occurrences_count else 0,
                    "redacted_occurrences_count": excerpt.redaction.redacted_occurrences_count,
                    "patterns_hit": list(excerpt.redaction.patterns_hit),
                },
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except PathSafetyError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_PATH_SAFETY_VIOLATION
    except ValueError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_INVALID_ARGUMENTS
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not read or write file excerpt: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print(excerpt_markdown)
        print(f"Excerpt report: {display_path(repo_root, excerpt_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")

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

    "tests/test_file_universe.py": r'''
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codebase_lens.scanners.universe import discover_file_universe


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable is not available")
def test_git_file_universe_includes_tracked_and_untracked_nonignored(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    run_git(repo, "init")
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repo / "tracked.py").write_text("print('tracked')\n", encoding="utf-8")
    (repo / "untracked.py").write_text("print('untracked')\n", encoding="utf-8")
    (repo / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "data" / "tracked_data.py").write_text("print('no')\n", encoding="utf-8")

    run_git(repo, "add", ".gitignore", "tracked.py", "data/tracked_data.py")

    result = discover_file_universe(repo)

    paths = {record.path for record in result.included_files}

    assert "tracked.py" in paths
    assert "untracked.py" in paths
    assert "ignored.txt" not in paths
    assert "data/tracked_data.py" not in paths

    assert result.is_git_repo is True
    assert result.counts["tracked_included_count"] >= 1
    assert result.counts["untracked_included_count"] >= 1
    assert result.counts["ignored_count"] >= 1
    assert result.counts["hard_excluded_count"] >= 1


def test_non_git_file_universe_uses_filesystem_walk_and_skips_unsafe(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    (repo / "blob.bin").write_bytes(b"abc\x00def")

    result = discover_file_universe(repo)

    paths = {record.path for record in result.included_files}
    omitted = {record.path: record.reason for record in result.omitted_files}

    assert "pyproject.toml" in paths
    assert "src/main.py" in paths
    assert ".env" not in paths
    assert "blob.bin" not in paths
    assert omitted[".env"] == "hard_excluded"
    assert omitted["blob.bin"] in {"hard_excluded", "binary_skipped", "unsupported_extension"}
    assert result.is_git_repo is False


def test_file_universe_records_redaction_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "settings.py").write_text("API_KEY = 'sk-fake-secret'\n", encoding="utf-8")

    result = discover_file_universe(repo)

    assert result.counts["redacted_file_count"] == 1
    assert result.redaction.redacted_occurrences_count == 1
    assert "API_KEY" in result.redaction.patterns_hit
''',

    "tests/test_tree_report.py": r'''
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
''',

    "tests/test_file_excerpt.py": r'''
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from codebase_lens.analyzers.excerpts import build_file_excerpt, render_excerpt_markdown
from codebase_lens.core.errors import PathSafetyError
from codebase_lens.core.paths import resolve_user_path

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


def test_build_file_excerpt_is_line_numbered_and_redacted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "settings.py"
    target.write_text(
        "alpha = 1\nAPI_KEY = 'sk-fake-secret'\nomega = 3\n",
        encoding="utf-8",
    )

    excerpt = build_file_excerpt(repo, target, line_selector="1:3")
    rendered = render_excerpt_markdown(excerpt)

    assert "settings.py:L1-L3" in rendered
    assert "0001: alpha = 1" in rendered
    assert "0002: API_KEY = '<REDACTED>'" in rendered
    assert "sk-fake-secret" not in rendered


def test_file_command_rejects_hard_excluded_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")

    try:
        resolve_user_path(repo, ".env")
    except PathSafetyError:
        pass
    else:
        raise AssertionError(".env should be rejected by path safety")


def test_file_command_writes_excerpt_and_uses_relative_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (repo / "module.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")

    result = run_cbl("file", "module.py", "--repo", str(repo), "--lines", "1:2", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Evidence: module.py:L1-L2" in result.stdout
    assert "0001: x = 1" in result.stdout
    assert "0002: y = 2" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    excerpt_path = repo / ".codecontext" / "latest" / "file_excerpt.md"
    assert excerpt_path.is_file()
    assert "module.py:L1-L2" in excerpt_path.read_text(encoding="utf-8")
''',

    "scripts/dev/audits/audit_phase2_file_universe.py": r'''
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

    print("Slice 003 applied: Phase 2 Git-aware file universe, tree report, and file excerpts implemented.")
    print("Run the Phase 2 audit and pytest before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())