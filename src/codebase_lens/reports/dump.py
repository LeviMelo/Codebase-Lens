from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from codebase_lens.analyzers.docstrings import collect_module_docstrings, module_docstring_payload
from codebase_lens.analyzers.python_ast import collect_python_symbols, flatten_symbol_results
from codebase_lens.core.hashing import sha256_file
from codebase_lens.core.paths import resolve_user_path, to_posix_relative
from codebase_lens.core.redaction import redact_text
from codebase_lens.core.textio import read_text_with_policy
from codebase_lens.reports.json import symbol_records_payload, write_json_report
from codebase_lens.reports.manifest import OutputLayout
from codebase_lens.scanners.universe import discover_file_universe


SOURCE_EXTENSIONS = frozenset(
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


@dataclass(frozen=True)
class DumpBundleResult:
    outputs: dict[str, str]
    counts: dict[str, int]
    warnings: tuple[str, ...]
    file_universe: dict[str, Any]
    redaction: dict[str, Any]


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith("tests/") or "/tests/" in f"/{normalized}/" or Path(normalized).name.startswith("test_")


def _is_doc_path(path: str) -> bool:
    return Path(path).suffix.lower() in {".md", ".rst"}


def _is_config_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    p = Path(normalized)
    return (
        normalized.startswith("config/")
        or p.name in CONFIG_FILENAMES
        or p.suffix.lower() in {".toml", ".yaml", ".yml", ".ini", ".cfg", ".json", ".jsonl"}
    )

def _is_dump_artifact(path: str) -> bool:
    name = Path(path).name.lower()
    normalized = path.replace("\\", "/").lower()
    return name in DUMP_ARTIFACT_NAMES or "codebase_dump" in name or "cbl_dump" in name or normalized.startswith(".codecontext/")


def _source_like(path: str, *, include_json: bool) -> bool:
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


def _language(path: str) -> str:
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
    return mapping.get(lowered, "text")

def _tree(paths: list[str]) -> str:
    rendered: list[str] = []
    seen: set[str] = set()
    for path in sorted(paths):
        parts = path.split("/")
        for index, part in enumerate(parts):
            marker_path = "/".join(parts[: index + 1])
            if marker_path in seen:
                continue
            seen.add(marker_path)
            prefix = "  " * index
            marker = "└─ " if index == len(parts) - 1 else "├─ "
            rendered.append(f"{prefix}{marker}{part}")
    return "\n".join(rendered)


def _numbered(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return "0001: "
    width = max(4, len(str(len(lines))))
    return "\n".join(f"{index:0{width}d}: {line}" for index, line in enumerate(lines, start=1))


def _normalize_scope_paths(repo_root: Path, raw_scope_paths: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Normalize repo-relative dump scope paths.

    Scope paths are explicit filters over the already-safe file universe. They do
    not redefine the repository root and they do not bypass hard exclusions.
    """

    if not raw_scope_paths:
        return ()

    values: list[str] = []
    for raw in raw_scope_paths:
        text = str(raw).strip()
        if not text:
            continue
        target = resolve_user_path(repo_root, text, allow_absolute=False, allow_hard_excluded=False)
        if not target.exists():
            raise ValueError(f"Dump scope does not exist: {text}")
        relative = to_posix_relative(repo_root, target).strip("/").replace("\\", "/")
        if relative in {"", "."}:
            continue
        if relative not in values:
            values.append(relative)

    return tuple(values)


def _record_in_scope(path: str, scope_paths: tuple[str, ...]) -> bool:
    if not scope_paths:
        return True
    normalized = path.replace("\\", "/").strip("/")
    for scope in scope_paths:
        if normalized == scope or normalized.startswith(scope.rstrip("/") + "/"):
            return True
    return False


def _filter_records(
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

    return selected, omissions

def _render_symbol_index(symbols: tuple[Any, ...]) -> list[str]:
    lines: list[str] = []
    by_path: dict[str, list[Any]] = {}
    for symbol in symbols:
        by_path.setdefault(symbol.path, []).append(symbol)
    for path in sorted(by_path):
        lines.extend([f"### `{path}`", ""])
        for symbol in sorted(by_path[path], key=lambda item: (item.start_line, item.qualified_name)):
            evidence = f"{symbol.path}:L{symbol.start_line}-L{symbol.end_line}"
            lines.append(f"- SYMBOL: `{symbol.qualified_name}` — `{symbol.kind}` — `{evidence}`")
            if symbol.signature:
                lines.append(f"  - Signature: `{symbol.signature}`")
            if symbol.docstring_summary:
                lines.append(f"  - Docstring: {symbol.docstring_summary}")
        lines.append("")
    return lines or ["No Python symbols were detected.", ""]


def _render_docstring_index(module_payload: dict[str, Any]) -> list[str]:
    records = module_payload.get("module_docstrings", [])
    lines: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        summary = record.get("summary")
        path = record.get("path")
        if not path or not summary:
            continue
        start = record.get("start_line") or "?"
        end = record.get("end_line") or start
        lines.extend([f"### `{path}`", "", f"- Evidence: `{path}:L{start}-L{end}`", f"- Summary: {summary}", ""])
    return lines or ["No module docstrings were detected.", ""]


def _render_source_file(repo_root: Path, path: str, *, line_numbers: bool, max_file_bytes: int) -> tuple[str, dict[str, Any], dict[str, Any]]:
    target = repo_root / path
    read_result = read_text_with_policy(target, max_file_bytes=max_file_bytes)
    if read_result.skipped_reason:
        raise ValueError(f"Selected dump file was unexpectedly skipped: {path}: {read_result.skipped_reason}")
    raw = read_result.text or ""
    redacted = redact_text(raw)
    body = _numbered(redacted.text) if line_numbers else redacted.text.rstrip("\n")
    language = _language(path)
    rendered = "\n".join([f"### FILE: `{path}`", "", f"Language: `{language}`", f"Lines: {len(raw.splitlines())}", f"SHA256: `{sha256_file(target)}`", "", f"~~~~{language}", body, "~~~~", ""])
    file_payload = {"path": path, "language": language, "size_bytes": read_result.size_bytes, "line_count": len(raw.splitlines()), "sha256": sha256_file(target), "redacted": bool(redacted.stats.redacted_occurrences_count)}
    redaction_payload = {"occurrences": redacted.stats.redacted_occurrences_count, "patterns_hit": list(redacted.stats.patterns_hit)}
    return rendered, file_payload, redaction_payload


def write_codebase_dump(layout: OutputLayout, repo_root: str | Path, *, max_file_bytes: int, tracked_only: bool = True, include_untracked: bool = False, include_tests: bool = True, include_docs: bool = True, include_config: bool = True, include_json: bool = False, out_file: str | None = None, output_format: str = "markdown", line_numbers: bool = True, max_total_bytes: int = 0, scope_paths: tuple[str, ...] | list[str] | None = None) -> DumpBundleResult:
    root = Path(repo_root).resolve()
    universe = discover_file_universe(root, max_file_bytes=max_file_bytes)
    normalized_scope_paths = _normalize_scope_paths(root, scope_paths)
    scoped_records = tuple(
        record
        for record in universe.included_files
        if _record_in_scope(str(getattr(record, "path", "")), normalized_scope_paths)
    )
    if normalized_scope_paths and not scoped_records:
        raise ValueError(f"Dump scope selected no scan-eligible files: {', '.join(normalized_scope_paths)}")

    selected, dump_omissions = _filter_records(scoped_records, tracked_only=tracked_only, include_untracked=include_untracked, include_tests=include_tests, include_docs=include_docs, include_config=include_config, include_json=include_json)
    selected_paths = [record.path for record in selected]
    if normalized_scope_paths and not selected_paths:
        raise ValueError(f"Dump scope selected no source-like files after filters: {', '.join(normalized_scope_paths)}")
    source_bytes = sum(int(getattr(record, "size_bytes", 0) or 0) for record in selected)
    if max_total_bytes and source_bytes > max_total_bytes:
        raise ValueError(f"Dump would emit {source_bytes} source bytes, exceeding --max-total-bytes={max_total_bytes}. Narrow selection or raise the cap.")
    python_files = [path for path in selected_paths if Path(path).suffix.lower() in {".py", ".pyw", ".pyi"}]
    symbol_results = collect_python_symbols(root, python_files)
    symbols = flatten_symbol_results(symbol_results)
    symbol_payload = symbol_records_payload(symbols, syntax_errors=[])
    module_docstrings = collect_module_docstrings(root, python_files)
    module_payload = module_docstring_payload(module_docstrings)
    scope_label = ", ".join(normalized_scope_paths) if normalized_scope_paths else "<repository>"
    lines: list[str] = ["# CBL Codebase Dump", "", f"Repository: `{root.name}`", f"Scope: `{scope_label}`", f"Format: `{output_format}`", f"Tracked only: `{str(tracked_only).lower()}`", f"Include untracked: `{str(include_untracked).lower()}`", f"Line numbers: `{str(line_numbers).lower()}`", "Source truncation: `disabled for included files`", "Safety: hard exclusions and redaction enabled", "", "## Counts", "", f"- Included source files: {len(selected_paths)}", f"- Python files analyzed: {len(python_files)}", f"- Symbols indexed: {len(symbols)}", f"- Source bytes emitted: {source_bytes}", f"- Dump-filter omissions: {len(dump_omissions)}", f"- Scanner omissions: {len(universe.omitted_files)}", "", "## File Tree", "", "~~~~text", _tree(selected_paths) or "<empty>", "~~~~", "", "## Module Docstring Index", "", *_render_docstring_index(module_payload), "## Symbol Index", "", *_render_symbol_index(symbols), "## Omitted Files", ""]
    all_omissions: list[dict[str, Any]] = [*dump_omissions]
    for item in universe.omitted_files:
        all_omissions.append(asdict(item))
    if all_omissions:
        lines.extend(["| Path | Reason | Category | Size |", "|---|---|---:|---:|"])
        for item in sorted(all_omissions, key=lambda value: str(value.get("path"))):
            lines.append(f"| `{item.get('path', '')}` | `{item.get('reason', '')}` | `{item.get('category', '')}` | {item.get('size_bytes', '') or ''} |")
    else:
        lines.append("No files were omitted.")
    lines.extend(["", "## Source Files", ""])
    files_payload: list[dict[str, Any]] = []
    redacted_files = 0
    redacted_occurrences = 0
    patterns_hit: set[str] = set()
    warnings: list[str] = list(universe.warnings)
    for path in selected_paths:
        rendered, file_payload, redaction_payload = _render_source_file(root, path, line_numbers=line_numbers, max_file_bytes=max_file_bytes)
        lines.append(rendered.rstrip("\n"))
        lines.append("")
        files_payload.append(file_payload)
        occurrences = int(redaction_payload.get("occurrences", 0) or 0)
        if occurrences:
            redacted_files += 1
            redacted_occurrences += occurrences
            patterns_hit.update(str(item) for item in redaction_payload.get("patterns_hit", []))
    dump_text = "\n".join(lines).rstrip() + "\n"
    dump_name = "codebase_dump.md" if output_format == "markdown" else "codebase_dump.txt"
    (layout.latest_dir / dump_name).write_text(dump_text, encoding="utf-8", newline="\n")
    index_payload = {"schema": {"name": "cbl.codebase_dump", "version": 2}, "mode": "tracked_source_dump", "scope_paths": list(normalized_scope_paths), "line_numbers": line_numbers, "source_truncation": "disabled_for_included_files", "files": files_payload, "module_docstrings": module_payload, "symbols": symbol_payload, "omitted_files": all_omissions, "counts": {"included_files": len(selected_paths), "python_files_analyzed": len(python_files), "symbols": len(symbols), "source_bytes": source_bytes, "dump_filter_omissions": len(dump_omissions), "scanner_omissions": len(universe.omitted_files)}, "warnings": warnings}
    write_json_report(layout.latest_dir / "codebase_dump_index.json", index_payload)
    outputs = {"codebase_dump_md": f".codecontext/latest/{dump_name}", "codebase_dump_index_json": ".codecontext/latest/codebase_dump_index.json"}
    if out_file:
        target = resolve_user_path(root, out_file, allow_absolute=False, allow_hard_excluded=False)
        rel = to_posix_relative(root, target)
        if _is_dump_artifact(rel):
            raise ValueError("--out-file may not target an existing or recursive dump artifact name.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dump_text, encoding="utf-8", newline="\n")
        outputs["codebase_dump_copy"] = rel
    redaction = {"enabled": True, "redacted_files_count": redacted_files + universe.counts.get("redacted_file_count", 0), "redacted_occurrences_count": redacted_occurrences + universe.redaction.redacted_occurrences_count, "patterns_hit": sorted(set(patterns_hit) | set(universe.redaction.patterns_hit))}
    return DumpBundleResult(outputs=outputs, counts=dict(index_payload["counts"]), warnings=tuple(warnings), file_universe=universe.manifest_counts(), redaction=redaction)
