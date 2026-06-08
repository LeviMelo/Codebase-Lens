from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd()
AUDIT = ROOT / "scripts" / "dev" / "audits" / "audit_phase26_v01_release_closure.py"


def main() -> int:
    text = AUDIT.read_text(encoding="utf-8")

    old_loop = '''    for name, command in commands:
        check = run_command(name, command)
        checks.append(check)
        status = "PASS" if check.returncode == 0 else "FAIL"
        print(f"{status}: {name} ({check.duration_seconds}s)")

        if check.returncode != 0:
            print(check.stdout_tail)
            print(check.stderr_tail)
            report_path = write_release_report(checks, skipped_pytest=args.skip_pytest)
            fail(f"Release closure failed at {name}. Report: {report_path}")

    assert_latest_artifacts()
    report_path = write_release_report(checks, skipped_pytest=args.skip_pytest)
'''

    new_loop = '''    for name, command in commands:
        check = run_command(name, command)
        checks.append(check)
        status = "PASS" if check.returncode == 0 else "FAIL"
        print(f"{status}: {name} ({check.duration_seconds}s)")

        if check.returncode != 0:
            print(check.stdout_tail)
            print(check.stderr_tail)
            report_path = write_release_report(checks, skipped_pytest=args.skip_pytest)
            fail(f"Release closure failed at {name}. Report: {report_path}")

        if name == "contract":
            assert_latest_artifacts()

    report_path = write_release_report(checks, skipped_pytest=args.skip_pytest)
'''

    if old_loop not in text:
        raise RuntimeError("Could not find the release-closure command loop to patch.")

    text = text.replace(old_loop, new_loop, 1)
    AUDIT.write_text(text, encoding="utf-8", newline="\n")

    ast.parse(AUDIT.read_text(encoding="utf-8"))

    print("Repair applied: release closure now validates contract artifacts immediately after the contract step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())