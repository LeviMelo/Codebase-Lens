from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path.cwd()


def require_repo_root() -> None:
    if not (ROOT / "pyproject.toml").is_file() or not (ROOT / "src" / "codebase_lens").is_dir():
        raise SystemExit("Run this updater from the CBL repository root.")


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def replace_assignment(text: str, name: str, replacement: str) -> str:
    pattern = re.compile(rf"^{re.escape(name)}\s*=", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"Assignment not found: {name}")

    start = match.start()
    pos = match.end()
    depth = 0
    in_string: str | None = None
    escaped = False
    seen_open = False

    while pos < len(text):
        ch = text[pos]

        if in_string is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            pos += 1
            continue

        if ch in {"'", '"'}:
            in_string = ch
            pos += 1
            continue

        if ch in "([{" :
            depth += 1
            seen_open = True
        elif ch in ")]}":
            depth -= 1

        pos += 1

        if seen_open and depth <= 0:
            while pos < len(text) and text[pos] in " \t\r\n":
                pos += 1
            return text[:start] + replacement.rstrip() + "\n\n" + text[pos:]

    raise RuntimeError(f"Could not find end of assignment: {name}")


def replace_function(text: str, name: str, replacement: str) -> str:
    pattern = re.compile(rf"^def {re.escape(name)}\(", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"Function not found: {name}")

    start = match.start()
    next_match = re.search(r"^(def |class |@dataclass|[A-Z_][A-Z0-9_]+\s*=)", text[match.end():], re.MULTILINE)
    if next_match:
        end = match.end() + next_match.start()
    else:
        end = len(text)

    return text[:start] + replacement.rstrip() + "\n\n" + text[end:].lstrip("\n")


def patch_constants() -> None:
    path = "src/codebase_lens/core/constants.py"
    text = read(path)

    hard_dirs = r'''HARD_EXCLUDED_DIR_NAMES = frozenset(
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
        "site-packages",
        ".eggs",
    }
)'''

    hard_files = r'''HARD_EXCLUDED_FILE_PATTERNS = (
    ".env",
    ".env.local",
    ".env.*.local",
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
)'''

    included_text = r'''DEFAULT_INCLUDED_TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyw",
        ".pyi",
        ".r",
        ".R",
        ".Rmd",
        ".qmd",
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
        ".env.example",
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
        ".scss",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".kts",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".lua",
        ".jl",
        ".m",
        ".mm",
        ".swift",
        ".scala",
        ".clj",
        ".ex",
        ".exs",
        ".erl",
        ".hrl",
        ".fs",
        ".fsx",
        ".ml",
        ".mli",
        ".nim",
        ".zig",
        ".hs",
        ".lhs",
        ".pl",
        ".pm",
        ".awk",
        ".sed",
        ".dockerfile",
        ".make",
        ".mk",
        ".cmake",
        ".jinja",
        ".j2",
        ".mustache",
        ".graphql",
        ".proto",
        ".thrift",
        ".csv",
        ".tsv",
    }
)'''

    text = replace_assignment(text, "HARD_EXCLUDED_DIR_NAMES", hard_dirs)
    text = replace_assignment(text, "HARD_EXCLUDED_FILE_PATTERNS", hard_files)
    if "DEFAULT_INCLUDED_TEXT_EXTENSIONS" in text:
        text = replace_assignment(text, "DEFAULT_INCLUDED_TEXT_EXTENSIONS", included_text)
    else:
        text += "\n\n" + included_text + "\n"

    write(path, text)


def patch_paths() -> None:
    path = "src/codebase_lens/core/paths.py"
    text = read(path)

    replacement = r'''def is_hard_excluded_relative(relative_posix_path: str) -> bool:
    """Return true only for non-source infrastructure, secrets, and binary/data artifacts."""

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

    return False'''

    text = replace_function(text, "is_hard_excluded_relative", replacement)
    write(path, text)


