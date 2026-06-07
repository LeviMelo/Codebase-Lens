from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from codebase_lens.core.models import CommandRecord, ImportRecord, RouteRecord, SymbolRecord
from codebase_lens.git.diff import ChangedFileSet
from codebase_lens.reports.manifest import write_json


def write_json_report(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path)
    write_json(target, payload)
    return target


def symbol_records_payload(records: tuple[SymbolRecord, ...], *, syntax_errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "symbols": [asdict(record) for record in records],
        "syntax_errors": syntax_errors or [],
        "counts": {
            "total": len(records),
            "classes": sum(1 for record in records if record.kind == "class"),
            "functions": sum(1 for record in records if record.kind == "function"),
            "methods": sum(1 for record in records if record.kind == "method"),
        },
    }


def import_records_payload(records: tuple[ImportRecord, ...], *, syntax_errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "imports": [asdict(record) for record in records],
        "syntax_errors": syntax_errors or [],
        "counts": {
            "total": len(records),
            "resolved_project_imports": sum(1 for record in records if record.resolved_project_path),
            "star_imports": sum(1 for record in records if record.name == "*"),
        },
    }


def command_records_payload(records: tuple[CommandRecord, ...], *, syntax_errors: list[str] | None = None, limitations: list[str] | None = None) -> dict[str, Any]:
    return {
        "commands": [asdict(record) for record in records],
        "syntax_errors": syntax_errors or [],
        "limitations": limitations or [],
        "counts": {
            "total": len(records),
            "argparse": sum(1 for record in records if record.framework == "argparse"),
            "click": sum(1 for record in records if record.framework == "click"),
            "typer": sum(1 for record in records if record.framework == "typer"),
            "unknown": sum(1 for record in records if record.framework == "unknown"),
        },
    }


def route_records_payload(records: tuple[RouteRecord, ...], *, syntax_errors: list[str] | None = None, limitations: list[str] | None = None) -> dict[str, Any]:
    return {
        "routes": [asdict(record) for record in records],
        "syntax_errors": syntax_errors or [],
        "limitations": limitations or [],
        "counts": {
            "total": len(records),
            "fastapi": sum(1 for record in records if record.framework == "fastapi"),
            "flask": sum(1 for record in records if record.framework == "flask"),
            "unknown": sum(1 for record in records if record.framework == "unknown"),
        },
    }


def changed_files_payload(result: ChangedFileSet) -> dict[str, Any]:
    return {
        "changed_files": [asdict(record) for record in result.changed_files],
        "counts": dict(result.counts),
        "warnings": list(result.warnings),
    }
