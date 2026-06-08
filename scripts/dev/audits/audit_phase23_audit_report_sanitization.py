from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def run_python(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    sys.path.insert(0, str(SRC))

    for relative in [
        "src/codebase_lens/core/audit_artifacts.py",
        "src/codebase_lens/contracts/release_safety.py",
        "src/codebase_lens/contracts/fixture_matrix.py",
        "src/codebase_lens/contracts/command_surface.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.core.audit_artifacts import audit_payload_contains_local_paths

    commands = [
        [sys.executable, "scripts/dev/audits/audit_phase20_public_command_stability.py"],
        [sys.executable, "scripts/dev/audits/audit_phase21_release_fixture_matrix.py"],
        [sys.executable, "scripts/dev/audits/audit_phase22_release_safety.py"],
    ]

    for command in commands:
        result = run_python(command)
        if result.returncode != 0:
            fail(
                "Required release audit failed before sanitization check.\n"
                f"Command: {' '.join(command)}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

    audit_dir = ROOT / ".codecontext" / "audits"
    expected = [
        audit_dir / "command_surface_audit.json",
        audit_dir / "fixture_matrix_audit.json",
        audit_dir / "release_safety_audit.json",
    ]

    for path in expected:
        if not path.is_file():
            fail(f"Expected stable audit report missing: {path}")

        payload = load_json(path)
        if audit_payload_contains_local_paths(payload):
            fail(f"Stable audit report still contains local absolute path fragments: {path}")

        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if "C:\\\\Users\\\\" in blob or "C:/Users/" in blob:
            fail(f"Stable audit report leaked Windows user path: {path}")
        if "AppData\\\\Local\\\\Temp" in blob or "AppData/Local/Temp" in blob:
            fail(f"Stable audit report leaked Windows temp path: {path}")
        if "/tmp/" in blob or "/var/tmp/" in blob or "/private/var/folders/" in blob:
            fail(f"Stable audit report leaked POSIX temp path: {path}")

    print("PASS: Phase 23 audit report path sanitization passed.")
    print(f"Stable audit directory: {audit_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
