from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "codebase_lens").is_dir():
            return candidate
    raise SystemExit("Could not locate CBL repository root. Run from the CBL repo root or a child directory.")


ROOT = find_repo_root()


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise SystemExit(f"Expected marker not found while patching {label}.")
    return text.replace(old, new, 1)


def replace_regex(text: str, pattern: str, new: str, *, label: str) -> str:
    # Use a callable replacement so backslashes in Python source text are not
    # interpreted as re.sub replacement escapes.
    updated, count = re.subn(pattern, lambda _match: new, text, count=1, flags=re.S)
    if count == 0:
        if new in text:
            return text
        raise SystemExit(f"Expected regex marker not found while patching {label}.")
    return updated


def patch_constants() -> None:
    rel = "src/codebase_lens/core/constants.py"
    text = read(rel)

    insertion = '''BINARY_SNIFF_BYTES = 8192

# Extensions that represent user-authored source code and must not be
# discarded merely because they live under a package directory named
# "output", "data", "cache", or another generic artifact-like name.
#
# This is intentionally broader than Python. CBL is a local evidence tool
# for heterogeneous repositories; R bridge scripts, shell scripts, SQL,
# frontend code, and typed stubs are source.
CODE_SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyw",
        ".pyi",
        ".r",
        ".rmd",
        ".qmd",
        ".ps1",
        ".psm1",
        ".bat",
        ".cmd",
        ".sh",
        ".sql",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".scss",
        ".html",
    }
)

'''

    text = replace_once(
        text,
        "BINARY_SNIFF_BYTES = 8192\n\n",
        insertion,
        label=rel,
    )

    default_extensions = '''DEFAULT_INCLUDED_TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyw",
        ".pyi",
        ".r",
        ".rmd",
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
    }
)

'''

    text = replace_regex(
        text,
        r"DEFAULT_INCLUDED_TEXT_EXTENSIONS = frozenset\(\n    \{\n.*?    \}\n\)\n",
        default_extensions,
        label=rel,
    )

    write(rel, text)


def patch_paths() -> None:
    rel = "src/codebase_lens/core/paths.py"
    text = read(rel)

    text = replace_once(
        text,
        "from .constants import HARD_EXCLUDED_DIR_NAMES, HARD_EXCLUDED_FILE_PATTERNS, STRONG_PROJECT_MARKERS\n",
        "from .constants import (\n"
        "    CODE_SOURCE_EXTENSIONS,\n"
        "    HARD_EXCLUDED_DIR_NAMES,\n"
        "    HARD_EXCLUDED_FILE_PATTERNS,\n"
        "    STRONG_PROJECT_MARKERS,\n"
        ")\n",
        label=rel,
    )

    new_function = '''SOURCE_ROOT_DIR_NAMES = frozenset(
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
    normalized = relative_posix_path.strip("/").replace("\\\\", "/")
    if not normalized:
        return False

    parts = tuple(part for part in normalized.split("/") if part)
    for index, _part in enumerate(parts):
        if _hard_excluded_dir_applies(parts, index, normalized):
            return True

    name = parts[-1]
    pure = PurePosixPath(normalized)
    for pattern in HARD_EXCLUDED_FILE_PATTERNS:
        if fnmatch(name, pattern) or pure.match(pattern):
            return True

    if ".dvc/cache" in normalized:
        return True

    return False
'''

    text = replace_regex(
        text,
        r"def is_hard_excluded_relative\(relative_posix_path: str\) -> bool:\n.*?\n\n\ndef resolve_user_path\(",
        new_function + "\n\ndef resolve_user_path(",
        label=rel,
    )

    write(rel, text)


def patch_universe() -> None:
    rel = "src/codebase_lens/scanners/universe.py"
    text = read(rel)

    text = replace_once(
        text,
        '''        ".pyi": "python",
        ".toml": "toml",
''',
        '''        ".pyi": "python",
        ".r": "r",
        ".rmd": "rmarkdown",
        ".qmd": "quarto",
        ".toml": "toml",
''',
        label=rel,
    )

    text = replace_once(
        text,
        '''        ".css": "css",
        ".js": "javascript",
''',
        '''        ".css": "css",
        ".scss": "scss",
        ".js": "javascript",
''',
        label=rel,
    )

    write(rel, text)


