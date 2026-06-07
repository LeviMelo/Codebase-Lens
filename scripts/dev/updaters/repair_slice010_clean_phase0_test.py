from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def main() -> int:
    path = ROOT / "tests" / "test_phase0_cli.py"
    text = path.read_text(encoding="utf-8")

    stale = '    assert PARTIAL_IMPLEMENTATION_MESSAGE in result.stdout\n'
    if stale not in text:
        raise RuntimeError("Could not patch tests/test_phase0_cli.py: stale partial implementation assertion was not found.")

    text = text.replace(stale, "", 1)

    if "PARTIAL_IMPLEMENTATION_MESSAGE" in text and "test_partial" not in text:
        text = text.replace(
            'from codebase_lens.core.result import PARTIAL_IMPLEMENTATION_MESSAGE\n',
            "",
        )

    path.write_text(text, encoding="utf-8", newline="\n")
    print("Repair applied: clean implementation test no longer expects the partial-command marker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())