UNIVERSE_SOURCE = r'''from __future__ import annotations

import os
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

    @property
    def omissions(self) -> tuple[OmissionRecord, ...]:
        return self.omitted_files

    def manifest_counts(self) -> dict[str, int]:
        return {
            "tracked_included_count": self.counts.get("tracked_included_count", 0),
            "untracked_included_count": self.counts.get("untracked_included_count", 0),
            "filesystem_included_count": self.counts.get("filesystem_included_count", 0),
            "ignored_count": self.counts.get("ignored_count", 0),
            "hard_excluded_ignored_count": self.counts.get("hard_excluded_ignored_count", 0),
            "hard_excluded_count": self.counts.get("hard_excluded_count", 0),
            "large_skipped_count": self.counts.get("large_skipped_count", 0),
            "binary_skipped_count": self.counts.get("binary_skipped_count", 0),
            "decode_failed_count": self.counts.get("decode_failed_count", 0),
            "redacted_file_count": self.counts.get("redacted_file_count", 0),
            "unsupported_extension_count": self.counts.get("unsupported_extension_count", 0),
            "included_count": self.counts.get("included_count", 0),
            "omitted_files_count": self.counts.get("omitted_files_count", 0),
        }


LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".r": "r",
    ".R": "r",
    ".rmd": "r",
    ".Rmd": "r",
    ".qmd": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".jsonl": "jsonl",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".ini": "ini",
    ".cfg": "ini",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sh": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".csv": "csv",
    ".tsv": "tsv",
}

SOURCE_LIKE_FILENAMES = {
    ".dockerignore",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".env.example",
    ".env.sample",
    ".env.template",
    "Dockerfile",
    "Containerfile",
    "Makefile",
    "makefile",
    "Rakefile",
    "Gemfile",
    "Procfile",
    "requirements.txt",
    "requirements-dev.txt",
}


def _split_ignored_counts(ignored_paths: tuple[str, ...]) -> tuple[int, int]:
    hard_excluded = 0
    ordinary = 0

    for raw_path in ignored_paths:
        relative = raw_path.replace("\\", "/").strip("/")
        if not relative:
            continue
        if is_hard_excluded_relative(relative):
            hard_excluded += 1
        else:
            ordinary += 1

    return ordinary, hard_excluded


def _empty_counts() -> dict[str, int]:
    return {
        "tracked_candidate_count": 0,
        "untracked_candidate_count": 0,
        "filesystem_candidate_count": 0,
        "tracked_included_count": 0,
        "untracked_included_count": 0,
        "filesystem_included_count": 0,
        "included_count": 0,
        "omitted_files_count": 0,
        "ignored_count": 0,
        "hard_excluded_ignored_count": 0,
        "hard_excluded_count": 0,
        "large_skipped_count": 0,
        "binary_skipped_count": 0,
        "decode_failed_count": 0,
        "missing_or_directory_count": 0,
        "unsupported_extension_count": 0,
        "redacted_file_count": 0,
    }


def _language_for(path: Path) -> str:
    suffix = path.suffix
    if suffix in LANGUAGE_BY_SUFFIX:
        return LANGUAGE_BY_SUFFIX[suffix]
    lowered = suffix.lower()
    if lowered in LANGUAGE_BY_SUFFIX:
        return LANGUAGE_BY_SUFFIX[lowered]
    if path.name in SOURCE_LIKE_FILENAMES:
        return "text"
    return "text"


def _extension_or_name_is_default_text(path: Path) -> bool:
    lowered_allowed = {item.lower() for item in DEFAULT_INCLUDED_TEXT_EXTENSIONS}
    suffix = path.suffix
    return (
        suffix in DEFAULT_INCLUDED_TEXT_EXTENSIONS
        or suffix.lower() in lowered_allowed
        or path.name in SOURCE_LIKE_FILENAMES
    )


def _filesystem_candidates(repo_root: Path) -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []

    for current_root, dir_names, file_names in os.walk(repo_root):
        current = Path(current_root)
        relative_current = "" if current == repo_root else to_posix_relative(repo_root, current)

        kept_dirs: list[str] = []
        for name in dir_names:
            candidate = f"{relative_current}/{name}".strip("/")
            if is_hard_excluded_relative(candidate):
                continue
            kept_dirs.append(name)
        dir_names[:] = kept_dirs

        for name in file_names:
            path = current / name
            relative = to_posix_relative(repo_root, path)
            candidates.append((relative, "filesystem"))

    return tuple(sorted(set(candidates)))


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
    """Materialize candidates first, then classify by concrete file facts."""

    root = Path(repo_root).resolve()
    git_sets = collect_git_file_sets(root)
    counts = _empty_counts()
    ignored_count, hard_excluded_ignored_count = _split_ignored_counts(git_sets.ignored)
    counts["ignored_count"] = ignored_count
    counts["hard_excluded_ignored_count"] = hard_excluded_ignored_count

    if git_sets.is_repo:
        counts["tracked_candidate_count"] = len(git_sets.tracked)
        counts["untracked_candidate_count"] = len(git_sets.untracked_nonignored)
    else:
        counts["filesystem_candidate_count"] = sum(1 for _ in _filesystem_candidates(root))

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

        if read_result.skipped_reason:
            omitted.append(_omit(relative, read_result.skipped_reason, size_bytes, read_result.skipped_reason))
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
            language=_language_for(path),
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

    included = sorted(included, key=lambda item: item.path)
    omitted = sorted(omitted, key=lambda item: item.path)
    counts["included_count"] = len(included)
    counts["omitted_files_count"] = len(omitted)

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
'''


