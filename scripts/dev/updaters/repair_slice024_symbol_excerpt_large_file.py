from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd()
CLI_PATH = ROOT / "src" / "codebase_lens" / "cli.py"


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Missing required file: {path}")
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _parse(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def main() -> int:
    text = _read(CLI_PATH)

    old = "max_file_bytes=min(args.max_file_bytes, DEFAULT_MAX_EXCERPT_BYTES),"
    new = "max_file_bytes=args.max_file_bytes,"
    count = text.count(old)
    if count < 1:
        raise RuntimeError(
            "Could not find the old excerpt byte-cap expression in cli.py. "
            "The file may already be repaired or has drifted from the expected Slice 024 state."
        )

    text = text.replace(old, new)

    # The excerpt-specific cap is no longer used by cli.py after this repair.
    # The constant can remain defined in core.constants for future lower-level APIs,
    # but the CLI must not artificially cap symbol/file excerpts below the normal
    # source-file safety limit.
    text = text.replace("    DEFAULT_MAX_EXCERPT_BYTES,\n", "")

    _write(CLI_PATH, text)
    _parse(CLI_PATH)

    print("Slice 024 repair applied: symbol/file excerpts now use the normal source-file read cap.")
    print(f"Replaced excerpt byte-cap expressions: {count}")
    print("The patched CLI parsed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
