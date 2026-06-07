from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from codebase_lens.analyzers.python_ast import collect_symbols_for_file
from codebase_lens.core.models import SymbolRecord
from codebase_lens.git.diff import ChangedFile, ChangedHunk


@dataclass(frozen=True)
class ChangedSymbolRecord:
    path: str
    qualified_name: str
    name: str
    kind: str
    start_line: int
    end_line: int
    change_origin: str
    change_status: str
    touched_hunks: tuple[ChangedHunk, ...]
    confidence: str


@dataclass(frozen=True)
class ChangedSymbolResult:
    changed_symbols: tuple[ChangedSymbolRecord, ...]
    syntax_errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _is_python_path(path: str) -> bool:
    return Path(path).suffix.lower() in {".py", ".pyw", ".pyi"}


def _hunk_touches_symbol(hunk: ChangedHunk, symbol: SymbolRecord) -> bool:
    if hunk.new_count == 0:
        return False

    hunk_start = hunk.new_start
    hunk_end = hunk.new_start + max(hunk.new_count - 1, 0)

    return not (hunk_end < symbol.start_line or hunk_start > symbol.end_line)


def _touched_hunks(changed_file: ChangedFile, symbol: SymbolRecord) -> tuple[ChangedHunk, ...]:
    if changed_file.origin == "untracked":
        return changed_file.hunks

    return tuple(hunk for hunk in changed_file.hunks if _hunk_touches_symbol(hunk, symbol))


def map_changed_symbols(repo_root: str | Path, changed_files: tuple[ChangedFile, ...]) -> ChangedSymbolResult:
    root = Path(repo_root).resolve()
    records: list[ChangedSymbolRecord] = []
    syntax_errors: list[str] = []
    warnings: list[str] = []

    for changed_file in changed_files:
        if not _is_python_path(changed_file.path):
            continue
        if changed_file.status == "D":
            warnings.append(f"Deleted Python file skipped for symbol mapping: {changed_file.path}")
            continue

        target = root / changed_file.path
        if not target.is_file():
            warnings.append(f"Changed Python file does not exist in working tree: {changed_file.path}")
            continue

        analysis = collect_symbols_for_file(root, target)
        syntax_errors.extend(analysis.syntax_errors)

        for symbol in analysis.symbols:
            touched = _touched_hunks(changed_file, symbol)
            if changed_file.origin != "untracked" and not touched:
                continue

            records.append(
                ChangedSymbolRecord(
                    path=symbol.path,
                    qualified_name=symbol.qualified_name,
                    name=symbol.name,
                    kind=symbol.kind,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    change_origin=changed_file.origin,
                    change_status=changed_file.status,
                    touched_hunks=touched,
                    confidence="medium" if changed_file.origin == "untracked" else "high",
                )
            )

    records = sorted(records, key=lambda item: (item.path, item.start_line, item.qualified_name))

    return ChangedSymbolResult(
        changed_symbols=tuple(records),
        syntax_errors=tuple(syntax_errors),
        warnings=tuple(warnings),
    )


def changed_symbol_result_payload(result: ChangedSymbolResult) -> dict[str, object]:
    return {
        "changed_symbols": [asdict(record) for record in result.changed_symbols],
        "syntax_errors": list(result.syntax_errors),
        "warnings": list(result.warnings),
        "counts": {
            "total": len(result.changed_symbols),
            "classes": sum(1 for record in result.changed_symbols if record.kind == "class"),
            "functions": sum(1 for record in result.changed_symbols if record.kind == "function"),
            "methods": sum(1 for record in result.changed_symbols if record.kind == "method"),
        },
    }
