from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def main() -> int:
    path = ROOT / "tests" / "test_phase0_cli.py"
    text = path.read_text(encoding="utf-8")

    old = '''def test_partial_commands_remain_explicit() -> None:
    result = run_cbl("pack")
    assert result.returncode == 1
'''

    new = '''def test_partial_commands_remain_explicit() -> None:
    result = run_cbl("clean")
    assert result.returncode == 1
'''

    if old not in text:
        raise RuntimeError("Could not patch tests/test_phase0_cli.py: expected stale pack partial test block was not found.")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")

    print("Repair applied: Phase 0 partial-command test now targets clean instead of implemented pack.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())