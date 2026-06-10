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

        if ch in "([{":
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
    next_match = re.search(
        r"^(def |class |@dataclass|[A-Z_][A-Z0-9_]+\s*=)",
        text[match.end():],
        re.MULTILINE,
    )
    end = match.end() + next_match.start() if next_match else len(text)
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:].lstrip("\n")


def insert_before_function(text: str, function_name: str, insertion: str) -> str:
    pattern = re.compile(rf"^def {re.escape(function_name)}\(", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"Function not found for insertion: {function_name}")
    return text[:match.start()] + insertion.rstrip() + "\n\n" + text[match.start():]


def patch_constants() -> None:
    path = "src/codebase_lens/core/constants.py"
    text = read(path)

    hard_dirs = """HARD_EXCLUDED_DIR_NAMES = frozenset(
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
)"""

    hard_patterns = """HARD_EXCLUDED_FILE_PATTERNS = (
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
)"""

    text = replace_assignment(text, "HARD_EXCLUDED_DIR_NAMES", hard_dirs)
    text = replace_assignment(text, "HARD_EXCLUDED_FILE_PATTERNS", hard_patterns)
    write(path, text)


def patch_paths() -> None:
    path = "src/codebase_lens/core/paths.py"
    text = read(path)

    replacement = """def is_hard_excluded_relative(relative_posix_path: str) -> bool:
    normalized = relative_posix_path.replace("\\\\", "/").strip("/")
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

    return False"""

    text = replace_function(text, "is_hard_excluded_relative", replacement)
    write(path, text)


def patch_universe() -> None:
    path = "src/codebase_lens/scanners/universe.py"
    text = read(path)

    # Preserve Slice 028's materialize-first implementation, but make sure comments
    # and helper wording reflect the root-aware generated-path rule.
    text = text.replace(
        "It is no longer used as an inclusion gate.  A tracked/nonignored file with an\n"
        "    unknown extension is still included if it is small, decodable text and not\n"
        "    blocked by hard safety rules.",
        "It is no longer used as an inclusion gate. A tracked/nonignored file with an\n"
        "    unknown extension is still included if it is small, decodable text and not\n"
        "    blocked by hard safety rules. Top-level generated/data roots are hard\n"
        "    safety exclusions; source packages with names like data/output/cache are not.",
    )

    text = text.replace(
        "The scanner no longer excludes source based on semantic directory names such as\n"
        "    ``output``, ``data``, ``cache``, or ``run``.  Inclusion is based on safety\n"
        "    predicates, file existence, size, binary/decode checks, and redaction.",
        "The scanner no longer excludes source based on non-root package directory names\n"
        "    such as ``src/pkg/output`` or ``src/pkg/data``. Top-level generated/data\n"
        "    roots remain safety exclusions. Inclusion is otherwise based on file\n"
        "    existence, size, binary/decode checks, and redaction.",
    )

    write(path, text)