def patch_universe() -> None:
    write("src/codebase_lens/scanners/universe.py", UNIVERSE_SOURCE)


def patch_dump() -> None:
    path = "src/codebase_lens/reports/dump.py"
    text = read(path)

    language = r'''def _language(path: str) -> str:
    suffix = Path(path).suffix
    lowered = suffix.lower()
    mapping = {
        ".py": "python",
        ".pyw": "python",
        ".pyi": "python",
        ".r": "r",
        ".rmd": "r",
        ".qmd": "markdown",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".jsonl": "jsonl",
        ".md": "markdown",
        ".rst": "rst",
        ".txt": "text",
        ".ini": "ini",
        ".cfg": "ini",
        ".ps1": "powershell",
        ".psm1": "powershell",
        ".bat": "batch",
        ".cmd": "batch",
        ".sh": "bash",
        ".sql": "sql",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".csv": "csv",
        ".tsv": "tsv",
    }
    if suffix == ".R" or path.endswith(".R"):
        return "r"
    return mapping.get(lowered, "text")'''

    config_path = r'''def _is_config_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    p = Path(normalized)
    return (
        normalized.startswith("config/")
        or p.name in CONFIG_FILENAMES
        or p.suffix.lower() in {".toml", ".yaml", ".yml", ".ini", ".cfg", ".json", ".jsonl"}
    )'''

    filter_records = r'''def _filter_records(
    records,
    *,
    tracked_only: bool,
    include_untracked: bool,
    include_tests: bool,
    include_docs: bool,
    include_config: bool,
    include_json: bool = False,
    scope_paths: tuple[str, ...] = (),
):
    """Filter an already materialized text universe for dump presentation."""

    selected = []
    omissions: list[dict[str, Any]] = []
    normalized_scopes = tuple(
        item.replace("\\", "/").strip("/")
        for item in scope_paths
        if str(item).replace("\\", "/").strip("/")
    )

    def in_scope(path: str) -> bool:
        if not normalized_scopes:
            return True
        normalized = path.replace("\\", "/").strip("/")
        return any(normalized == scope or normalized.startswith(scope + "/") for scope in normalized_scopes)

    for record in sorted(records, key=lambda item: item.path):
        path = record.path
        name = Path(path).name

        if name in DUMP_ARTIFACT_NAMES:
            omissions.append({"path": path, "reason": "dump_artifact", "category": "dump_filter", "size_bytes": getattr(record, "size_bytes", None)})
            continue

        if not in_scope(path):
            omissions.append({"path": path, "reason": "outside_scope", "category": "dump_filter", "size_bytes": getattr(record, "size_bytes", None)})
            continue

        if tracked_only and getattr(record, "git_status", None) == "untracked" and not include_untracked:
            omissions.append({"path": path, "reason": "untracked_excluded", "category": "dump_filter", "size_bytes": getattr(record, "size_bytes", None)})
            continue

        if not include_tests and _is_test_path(path):
            omissions.append({"path": path, "reason": "tests_excluded", "category": "dump_filter", "size_bytes": getattr(record, "size_bytes", None)})
            continue

        if not include_docs and _is_doc_path(path):
            omissions.append({"path": path, "reason": "docs_excluded", "category": "dump_filter", "size_bytes": getattr(record, "size_bytes", None)})
            continue

        if not include_config and _is_config_path(path):
            omissions.append({"path": path, "reason": "config_excluded", "category": "dump_filter", "size_bytes": getattr(record, "size_bytes", None)})
            continue

        selected.append(record)

    return selected, omissions'''

    text = replace_function(text, "_is_config_path", config_path)
    if "def _language(" in text:
        text = replace_function(text, "_language", language)
    text = replace_function(text, "_filter_records", filter_records)

    write(path, text)


