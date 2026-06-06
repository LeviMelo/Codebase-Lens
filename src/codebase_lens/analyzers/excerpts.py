from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.constants import DEFAULT_MAX_EXCERPT_BYTES
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.redaction import RedactionStats, redact_text
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class FileExcerpt:
    path: str
    start_line: int
    end_line: int
    text: str
    redaction: RedactionStats


def parse_line_range(selector: str | None, *, total_lines: int) -> tuple[int, int]:
    if selector is None:
        end = min(total_lines, 200)
        return (1, max(1, end))

    if ":" not in selector:
        try:
            value = int(selector)
        except ValueError as exc:
            raise ValueError("Line selector must be N or START:END.") from exc
        if value < 1:
            raise ValueError("Line numbers are 1-based and must be positive.")
        return (value, min(value, total_lines))

    left, right = selector.split(":", 1)
    start = int(left) if left.strip() else 1
    end = int(right) if right.strip() else total_lines

    if start < 1 or end < 1:
        raise ValueError("Line numbers are 1-based and must be positive.")
    if start > end:
        raise ValueError("Line range start must be less than or equal to end.")

    return (start, min(end, total_lines))


def line_window_around(line: int | None, *, context: int, total_lines: int) -> tuple[int, int] | None:
    if line is None:
        return None
    if line < 1:
        raise ValueError("--around must be a positive 1-based line number.")
    context = max(0, context)
    start = max(1, line - context)
    end = min(total_lines, line + context)
    return (start, end)


def render_numbered_excerpt(
    repo_root: Path,
    path: Path,
    text: str,
    *,
    start_line: int,
    end_line: int,
) -> FileExcerpt:
    lines = text.splitlines()
    if not lines:
        lines = [""]

    start_line = max(1, start_line)
    end_line = min(max(start_line, end_line), len(lines))

    selected_lines = lines[start_line - 1 : end_line]
    selected_text = "\n".join(selected_lines)
    redacted = redact_text(selected_text)
    redacted_lines = redacted.text.splitlines() or [""]

    numbered: list[str] = []
    for offset, line in enumerate(redacted_lines):
        numbered.append(f"{start_line + offset:04d}: {line}")

    relative = to_posix_relative(repo_root, path)
    return FileExcerpt(
        path=relative,
        start_line=start_line,
        end_line=end_line,
        text="\n".join(numbered) + "\n",
        redaction=redacted.stats,
    )


def build_file_excerpt(
    repo_root: str | Path,
    path: str | Path,
    *,
    line_selector: str | None = None,
    around: int | None = None,
    context: int = 30,
    max_file_bytes: int = DEFAULT_MAX_EXCERPT_BYTES,
) -> FileExcerpt:
    root = Path(repo_root).resolve()
    target = Path(path).resolve()

    read_result = read_text_with_policy(target, max_file_bytes=max_file_bytes)
    if read_result.skipped_reason:
        raise ValueError(f"Cannot excerpt file because it was skipped: {read_result.skipped_reason}")

    text = read_result.text or ""
    total_lines = max(1, len(text.splitlines()))

    window = line_window_around(around, context=context, total_lines=total_lines)
    if window is None:
        window = parse_line_range(line_selector, total_lines=total_lines)

    return render_numbered_excerpt(
        root,
        target,
        text,
        start_line=window[0],
        end_line=window[1],
    )


def render_excerpt_markdown(excerpt: FileExcerpt) -> str:
    evidence = f"{excerpt.path}:L{excerpt.start_line}-L{excerpt.end_line}"
    lines = [
        "# CBL File Excerpt",
        "",
        f"Evidence: {evidence}",
        f"Redaction enabled: {str(excerpt.redaction.enabled).lower()}",
        f"Redacted occurrences: {excerpt.redaction.redacted_occurrences_count}",
        "",
        excerpt.text.rstrip("\n"),
        "",
    ]
    return "\n".join(lines)