def patch_dump_report() -> None:
    rel = "src/codebase_lens/reports/dump.py"
    text = read(rel)

    new_header = '''SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".pyw",
        ".r",
        ".rmd",
        ".qmd",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".md",
        ".rst",
        ".ps1",
        ".psm1",
        ".bat",
        ".cmd",
        ".sh",
        ".sql",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".scss",
        ".html",
    }
)
CONFIG_FILENAMES = frozenset({"pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", "mypy.ini", "ruff.toml", ".gitignore", ".dockerignore", "requirements.txt", "requirements-dev.txt", "setup.py", "package.json", "tsconfig.json", "jsconfig.json", "biome.json", ".eslintrc.json", ".prettierrc.json"})
JSON_CONFIG_FILENAMES = frozenset({"package.json", "tsconfig.json", "jsconfig.json", "biome.json", ".eslintrc.json", ".prettierrc.json"})
JSON_SOURCE_EXTENSIONS = frozenset({".json", ".jsonl"})
DUMP_ARTIFACT_NAMES = frozenset({"codebase_dump.md", "codebase_dump.txt", "codebase_dump_index.json", "diff_dump.md", "diff_dump.txt", "diff_dump_index.json"})
'''

    text = replace_regex(
        text,
        r"SOURCE_EXTENSIONS = frozenset\(\{.*?DUMP_ARTIFACT_NAMES = frozenset\(\{.*?\}\)\n",
        new_header,
        label=rel,
    )

    new_is_config = '''def _is_config_path(path: str) -> bool:
    normalized = path.replace("\\\\", "/")
    p = Path(normalized)
    suffix = p.suffix.lower()
    if p.name in CONFIG_FILENAMES:
        return True
    if suffix in {".toml", ".yaml", ".yml", ".ini", ".cfg"}:
        return True
    if normalized.startswith("config/") and suffix in JSON_SOURCE_EXTENSIONS:
        return True
    if normalized.startswith(".github/") and suffix in {".yaml", ".yml", ".json"}:
        return True
    return False
'''

    text = replace_regex(
        text,
        r"def _is_config_path\(path: str\) -> bool:\n.*?\n\n\ndef _is_dump_artifact",
        new_is_config + "\n\ndef _is_dump_artifact",
        label=rel,
    )

    new_source_like = '''def _source_like(path: str, *, include_json: bool) -> bool:
    p = Path(path)
    suffix = p.suffix.lower()
    name = p.name

    if name in CONFIG_FILENAMES:
        return True

    if _is_config_path(path):
        return True

    if suffix in SOURCE_EXTENSIONS:
        return True

    if suffix in JSON_SOURCE_EXTENSIONS:
        return bool(include_json)

    return False
'''

    text = replace_regex(
        text,
        r"def _source_like\(path: str, \*, include_json: bool\) -> bool:\n.*?\n\n\ndef _language",
        new_source_like + "\n\ndef _language",
        label=rel,
    )

    new_language = '''def _language(path: str) -> str:
    suffix = Path(path).suffix.lower()
    mapping = {
        ".py": "python",
        ".pyi": "python",
        ".pyw": "python",
        ".r": "r",
        ".rmd": "rmarkdown",
        ".qmd": "quarto",
        ".md": "markdown",
        ".rst": "rst",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".jsonl": "jsonl",
        ".ini": "ini",
        ".cfg": "cfg",
        ".ps1": "powershell",
        ".psm1": "powershell",
        ".bat": "batch",
        ".cmd": "batch",
        ".sh": "shell",
        ".sql": "sql",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".css": "css",
        ".scss": "scss",
        ".html": "html",
    }
    if Path(path).name == ".gitignore":
        return "gitignore"
    if Path(path).name == ".dockerignore":
        return "dockerignore"
    return mapping.get(suffix, suffix.strip(".") or "text")
'''

    text = replace_regex(
        text,
        r"def _language\(path: str\) -> str:\n.*?\n\n\ndef _tree",
        new_language + "\n\ndef _tree",
        label=rel,
    )

    write(rel, text)


