from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class ModuleDocstringRecord:
    path: str
    start_line: int | None
    end_line: int | None
    summary: str | None
    text: str | None
    confidence: str


@dataclass(frozen=True)
class ModuleDocstringResult:
    records: tuple[ModuleDocstringRecord, ...]
    syntax_errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _summary(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:240]
    return None


def _module_docstring_span(tree: ast.Module) -> tuple[int | None, int | None]:
    if not tree.body:
        return (None, None)
    first = tree.body[0]
    if not isinstance(first, ast.Expr):
        return (None, None)
    value = first.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        start = int(getattr(first, "lineno", 1))
        end = int(getattr(first, "end_lineno", start))
        return (start, end)
    return (None, None)


def collect_module_docstring_for_file(repo_root: str | Path, file_path: str | Path) -> tuple[ModuleDocstringRecord | None, tuple[str, ...]]:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)
    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return None, (f"{relative}: skipped: {read_result.skipped_reason}",)
    source = read_result.text or ""
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        return None, (f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}",)
    text = ast.get_docstring(tree)
    start, end = _module_docstring_span(tree)
    return ModuleDocstringRecord(path=relative, start_line=start, end_line=end, summary=_summary(text), text=text, confidence="high" if text else "exact_no_module_docstring"), ()


def collect_module_docstrings(repo_root: str | Path, python_files: list[str | Path]) -> ModuleDocstringResult:
    root = Path(repo_root).resolve()
    records: list[ModuleDocstringRecord] = []
    errors: list[str] = []
    for path in sorted(str(item).replace("\\", "/") for item in python_files):
        record, file_errors = collect_module_docstring_for_file(root, root / path)
        errors.extend(file_errors)
        if record is not None:
            records.append(record)
    return ModuleDocstringResult(records=tuple(sorted(records, key=lambda item: item.path)), syntax_errors=tuple(errors), warnings=())


def module_docstring_payload(result: ModuleDocstringResult) -> dict[str, Any]:
    return {
        "schema": {"name": "cbl.module_docstrings", "version": 1},
        "module_docstrings": [asdict(record) for record in result.records],
        "syntax_errors": list(result.syntax_errors),
        "warnings": list(result.warnings),
        "counts": {"files": len(result.records), "with_docstrings": sum(1 for record in result.records if record.text), "without_docstrings": sum(1 for record in result.records if not record.text), "syntax_errors": len(result.syntax_errors)},
    }
