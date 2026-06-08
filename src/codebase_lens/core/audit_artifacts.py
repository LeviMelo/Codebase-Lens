from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _safe_audit_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        raise ValueError("Audit artifact name cannot be empty.")
    if not cleaned.endswith(".json"):
        cleaned += ".json"
    return cleaned


def stable_audit_dir(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / ".codecontext" / "audits"


def latest_dir(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / ".codecontext" / "latest"


def write_stable_audit_report(repo_root: str | Path, name: str, payload: dict[str, Any]) -> Path:
    destination = stable_audit_dir(repo_root) / _safe_audit_name(name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def write_latest_audit_report(repo_root: str | Path, name: str, payload: dict[str, Any]) -> Path:
    destination = latest_dir(repo_root) / _safe_audit_name(name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def write_audit_report_pair(repo_root: str | Path, name: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    stable = write_stable_audit_report(repo_root, name, payload)
    latest = write_latest_audit_report(repo_root, name, payload)
    return stable, latest