def write_tests() -> None:
    write(
        "tests/test_source_universe_semantics.py",
        r'''
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codebase_lens.core.paths import is_hard_excluded_relative


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) if not current else str(SRC) + os.pathsep + current
    return env


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _run_cbl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def _make_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is required for the source-universe integration test")

    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, check=True)

    _write(repo / ".gitignore", ".codecontext/\n")
    _write(repo / "pyproject.toml", "[project]\nname = 'target'\nversion = '0.0.0'\n")
    _write(repo / "src" / "demo_pkg" / "__init__.py", "")
    _write(repo / "src" / "demo_pkg" / "output" / "bundle.py", "def build_bundle() -> dict:\n    return {'ok': True}\n")
    _write(repo / "src" / "demo_pkg" / "data" / "transforms.py", "def transform() -> int:\n    return 1\n")
    _write(repo / "src" / "demo_pkg" / "r_scripts" / "fetch.R", "cat('source R bridge')\n")
    _write(repo / "scripts" / "check_r.R", "cat('script source')\n")
    _write(repo / "config" / "intents" / "smoke.json", json.dumps({"intent": "smoke"}))
    _write(repo / "config" / "registries" / "seed.jsonl", '{"id":"seed"}\n')
    _write(repo / "tests" / "test_bundle.py", "from demo_pkg.output.bundle import build_bundle\n\ndef test_build_bundle():\n    assert build_bundle()['ok']\n")
    _write(repo / "tests" / "fixtures" / "payload.json", json.dumps({"fixture": True}))

    # These are tracked but still must be excluded because they are top-level generated/data roots.
    _write(repo / "output" / "generated.py", "def generated():\n    return 'no'\n")
    _write(repo / "data" / "script.py", "def data_lake_script():\n    return 'no'\n")

    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=True)
    return repo


def _file_headings(markdown: str) -> set[str]:
    return set(re.findall(r"^### FILE: `([^`]+)`", markdown, flags=re.MULTILINE))


def test_hard_exclusion_does_not_reject_source_package_output_modules() -> None:
    assert not is_hard_excluded_relative("src/demo_pkg/output/bundle.py")
    assert not is_hard_excluded_relative("src/demo_pkg/data/transforms.py")
    assert not is_hard_excluded_relative("src/demo_pkg/r_scripts/fetch.R")
    assert is_hard_excluded_relative("output/generated.py")
    assert is_hard_excluded_relative("data/script.py")
    assert is_hard_excluded_relative("src/demo_pkg/output/model.parquet")


def test_dump_includes_polyglot_source_config_json_and_protected_package_dirs(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = _run_cbl("dump", "--repo", str(repo), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    dump_path = repo / ".codecontext" / "latest" / "codebase_dump.md"
    index_path = repo / ".codecontext" / "latest" / "codebase_dump_index.json"
    assert dump_path.is_file()
    assert index_path.is_file()

    markdown = dump_path.read_text(encoding="utf-8")
    headings = _file_headings(markdown)

    expected = {
        "src/demo_pkg/output/bundle.py",
        "src/demo_pkg/data/transforms.py",
        "src/demo_pkg/r_scripts/fetch.R",
        "scripts/check_r.R",
        "config/intents/smoke.json",
        "config/registries/seed.jsonl",
        "tests/test_bundle.py",
    }
    missing = expected - headings
    assert not missing, f"missing dumped source headings: {sorted(missing)}"

    forbidden = {
        "output/generated.py",
        "data/script.py",
        "tests/fixtures/payload.json",
    }
    leaked = forbidden & headings
    assert not leaked, f"unexpected dumped headings: {sorted(leaked)}"

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    indexed_paths = {item["path"] for item in payload["files"]}
    assert expected <= indexed_paths
    assert not (forbidden & indexed_paths)

    assert "Language: `r`" in markdown
    assert "src/demo_pkg/output/bundle.py" not in {
        item["path"]
        for item in payload.get("omitted_files", [])
        if item.get("reason") == "hard_excluded"
    }


def test_dump_include_json_expands_non_config_json(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = _run_cbl("dump", "--repo", str(repo), "--include-json", "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr

    markdown = (repo / ".codecontext" / "latest" / "codebase_dump.md").read_text(encoding="utf-8")
    headings = _file_headings(markdown)

    assert "tests/fixtures/payload.json" in headings
    assert "output/generated.py" not in headings
''',
    )


