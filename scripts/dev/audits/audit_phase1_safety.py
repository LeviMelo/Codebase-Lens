from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/core/paths.py": [
        "RootInfo",
        "detect_repository_root",
        "resolve_user_path",
        "is_hard_excluded_relative",
        "gitignore_mentions_codecontext",
    ],
    "src/codebase_lens/core/redaction.py": [
        "RedactionStats",
        "RedactionResult",
        "redact_text",
    ],
    "src/codebase_lens/core/textio.py": [
        "TextReadResult",
        "is_probably_binary",
        "read_text_with_policy",
    ],
    "src/codebase_lens/git/discover.py": [
        "GitInfo",
        "collect_git_info",
        "is_git_available",
    ],
    "src/codebase_lens/reports/manifest.py": [
        "OutputLayout",
        "prepare_output_layout",
        "build_manifest",
        "write_manifest_bundle",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def run_cbl(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def main() -> int:
    for relative_path, required in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(required) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    doctor = run_cbl("doctor", "--no-archive")
    if doctor.returncode != 0:
        fail(f"doctor failed after Phase 1 implementation:\nSTDOUT:\n{doctor.stdout}\nSTDERR:\n{doctor.stderr}")

    if "PARTIAL IMPLEMENTATION" in doctor.stdout:
        fail("doctor still reports partial implementation after Phase 1.")

    if "C:\\Users\\" in doctor.stdout:
        fail("doctor leaked an absolute Windows user path in default console output.")

    if "Output manifest: .codecontext/latest/manifest.json" not in doctor.stdout:
        fail("doctor did not report the expected relative manifest path.")

    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"
    if not manifest_path.is_file():
        fail("doctor did not write .codecontext/latest/manifest.json.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["command"]["subcommand"] != "doctor":
        fail("manifest command.subcommand is not doctor.")
    if manifest["repo"]["root_redacted_for_ai"] is not True:
        fail("manifest does not mark root_redacted_for_ai true.")
    if manifest["safety"]["redaction_enabled"] is not True:
        fail("manifest does not mark redaction enabled.")
    if manifest["outputs"]["manifest_json"] != ".codecontext/latest/manifest.json":
        fail("manifest output path contract is wrong.")

    redaction_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from codebase_lens.core.redaction import redact_text; r=redact_text('OPENAI_API_KEY=sk-test-secret\\npassword: hunter2'); print(r.text)",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        text=True,
        capture_output=True,
        check=False,
    )
    if redaction_probe.returncode != 0:
        fail(redaction_probe.stderr)
    if "sk-test-secret" in redaction_probe.stdout or "hunter2" in redaction_probe.stdout:
        fail("redaction probe leaked secret values.")

    print("PASS: Phase 1 safety audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