TEST_SOURCE = r'''from __future__ import annotations

import json
import subprocess
from pathlib import Path

from codebase_lens.reports.dump import write_codebase_dump
from codebase_lens.reports.manifest import prepare_output_layout
from codebase_lens.scanners.universe import discover_file_universe


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "cbl@example.invalid")
    _git(repo, "config", "user.name", "CBL Test")

    _write(repo / "pyproject.toml", "[project]\nname='fixture'\nversion='0.0.0'")
    _write(repo / ".env.example", "TOKEN=example-only")
    _write(repo / ".env", "TOKEN=secret")
    _write(repo / "src/pkg/output/denominator.py", "def denominator():\n    return 1")
    _write(repo / "src/pkg/data/schema.py", "SCHEMA = {'ok': True}")
    _write(repo / "src/pkg/cache/store.py", "def store():\n    return 'ok'")
    _write(repo / "src/pkg/r_scripts/fetch.R", "cat('fetch')\n")
    _write(repo / "scripts/check_r_microdatasus.R", "cat('check')\n")
    _write(repo / "config/intents/alagoas_smoke.json", json.dumps({"execution_scale": "smoke"}))
    _write(repo / "config/registries/sidra_table_seed.jsonl", '{"table_id":"9606"}')
    _write(repo / "tests/fixtures/sidra_flat_fixture.json", json.dumps({"payload": [1]}))
    _write(repo / "tests/fixtures/small.csv", "a,b\n1,2")
    _write(repo / "data/small_tracked_fixture.csv", "a,b\n1,2")
    _write(repo / ".codecontext/latest/old.md", "generated")
    _write(repo / "model.parquet", "not really parquet but suffix must be excluded")

    _git(repo, "add", ".")
    return repo


def test_file_universe_is_evidence_driven_not_directory_name_driven(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    universe = discover_file_universe(repo)
    paths = {record.path for record in universe.included_files}
    omitted = {record.path: record.reason for record in universe.omitted_files}

    assert "src/pkg/output/denominator.py" in paths
    assert "src/pkg/data/schema.py" in paths
    assert "src/pkg/cache/store.py" in paths
    assert "src/pkg/r_scripts/fetch.R" in paths
    assert "scripts/check_r_microdatasus.R" in paths
    assert "config/intents/alagoas_smoke.json" in paths
    assert "config/registries/sidra_table_seed.jsonl" in paths
    assert "tests/fixtures/sidra_flat_fixture.json" in paths
    assert "tests/fixtures/small.csv" in paths
    assert "data/small_tracked_fixture.csv" in paths
    assert ".env.example" in paths

    assert ".env" not in paths
    assert omitted[".env"] == "hard_excluded"
    assert ".codecontext/latest/old.md" not in paths
    assert omitted[".codecontext/latest/old.md"] == "hard_excluded"
    assert "model.parquet" not in paths
    assert omitted["model.parquet"] == "hard_excluded"
    assert universe.counts["unsupported_extension_count"] == 0


def test_dump_uses_scanner_text_universe_without_second_extension_gate(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    layout = prepare_output_layout(repo, ".codecontext", archive=False)

    result = write_codebase_dump(
        layout,
        repo,
        max_file_bytes=262144,
        tracked_only=True,
        include_untracked=False,
        include_tests=True,
        include_docs=True,
        include_config=True,
        include_json=False,
        line_numbers=True,
    )

    dump = (repo / ".codecontext/latest/codebase_dump.md").read_text(encoding="utf-8")
    index = json.loads((repo / ".codecontext/latest/codebase_dump_index.json").read_text(encoding="utf-8"))
    dumped_paths = {item["path"] for item in index["files"]}

    expected = {
        "src/pkg/output/denominator.py",
        "src/pkg/data/schema.py",
        "src/pkg/cache/store.py",
        "src/pkg/r_scripts/fetch.R",
        "scripts/check_r_microdatasus.R",
        "config/intents/alagoas_smoke.json",
        "config/registries/sidra_table_seed.jsonl",
        "tests/fixtures/sidra_flat_fixture.json",
        "tests/fixtures/small.csv",
        "data/small_tracked_fixture.csv",
        ".env.example",
    }
    assert expected <= dumped_paths
    for path in expected:
        assert f"### FILE: `{path}`" in dump

    assert ".env" not in dumped_paths
    assert ".codecontext/latest/old.md" not in dumped_paths
    assert "model.parquet" not in dumped_paths
    assert result.counts["included_files"] >= len(expected)
'''


