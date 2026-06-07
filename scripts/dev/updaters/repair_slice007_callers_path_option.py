from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def patch_cli() -> None:
    path = ROOT / "src/codebase_lens/cli.py"
    text = path.read_text(encoding="utf-8")

    old = '''    callers = sub.add_parser("callers", parents=[parent], help="Find static call sites.")
    callers.add_argument("name")
    callers.set_defaults(handler=_run_callers)
'''

    new = '''    callers = sub.add_parser("callers", parents=[parent], help="Find static call sites.")
    callers.add_argument("name")
    callers.add_argument("--path")
    callers.set_defaults(handler=_run_callers)
'''

    if old not in text:
        raise RuntimeError("Could not patch cli.py: callers parser block did not match expected Slice 007 shape.")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_integration_test() -> None:
    path = ROOT / "tests/test_tests_callers_integration.py"
    text = path.read_text(encoding="utf-8")

    old = '''    callers_result = run_cbl("callers", "target", "--repo", str(repo), "--no-archive")
'''

    new = '''    callers_result = run_cbl("callers", "target", "--repo", str(repo), "--path", "src/demo/service.py", "--no-archive")
'''

    if old not in text:
        raise RuntimeError("Could not patch integration test: callers command marker not found.")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    patch_cli()
    patch_integration_test()
    print("Repair applied: cbl callers now accepts --path and integration test exercises it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())