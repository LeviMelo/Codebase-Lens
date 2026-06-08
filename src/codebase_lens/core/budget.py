from __future__ import annotations

from typing import Any

ESTIMATION_METHOD = "heuristic: max(1, file_size_bytes // 4)"


def estimate_tokens_for_bytes(size_bytes: int | None) -> int:
    size = int(size_bytes or 0)
    if size <= 0:
        return 1
    return max(1, size // 4)


def estimate_tokens_for_text(text: str) -> int:
    return max(1, len(text) // 4)


def focus_hits_for_path(path: str, focus_terms: tuple[str, ...]) -> int:
    if not focus_terms:
        return 0
    lowered = path.lower()
    return sum(1 for term in focus_terms if term.lower() in lowered)


def ranked_budget_file_records(
    included_files: object,
    *,
    focus_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    ranked_files: list[dict[str, Any]] = []

    for record in list(included_files or ()):
        path = str(getattr(record, "path", ""))
        size_bytes = int(getattr(record, "size_bytes", 0) or 0)
        estimated_tokens = estimate_tokens_for_bytes(size_bytes)
        focus_hits = focus_hits_for_path(path, focus_terms)

        ranked_files.append(
            {
                "path": path,
                "size_bytes": size_bytes,
                "estimated_tokens": estimated_tokens,
                "focus_hits": focus_hits,
                "priority_score": focus_hits * 1000 + max(0, 100000 - size_bytes),
            }
        )

    ranked_files.sort(key=lambda item: (-int(item["priority_score"]), str(item["path"])))
    return ranked_files


def build_budget_report_payload(
    included_files: object,
    *,
    budget: int,
    focus_terms: tuple[str, ...],
    changed_only: bool,
    python_files: list[str],
) -> dict[str, Any]:
    ranked_files = ranked_budget_file_records(included_files, focus_terms=focus_terms)
    total_estimated_tokens = sum(int(item["estimated_tokens"]) for item in ranked_files)

    return {
        "schema": {
            "name": "cbl.budget_report",
            "version": 2,
        },
        "scope": "changed" if changed_only else "full",
        "requested_budget_tokens": budget,
        "focus_terms": list(focus_terms),
        "estimation_method": ESTIMATION_METHOD,
        "total_estimated_file_tokens": total_estimated_tokens,
        "budget_pressure": "over_budget" if total_estimated_tokens > budget else "within_budget",
        "python_files_analyzed": python_files,
        "ranked_files": ranked_files[:250],
        "counts": {
            "ranked_files": len(ranked_files),
            "python_files_analyzed": len(python_files),
            "focus_terms": len(focus_terms),
        },
    }