def write_audit() -> None:
    write(
        "scripts/dev/audits/audit_phase32_source_universe_semantics.py",
        r'''
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def env() -> dict[str, str]:
    root = repo_root()
    payload = os.environ.copy()
    current = payload.get("PYTHONPATH", "")
    src = str(root / "src")
    payload["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return payload


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env(), text=True, capture_output=True, check=False, timeout=60)


def file_headings(markdown: str) -> set[str]:
    return set(re.findall(r"^### FILE: `([^`]+)`", markdown, flags=re.MULTILINE))


def make_target_repo(base: Path) -> Path:
    if shutil.which("git") is None:
        raise SystemExit("git is required for this audit")

    target = base / "target"
    target.mkdir()
    git = run(["git", "init"], cwd=target)
    if git.returncode != 0:
        raise SystemExit(git.stdout + git.stderr)

    write(target / ".gitignore", ".codecontext/\n")
    write(target / "pyproject.toml", "[project]\nname = 'target'\nversion = '0.0.0'\n")
    write(target / "src" / "pkg" / "__init__.py", "")
    write(target / "src" / "pkg" / "output" / "bundle.py", "def bundle():\n    return 1\n")
    write(target / "src" / "pkg" / "r_scripts" / "fetch.R", "cat('ok')\n")
    write(target / "config" / "intents" / "smoke.json", json.dumps({"intent": "smoke"}))
    write(target / "config" / "registries" / "seed.jsonl", '{"id":"seed"}\n')
    write(target / "output" / "generated.py", "def generated():\n    return 0\n")
    write(target / "data" / "script.py", "def data_script():\n    return 0\n")

    added = run(["git", "add", "."], cwd=target)
    if added.returncode != 0:
        raise SystemExit(added.stdout + added.stderr)
    return target


def assert_contains(headings: set[str], path: str) -> None:
    if path not in headings:
        raise AssertionError(f"Expected dumped file heading is absent: {path}")


def assert_absent(headings: set[str], path: str) -> None:
    if path in headings:
        raise AssertionError(f"Unexpected dumped file heading is present: {path}")


def main() -> int:
    root = repo_root()
    with tempfile.TemporaryDirectory(prefix="cbl_phase32_source_universe_") as tmp:
        target = make_target_repo(Path(tmp))

        result = run(
            [
                sys.executable,
                "-m",
                "codebase_lens",
                "dump",
                "--repo",
                str(target),
                "--no-archive",
            ],
            cwd=root,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode

        dump_path = target / ".codecontext" / "latest" / "codebase_dump.md"
        index_path = target / ".codecontext" / "latest" / "codebase_dump_index.json"

        if not dump_path.is_file():
            raise AssertionError(f"Missing dump markdown: {dump_path}")
        if not index_path.is_file():
            raise AssertionError(f"Missing dump index: {index_path}")

        headings = file_headings(dump_path.read_text(encoding="utf-8"))
        assert_contains(headings, "src/pkg/output/bundle.py")
        assert_contains(headings, "src/pkg/r_scripts/fetch.R")
        assert_contains(headings, "config/intents/smoke.json")
        assert_contains(headings, "config/registries/seed.jsonl")
        assert_absent(headings, "output/generated.py")
        assert_absent(headings, "data/script.py")

        payload = json.loads(index_path.read_text(encoding="utf-8"))
        indexed = {item["path"] for item in payload["files"]}
        if indexed != headings:
            raise AssertionError("Dump index file list does not match markdown FILE headings.")

        print("PASS: Phase 32 source universe semantics audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    )


def validate_python_files(paths: list[str]) -> None:
    for rel in paths:
        path = ROOT / rel
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            raise SystemExit(f"Syntax error after patching {rel}: {exc}") from exc


def main() -> None:
    patch_constants()
    patch_paths()
    patch_universe()
    patch_dump_report()
    write_tests()
    write_audit()

    validate_python_files(
        [
            "src/codebase_lens/core/constants.py",
            "src/codebase_lens/core/paths.py",
            "src/codebase_lens/scanners/universe.py",
            "src/codebase_lens/reports/dump.py",
            "tests/test_source_universe_semantics.py",
            "scripts/dev/audits/audit_phase32_source_universe_semantics.py",
        ]
    )

    print("Slice 027 source-universe repair applied.")
    print("CBL now preserves source code under package directories named output/data/cache/etc.")
    print("CBL dump now includes R/Rmd/Qmd source files and config JSON/JSONL by default.")
    print("Added tests/test_source_universe_semantics.py.")
    print("Added scripts/dev/audits/audit_phase32_source_universe_semantics.py.")


if __name__ == "__main__":
    main()