def patch_dump() -> None:
    path = "src/codebase_lens/reports/dump.py"
    text = read(path)

    source_ext = """SOURCE_EXTENSIONS = frozenset({".py", ".pyi", ".pyw", ".r", ".R", ".rmd", ".Rmd", ".qmd", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".md", ".rst", ".ps1", ".psm1", ".bat", ".cmd", ".sh", ".sql", ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".html"})"""
    if "SOURCE_EXTENSIONS" in text:
        text = replace_assignment(text, "SOURCE_EXTENSIONS", source_ext)

    source_like = """def _source_like(path: str, *, include_json: bool) -> bool:
    normalized = path.replace("\\\\", "/")
    p = Path(normalized)
    suffix = p.suffix
    lowered = suffix.lower()
    name = p.name

    if normalized.startswith("config/"):
        return lowered in {".toml", ".yaml", ".yml", ".ini", ".cfg", ".json", ".jsonl", ".txt", ".md", ".rst"}

    if name in CONFIG_FILENAMES:
        if lowered in {".json", ".jsonl"}:
            return include_json or name in JSON_CONFIG_FILENAMES
        return True

    if lowered in {".json", ".jsonl", ".csv", ".tsv"}:
        return bool(include_json)

    if suffix == ".R" or path.endswith(".R"):
        return True

    return lowered in {item.lower() for item in SOURCE_EXTENSIONS}"""

    if "def _source_like(" in text:
        text = replace_function(text, "_source_like", source_like)
    else:
        text = insert_before_function(text, "_filter_records", source_like)

    language = """def _language(path: str) -> str:
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
    return mapping.get(lowered, "text")"""
    if "def _language(" in text:
        text = replace_function(text, "_language", language)

    filter_records = """def _filter_records(
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
    selected = []
    omissions: list[dict[str, Any]] = []
    normalized_scopes = tuple(
        item.replace("\\\\", "/").strip("/")
        for item in scope_paths
        if str(item).replace("\\\\", "/").strip("/")
    )

    def in_scope(path: str) -> bool:
        if not normalized_scopes:
            return True
        normalized = path.replace("\\\\", "/").strip("/")
        return any(normalized == scope or normalized.startswith(scope + "/") for scope in normalized_scopes)

    for record in sorted(records, key=lambda item: item.path):
        path = str(getattr(record, "path", ""))
        name = Path(path).name
        git_status = str(getattr(record, "git_status", "") or "")
        reason: str | None = None

        if name in DUMP_ARTIFACT_NAMES:
            reason = "dump_artifact"
        elif not in_scope(path):
            reason = "outside_scope"
        elif tracked_only and git_status == "untracked" and not include_untracked:
            reason = "untracked_excluded"
        elif not include_tests and _is_test_path(path):
            reason = "tests_excluded"
        elif not include_docs and _is_doc_path(path):
            reason = "docs_excluded"
        elif not include_config and _is_config_path(path):
            reason = "config_excluded"
        elif not _source_like(path, include_json=include_json):
            reason = "not_source_like_for_dump"

        if reason:
            omissions.append({"path": path, "reason": reason, "category": "dump_filter", "size_bytes": getattr(record, "size_bytes", None)})
        else:
            selected.append(record)

    return selected, sorted(omissions, key=lambda item: str(item.get("path")))"""
    text = replace_function(text, "_filter_records", filter_records)

    write(path, text)


