from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import BINARY_SNIFF_BYTES, DEFAULT_MAX_FILE_BYTES, TEXT_ENCODINGS


@dataclass(frozen=True)
class TextReadResult:
    path: Path
    text: str | None
    encoding: str | None
    size_bytes: int
    is_binary: bool
    skipped_reason: str | None


def is_probably_binary(path: str | Path, *, sniff_bytes: int = BINARY_SNIFF_BYTES) -> bool:
    data = Path(path).read_bytes()[:sniff_bytes]
    return b"\x00" in data


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text_with_policy(
    path: str | Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    encodings: tuple[str, ...] = TEXT_ENCODINGS,
) -> TextReadResult:
    target = Path(path)
    size = target.stat().st_size

    if size > max_file_bytes:
        return TextReadResult(target, None, None, size, False, "large_skipped")

    if is_probably_binary(target):
        return TextReadResult(target, None, None, size, True, "binary_skipped")

    data = target.read_bytes()
    for encoding in encodings:
        try:
            return TextReadResult(
                path=target,
                text=normalize_newlines(data.decode(encoding)),
                encoding=encoding,
                size_bytes=size,
                is_binary=False,
                skipped_reason=None,
            )
        except UnicodeDecodeError:
            continue

    return TextReadResult(target, None, None, size, False, "decode_failed")
