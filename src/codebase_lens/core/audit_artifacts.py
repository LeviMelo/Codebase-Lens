from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


WINDOWS_TEMP_RE = re.compile(
    r"(?i)[A-Z]:\\Users\\[^\\/\r\n\t\"']+\\AppData\\Local\\Temp(?:\\[^,\r\n\"']*)?"
)
WINDOWS_USER_RE = re.compile(
    r"(?i)[A-Z]:\\Users\\[^\\/\r\n\t\"']+"
)
POSIX_TEMP_RE = re.compile(
    r"(?:(?:/tmp|/var/tmp|/private/var/folders)/[^,\r\n\"']*)"
)


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


def _path_text_variants(path: str | Path | None) -> tuple[str, ...]:
    if path is None:
        return ()

    raw = str(path)
    if not raw:
        return ()

    variants = {
        raw,
        raw.replace("\\", "/"),
        raw.replace("/", "\\"),
    }

    try:
        resolved = str(Path(raw).expanduser().resolve(strict=False))
        variants.add(resolved)
        variants.add(resolved.replace("\\", "/"))
        variants.add(resolved.replace("/", "\\"))
    except OSError:
        pass

    return tuple(sorted((item for item in variants if item), key=len, reverse=True))


def _specific_sensitive_path_replacements() -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []

    for value, placeholder in (
        (tempfile.gettempdir(), "<TEMP_DIR>"),
        (os.environ.get("TMP"), "<TEMP_DIR>"),
        (os.environ.get("TEMP"), "<TEMP_DIR>"),
        (os.environ.get("USERPROFILE"), "<USER_HOME>"),
        (os.environ.get("HOME"), "<USER_HOME>"),
        (Path.home(), "<USER_HOME>"),
    ):
        for variant in _path_text_variants(value):
            candidates.append((variant, placeholder))

    deduped: dict[str, str] = {}
    for needle, placeholder in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
        deduped.setdefault(needle, placeholder)

    return tuple(deduped.items())


def sanitize_audit_string(value: str) -> str:
    sanitized = value

    for needle, placeholder in _specific_sensitive_path_replacements():
        if needle:
            sanitized = sanitized.replace(needle, placeholder)

    sanitized = WINDOWS_TEMP_RE.sub("<TEMP_DIR>", sanitized)
    sanitized = POSIX_TEMP_RE.sub("<TEMP_DIR>", sanitized)
    sanitized = WINDOWS_USER_RE.sub("<USER_HOME>", sanitized)

    return sanitized


def sanitize_audit_payload(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_audit_string(value)

    if isinstance(value, Path):
        return sanitize_audit_string(str(value))

    if isinstance(value, dict):
        return {
            str(key): sanitize_audit_payload(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [sanitize_audit_payload(item) for item in value]

    if isinstance(value, tuple):
        return [sanitize_audit_payload(item) for item in value]

    if isinstance(value, set):
        return sorted(sanitize_audit_payload(item) for item in value)

    return value


def audit_payload_contains_local_paths(value: Any) -> bool:
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False)

    forbidden_fragments = [
        "AppData\\\\Local\\\\Temp",
        "AppData/Local/Temp",
        "C:\\\\Users\\\\",
        "C:/Users/",
        "/tmp/",
        "/var/tmp/",
        "/private/var/folders/",
    ]

    home = str(Path.home())
    temp_dir = tempfile.gettempdir()

    for variant in [*_path_text_variants(home), *_path_text_variants(temp_dir)]:
        if variant and variant in blob:
            return True

    return any(fragment in blob for fragment in forbidden_fragments)


def write_stable_audit_report(repo_root: str | Path, name: str, payload: dict[str, Any]) -> Path:
    destination = stable_audit_dir(repo_root) / _safe_audit_name(name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_audit_payload(payload)
    destination.write_text(
        json.dumps(sanitized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def write_latest_audit_report(repo_root: str | Path, name: str, payload: dict[str, Any]) -> Path:
    destination = latest_dir(repo_root) / _safe_audit_name(name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_audit_payload(payload)
    destination.write_text(
        json.dumps(sanitized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def write_audit_report_pair(repo_root: str | Path, name: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    stable = write_stable_audit_report(repo_root, name, payload)
    latest = write_latest_audit_report(repo_root, name, payload)
    return stable, latest