AUDIT_SOURCE = r'''from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return env


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> None:
    result = _run(["git", *args], cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _make_repo(base: Path) -> Path:
    repo = base / "evidence_driven_repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "cbl@example.invalid")
    _git(repo, "config", "user.name", "CBL Test")

    files = {
        "pyproject.toml": "[project]\nname='fixture'\nversion='0.0.0'",
        ".env.example": "TOKEN=example-only",
        ".env": "TOKEN=secret",
        "src/pkg/output/denominator.py": "def denominator():\n    return 1",
        "src/pkg/data/schema.py": "SCHEMA = {'ok': True}",
        "src/pkg/cache/store.py": "def store():\n    return 'ok'",
        "src/pkg/r_scripts/fetch.R": "cat('fetch')",
        "scripts/check_r_microdatasus.R": "cat('check')",
        "config/intents/alagoas_smoke.json": json.dumps({"execution_scale": "smoke"}),
        "config/registries/sidra_table_seed.jsonl": '{"table_id":"9606"}',
        "tests/fixtures/sidra_flat_fixture.json": json.dumps({"payload": [1]}),
        "tests/fixtures/small.csv": "a,b\n1,2",
        "data/small_tracked_fixture.csv": "a,b\n1,2",
        ".codecontext/latest/old.md": "generated",
        "model.parquet": "not really parquet but suffix must be excluded",
    }
    for relative, text in files.items():
        _write(repo / relative, text)
    _git(repo, "add", ".")
    return repo


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbl_source_universe_") as tmp:
        repo = _make_repo(Path(tmp))
        result = _run(
            [
                sys.executable,
                "-m",
                "codebase_lens",
                "dump",
                "--repo",
                str(repo),
                "--no-archive",
            ],
            cwd=ROOT,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode

        latest = repo / ".codecontext/latest"
        dump = (latest / "codebase_dump.md").read_text(encoding="utf-8")
        index = json.loads((latest / "codebase_dump_index.json").read_text(encoding="utf-8"))
        paths = {item["path"] for item in index.get("files", [])}

        required = {
            "src/pkg/output/denominator.py",
            "src/pkg/data/schema.py",
            "src/pkg/cache/store.py",
            "src/pkg/r_scripts/fetch.R",
            "scripts/check_r_microdatasus.R",
            "config/intents/alagoas_smoke.json",
            "config/registries/sidra_table_seed.jsonl",
            "tests/fixtures/sidra_flat_fixture.json",
            "tests/fixtures/small.csv",
            "data/small_tracked_fixture.csv",
            ".env.example",
        }
        missing = sorted(required - paths)
        forbidden = sorted(
            item
            for item in [".env", ".codecontext/latest/old.md", "model.parquet"]
            if item in paths
        )
        heading_missing = sorted(path for path in required if f"### FILE: `{path}`" not in dump)

        if missing or forbidden or heading_missing:
            print(
                json.dumps(
                    {
                        "missing": missing,
                        "forbidden": forbidden,
                        "heading_missing": heading_missing,
                        "all_paths": sorted(paths),
                    },
                    indent=2,
                )
            )
            return 1

    print("PASS: Phase 33 evidence-driven source universe audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def write_tests_and_audit() -> None:
    write("tests/test_evidence_driven_source_universe.py", TEST_SOURCE)
    write("scripts/dev/audits/audit_phase33_evidence_driven_source_universe.py", AUDIT_SOURCE)


def validate_python_files(paths: list[str]) -> None:
    for path in paths:
        ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


def main() -> None:
    require_repo_root()
    patch_constants()
    patch_paths()
    patch_universe()
    patch_dump()
    write_tests_and_audit()
    validate_python_files(
        [
            "src/codebase_lens/core/constants.py",
            "src/codebase_lens/core/paths.py",
            "src/codebase_lens/scanners/universe.py",
            "src/codebase_lens/reports/dump.py",
            "tests/test_evidence_driven_source_universe.py",
            "scripts/dev/audits/audit_phase33_evidence_driven_source_universe.py",
        ]
    )
    print("Applied Slice 028 evidence-driven source universe repair.")
    print("Source universe now materializes Git/nonignored candidates first and classifies by concrete file facts.")
    print("Directory words such as output/data/cache/run no longer hard-exclude tracked text source.")


if __name__ == "__main__":
    main()
