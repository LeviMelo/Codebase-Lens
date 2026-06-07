from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def main() -> int:
    path = ROOT / "tests" / "test_phase0_cli.py"
    text = path.read_text(encoding="utf-8")

    old = '    assert "CBL command: pack" in result.stdout\n'
    new = '    assert "CBL command: clean" in result.stdout\n'

    if old not in text:
        raise RuntimeError("Could not patch tests/test_phase0_cli.py: stale pack stdout assertion was not found.")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")

    print("Repair applied: Phase 0 partial-command stdout assertion now targets clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())