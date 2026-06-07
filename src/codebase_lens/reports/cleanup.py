from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from codebase_lens.core.paths import resolve_user_path
from codebase_lens.reports.manifest import OutputLayout, write_json


@dataclass(frozen=True)
class CleanedRunRecord:
    path: str
    action: str
    reason: str


@dataclass(frozen=True)
class CleanResult:
    out_dir: str
    runs_dir: str
    keep: int
    remove_all: bool
    deleted: tuple[CleanedRunRecord, ...]
    kept: tuple[CleanedRunRecord, ...]
    errors: tuple[CleanedRunRecord, ...]
    counts: dict[str, int]


def _safe_output_dir(repo_root: Path, out_dir: str | Path) -> Path:
    raw = Path(out_dir)
    if raw.is_absolute():
        raise ValueError("Absolute --out paths are not allowed for clean.")
    return resolve_user_path(repo_root, raw, allow_absolute=False, allow_hard_excluded=True)


def _run_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.exists():
        return []
    return sorted(
        [item for item in runs_dir.iterdir() if item.is_dir()],
        key=lambda item: (item.stat().st_mtime_ns, item.name),
        reverse=True,
    )


def _relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _delete_run(repo_root: Path, runs_dir: Path, run_dir: Path) -> CleanedRunRecord:
    resolved_runs = runs_dir.resolve()
    resolved_run = run_dir.resolve()

    try:
        resolved_run.relative_to(resolved_runs)
    except ValueError:
        return CleanedRunRecord(
            path=_relative(repo_root, run_dir),
            action="error",
            reason="refused to delete path outside runs directory",
        )

    try:
        shutil.rmtree(resolved_run)
    except OSError as exc:
        return CleanedRunRecord(
            path=_relative(repo_root, run_dir),
            action="error",
            reason=f"delete failed: {exc}",
        )

    return CleanedRunRecord(
        path=_relative(repo_root, run_dir),
        action="deleted",
        reason="matched clean policy",
    )


def clean_archives(
    repo_root: str | Path,
    *,
    out_dir: str | Path = ".codecontext",
    keep: int = 10,
    remove_all: bool = False,
) -> CleanResult:
    root = Path(repo_root).resolve()
    if keep < 0:
        raise ValueError("--keep must be >= 0.")

    output_dir = _safe_output_dir(root, out_dir)
    runs_dir = output_dir / "runs"

    runs = _run_dirs(runs_dir)

    if remove_all:
        keep_set: set[Path] = set()
    else:
        keep_set = set(runs[:keep])

    deleted: list[CleanedRunRecord] = []
    kept: list[CleanedRunRecord] = []
    errors: list[CleanedRunRecord] = []

    for run_dir in runs:
        if run_dir in keep_set:
            kept.append(
                CleanedRunRecord(
                    path=_relative(root, run_dir),
                    action="kept",
                    reason=f"within newest {keep} run(s)",
                )
            )
            continue

        record = _delete_run(root, runs_dir, run_dir)
        if record.action == "error":
            errors.append(record)
        else:
            deleted.append(record)

    return CleanResult(
        out_dir=_relative(root, output_dir),
        runs_dir=_relative(root, runs_dir),
        keep=keep,
        remove_all=remove_all,
        deleted=tuple(deleted),
        kept=tuple(kept),
        errors=tuple(errors),
        counts={
            "runs_seen": len(runs),
            "deleted": len(deleted),
            "kept": len(kept),
            "errors": len(errors),
        },
    )


def clean_result_payload(result: CleanResult) -> dict[str, object]:
    return {
        "schema": {
            "name": "cbl.clean_report",
            "version": 1,
        },
        "out_dir": result.out_dir,
        "runs_dir": result.runs_dir,
        "keep": result.keep,
        "remove_all": result.remove_all,
        "deleted": [asdict(record) for record in result.deleted],
        "kept": [asdict(record) for record in result.kept],
        "errors": [asdict(record) for record in result.errors],
        "counts": dict(result.counts),
    }


def write_clean_report(layout: OutputLayout, result: CleanResult) -> Path:
    target = layout.latest_dir / "clean_report.json"
    write_json(target, clean_result_payload(result))
    return target
