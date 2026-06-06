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
