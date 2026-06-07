from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def file_universe_to_inventory(result) -> dict[str, Any]:
    """Convert a scanner FileUniverseResult into a serializable inventory payload.

    This module intentionally does not write files and does not import report-layer
    helpers. Scanner modules own file-universe semantics; report modules own output
    persistence.
    """

    return {
        "schema": {
            "name": "cbl.file_inventory",
            "version": 1,
        },
        "repo": {
            "root": "<redacted>",
            "root_redacted_for_ai": True,
        },
        "counts": dict(getattr(result, "counts", {})),
        "redaction": _jsonable(getattr(result, "redaction", None)),
        "files": [_jsonable(record) for record in getattr(result, "included_files", ())],
        "omissions": [_jsonable(record) for record in getattr(result, "omissions", ())],
        "warnings": list(getattr(result, "warnings", ())),
    }