def patch_slice028_tests_and_audit() -> None:
    test_path = ROOT / "tests/test_evidence_driven_source_universe.py"
    if test_path.is_file():
        text = test_path.read_text(encoding="utf-8")
        text = text.replace(
            '    assert "data/small_tracked_fixture.csv" in paths\n',
            '    assert "data/small_tracked_fixture.csv" not in paths\n'
            '    assert omitted["data/small_tracked_fixture.csv"] == "hard_excluded"\n',
        )
        text = text.replace(
            '        "data/small_tracked_fixture.csv",\n',
            "",
        )
        test_path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")

    audit_path = ROOT / "scripts/dev/audits/audit_phase33_evidence_driven_source_universe.py"
    if audit_path.is_file():
        text = audit_path.read_text(encoding="utf-8")
        text = text.replace(
            '            "data/small_tracked_fixture.csv",\n',
            "",
        )
        text = text.replace(
            '            item\n            for item in [".env", ".codecontext/latest/old.md", "model.parquet"]\n',
            '            item\n            for item in [".env", ".codecontext/latest/old.md", "model.parquet", "data/small_tracked_fixture.csv"]\n',
        )
        audit_path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_audit_phase34() -> None:
    audit = r"""from __future__ import annotations

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
    return subprocess.run(args, cwd=cwd, env=_env(), text=True, capture_output=True, check=False)


def _git(repo: Path, *args: str) -> None:
    result = _run(["git", *args], cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbl_root_aware_universe_") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "cbl@example.invalid")
        _git(repo, "config", "user.name", "CBL Test")

        files = {
            "pyproject.toml": "[project]\nname='fixture'\nversion='0.0.0'",
            "src/pkg/output/bundle.py": "def bundle():\n    return 1",
            "src/pkg/data/transforms.py": "def transform():\n    return 2",
            "src/pkg/cache/store.py": "def store():\n    return 3",
            "src/pkg/r_scripts/fetch.R": "cat('fetch')",
            "scripts/check_r.R": "cat('check')",
            "config/intents/smoke.json": json.dumps({"intent": "smoke"}),
            "config/registries/seed.jsonl": '{"id":1}',
            "tests/fixtures/payload.json": json.dumps({"payload": [1]}),
            "output/generated.py": "def poison_should_not_be_scanned():\n    pass",
            "outputs/poison.py": "def output_poison_should_not_be_scanned():\n    pass",
            "data/raw/poison.py": "def data_poison_should_not_be_scanned():\n    pass",
            ".codecontext/latest/old.md": "generated",
            ".env": "TOKEN=secret",
        }
        for relative, content in files.items():
            _write(repo / relative, content)
        _git(repo, "add", ".")

        result = _run([sys.executable, "-m", "codebase_lens", "dump", "--repo", str(repo), "--no-archive"], cwd=ROOT)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode

        dump = (repo / ".codecontext/latest/codebase_dump.md").read_text(encoding="utf-8")
        index = json.loads((repo / ".codecontext/latest/codebase_dump_index.json").read_text(encoding="utf-8"))
        paths = {item["path"] for item in index.get("files", [])}

        required = {
            "src/pkg/output/bundle.py",
            "src/pkg/data/transforms.py",
            "src/pkg/cache/store.py",
            "src/pkg/r_scripts/fetch.R",
            "scripts/check_r.R",
            "config/intents/smoke.json",
            "config/registries/seed.jsonl",
        }
        forbidden = {
            "tests/fixtures/payload.json",
            "output/generated.py",
            "outputs/poison.py",
            "data/raw/poison.py",
            ".codecontext/latest/old.md",
            ".env",
        }

        missing = sorted(required - paths)
        leaked = sorted(forbidden & paths)
        poison_markers = [
            "poison_should_not_be_scanned",
            "output_poison_should_not_be_scanned",
            "data_poison_should_not_be_scanned",
        ]
        marker_leaks = [marker for marker in poison_markers if marker in dump]

        if missing or leaked or marker_leaks:
            print(json.dumps({"missing": missing, "leaked": leaked, "marker_leaks": marker_leaks, "paths": sorted(paths)}, indent=2))
            return 1

        result_json = _run([sys.executable, "-m", "codebase_lens", "dump", "--repo", str(repo), "--include-json", "--no-archive"], cwd=ROOT)
        if result_json.returncode != 0:
            print(result_json.stdout)
            print(result_json.stderr)
            return result_json.returncode
        index_json = json.loads((repo / ".codecontext/latest/codebase_dump_index.json").read_text(encoding="utf-8"))
        paths_json = {item["path"] for item in index_json.get("files", [])}
        if "tests/fixtures/payload.json" not in paths_json:
            print(json.dumps({"missing_include_json_fixture": True, "paths": sorted(paths_json)}, indent=2))
            return 1
        if "output/generated.py" in paths_json or "data/raw/poison.py" in paths_json:
            print(json.dumps({"unsafe_include_json_leak": sorted({"output/generated.py", "data/raw/poison.py"} & paths_json)}, indent=2))
            return 1

    print("PASS: Phase 34 root-aware source universe audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
    write("scripts/dev/audits/audit_phase34_root_aware_source_universe.py", audit)


def validate_python_files(paths: list[str]) -> None:
    for path in paths:
        if (ROOT / path).is_file():
            ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


def main() -> None:
    require_repo_root()
    patch_constants()
    patch_paths()
    patch_universe()
    patch_dump()
    patch_slice028_tests_and_audit()
    write_audit_phase34()
    validate_python_files(
        [
            "src/codebase_lens/core/constants.py",
            "src/codebase_lens/core/paths.py",
            "src/codebase_lens/scanners/universe.py",
            "src/codebase_lens/reports/dump.py",
            "tests/test_evidence_driven_source_universe.py",
            "scripts/dev/audits/audit_phase33_evidence_driven_source_universe.py",
            "scripts/dev/audits/audit_phase34_root_aware_source_universe.py",
        ]
    )
    print("Applied Slice 029 root-aware source-universe repair.")
    print("Source package dirs named output/data/cache are included; top-level generated/data roots remain excluded.")
    print("Non-config JSON/CSV fixtures remain opt-in through --include-json.")


if __name__ == "__main__":
    main()
