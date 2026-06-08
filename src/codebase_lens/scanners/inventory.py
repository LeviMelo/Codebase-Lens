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


def _omitted_files(result: object) -> tuple[object, ...]:
    value = getattr(result, "omitted_files", None)
    if value is None:
        value = getattr(result, "omissions", ())
    return tuple(value or ())


def file_universe_to_inventory(result) -> dict[str, Any]:
    """Convert a scanner FileUniverseResult into a serializable inventory payload.

    Scanner semantics use the canonical name ``omitted_files``. The legacy
    ``omissions`` key remains in emitted JSON for one compatibility cycle.
    """

    omitted = [_jsonable(record) for record in _omitted_files(result)]

    return {
        "schema": {
            "name": "cbl.file_inventory",
            "version": 2,
        },
        "repo": {
            "root": "<redacted>",
            "root_redacted_for_ai": True,
        },
        "counts": dict(getattr(result, "counts", {})),
        "redaction": _jsonable(getattr(result, "redaction", None)),
        "files": [_jsonable(record) for record in getattr(result, "included_files", ())],
        "omitted_files": omitted,
        "omissions": omitted,
        "warnings": list(getattr(result, "warnings", ())),
    }
