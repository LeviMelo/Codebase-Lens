from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codebase_lens import TOOL_NAME, __version__
from codebase_lens.core.redaction import redact_jsonable


@dataclass(frozen=True)
class OutputLayout:
    codecontext_dir: Path
    latest_dir: Path
    runs_dir: Path
    run_dir: Path | None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_run_stamp() -> str:
    return utc_now_iso().replace(":", "-")


def _clear_directory(directory: Path) -> None:
    if not directory.exists():
        return
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def prepare_output_layout(
    repo_root: str | Path,
    out_dir: str | Path = ".codecontext",
    *,
    archive: bool = True,
    clear_latest: bool = True,
) -> OutputLayout:
    root = Path(repo_root).resolve()
    requested = Path(out_dir)

    codecontext_dir = requested if requested.is_absolute() else root / requested
    codecontext_dir = codecontext_dir.resolve()

    latest_dir = codecontext_dir / "latest"
    runs_dir = codecontext_dir / "runs"

    latest_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    if clear_latest:
        _clear_directory(latest_dir)

    run_dir = None
    if archive:
        base = runs_dir / utc_run_stamp()
        run_dir = base
        suffix = 1
        while run_dir.exists():
            run_dir = Path(f"{base}-{suffix}")
            suffix += 1
        run_dir.mkdir(parents=True, exist_ok=False)

    return OutputLayout(
        codecontext_dir=codecontext_dir,
        latest_dir=latest_dir,
        runs_dir=runs_dir,
        run_dir=run_dir,
    )

def _sanitize_argv(argv: list[str]) -> list[str]:
    sanitized: list[str] = []
    redact_next = False
    value_options = {"--repo", "--out", "--spec"}
    for item in argv:
        if redact_next:
            sanitized.append("<PATH_OR_SPEC_REDACTED>")
            redact_next = False
            continue
        if item in value_options:
            sanitized.append(item)
            redact_next = True
            continue
        if item.startswith("--repo="):
            sanitized.append("--repo=<PATH_OR_SPEC_REDACTED>")
            continue
        if item.startswith("--out="):
            sanitized.append("--out=<PATH_OR_SPEC_REDACTED>")
            continue
        if item.startswith("--spec="):
            sanitized.append("--spec=<PATH_OR_SPEC_REDACTED>")
            continue
        sanitized.append(str(redact_jsonable(item)))
    return sanitized

def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(redact_jsonable(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def copy_latest_to_run(layout: OutputLayout) -> None:
    if layout.run_dir is None:
        return

    for source in sorted(layout.latest_dir.iterdir()):
        target = layout.run_dir / source.name
        if source.is_file():
            shutil.copy2(source, target)


def build_manifest(
    *,
    repo_root: Path,
    repo_name: str,
    root_redacted_for_ai: bool,
    is_git_repo: bool,
    git: dict[str, Any],
    argv: list[str],
    subcommand: str,
    budget: int,
    focus: list[str],
    outputs: dict[str, str],
    redaction: dict[str, Any],
    file_universe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tool": {
            "name": TOOL_NAME,
            "command": "cbl",
            "version": __version__,
        },
        "generated_at_utc": utc_now_iso(),
        "repo": {
            "name": repo_name,
            "root": "<redacted>" if root_redacted_for_ai else str(repo_root.resolve()),
            "root_redacted_for_ai": root_redacted_for_ai,
            "is_git_repo": is_git_repo,
            "detected_project_types": ["python"] if (repo_root / "pyproject.toml").exists() else [],
            "primary_language": "python" if (repo_root / "pyproject.toml").exists() else None,
        },
        "git": git,
        "command": {
            "argv": _sanitize_argv(argv),
            "argv_redacted_for_ai": True,
            "subcommand": subcommand,
            "budget": budget,
            "focus": focus,
            "changed_only": "--changed" in argv,
        },
        "file_universe": file_universe
        or {
            "tracked_included_count": 0,
            "untracked_included_count": 0,
            "ignored_count": 0,
            "hard_excluded_count": 0,
            "large_skipped_count": 0,
            "binary_skipped_count": 0,
            "decode_failed_count": 0,
            "redacted_file_count": 0,
            "included_count": 0,
        },
        "safety": {
            "redaction_enabled": redaction.get("enabled", True),
            "redacted_files_count": redaction.get("redacted_files_count", 0),
            "redacted_occurrences_count": redaction.get("redacted_occurrences_count", 0),
            "patterns_hit": redaction.get("patterns_hit", []),
            "absolute_paths_in_ai_reports": False,
        },
        "outputs": outputs,
    }


def write_manifest_bundle(layout: OutputLayout, manifest: dict[str, Any]) -> Path:
    manifest_path = layout.latest_dir / "manifest.json"
    write_json(manifest_path, manifest)
    if layout.run_dir is not None:
        write_json(layout.run_dir / "manifest.json", manifest)
    return manifest_path
