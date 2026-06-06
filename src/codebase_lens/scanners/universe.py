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
