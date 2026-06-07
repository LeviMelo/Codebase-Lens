from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/contracts/architecture.py": [
        "ContractViolation",
        "ContractResult",
        "builtin_cbl_contract",
        "load_contract_spec",
        "evaluate_contract",
    ],
    "src/codebase_lens/reports/json.py": [
        "contract_result_payload",
    ],
    "src/codebase_lens/reports/scanner_outputs.py": [
        "write_file_inventory",
        "write_tree_report",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def run_cbl(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    builtin = run_cbl("contract", "--no-archive")
    if builtin.returncode != 0:
        fail(f"builtin cbl contract failed:\nSTDOUT:\n{builtin.stdout}\nSTDERR:\n{builtin.stderr}")
    if "CBL contract: OK" not in builtin.stdout:
        fail("builtin cbl contract did not report success.")
    if "C:\\Users\\" in builtin.stdout:
        fail("builtin cbl contract leaked an absolute Windows user path.")

    report_path = ROOT / ".codecontext" / "latest" / "contract_report.json"
    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"

    if not report_path.is_file():
        fail("contract did not write contract_report.json.")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report["counts"]["errors"] != 0:
        fail(f"builtin contract has errors: {report['violations']}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["command"]["subcommand"] != "contract":
        fail("manifest command.subcommand is not contract.")
    if manifest["outputs"].get("contract_report_json") != ".codecontext/latest/contract_report.json":
        fail("manifest does not declare contract_report_json.")
    if manifest["repo"].get("root") != "<redacted>":
        fail("manifest repo.root must be redacted.")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "contract_repo"
        source = repo / "src" / "demo"
        source.mkdir(parents=True)

        (repo / "pyproject.toml").write_text("[project]\nname = 'contract-repo'\n", encoding="utf-8")
        (source / "bad.py").write_text("import forbidden.module\n", encoding="utf-8")

        spec = repo / "contract.json"
        spec.write_text(
            json.dumps(
                {
                    "id": "custom-contract",
                    "name": "Custom Contract",
                    "required_files": ["pyproject.toml"],
                    "forbidden_imports": [
                        {
                            "id": "no-forbidden",
                            "from": "src/**/*.py",
                            "disallow": ["forbidden"],
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        violated = run_cbl("contract", "--repo", str(repo), "--spec", "contract.json", "--no-fail-exit", "--no-archive")
        if violated.returncode != 0:
            fail(f"custom contract with --no-fail-exit should return 0:\nSTDOUT:\n{violated.stdout}\nSTDERR:\n{violated.stderr}")
        if "Violations: 1" not in violated.stdout:
            fail("custom violation contract did not report exactly one violation.")

        custom_report = json.loads((repo / ".codecontext" / "latest" / "contract_report.json").read_text(encoding="utf-8"))
        if custom_report["counts"]["errors"] != 1:
            fail("custom violation contract did not record one error.")
        if custom_report["violations"][0]["rule_id"] != "no-forbidden":
            fail("custom violation contract did not preserve the rule id.")

    print("PASS: Phase 7 architecture contract audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
