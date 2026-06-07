from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/reports/cleanup.py": [
        "CleanedRunRecord",
        "CleanResult",
        "clean_archives",
        "clean_result_payload",
        "write_clean_report",
    ],
    "src/codebase_lens/cli.py": [
        "_run_clean",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
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


def make_repo(base: Path) -> Path:
    repo = base / "clean_repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'clean-repo'\n", encoding="utf-8")

    runs = repo / ".codecontext" / "runs"
    runs.mkdir(parents=True)

    for index in range(4):
        run_dir = runs / f"20260101T00000{index}Z"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        time.sleep(0.01)

    return repo


def main() -> int:
    if not (ROOT / ".gitattributes").is_file():
        fail(".gitattributes is missing.")

    gitattributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    if "*.py text eol=lf" not in gitattributes:
        fail(".gitattributes does not enforce LF for Python files.")

    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))

        clean = run_cbl("clean", "--repo", str(repo), "--keep", "2")
        if clean.returncode != 0:
            fail(f"cbl clean failed:\nSTDOUT:\n{clean.stdout}\nSTDERR:\n{clean.stderr}")
        if "CBL clean: OK" not in clean.stdout:
            fail("cbl clean did not report success.")
        if "C:\\Users\\" in clean.stdout:
            fail("cbl clean leaked an absolute Windows user path.")

        latest = repo / ".codecontext" / "latest"
        report_path = latest / "clean_report.json"
        manifest_path = latest / "manifest.json"

        if not report_path.is_file():
            fail("cbl clean did not write clean_report.json.")
        if not manifest_path.is_file():
            fail("cbl clean did not write manifest.json.")

        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["counts"]["runs_seen"] != 4:
            fail("clean report has wrong runs_seen count.")
        if report["counts"]["kept"] != 2:
            fail("clean report has wrong kept count.")
        if report["counts"]["deleted"] != 2:
            fail("clean report has wrong deleted count.")
        if report["counts"]["errors"] != 0:
            fail("clean report has deletion errors.")

        remaining_runs = [item for item in (repo / ".codecontext" / "runs").iterdir() if item.is_dir()]
        if len(remaining_runs) != 2:
            fail("clean command did not leave exactly two runs.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "clean":
            fail("manifest command.subcommand is not clean.")
        if manifest["outputs"].get("clean_report_json") != ".codecontext/latest/clean_report.json":
            fail("manifest does not declare clean_report_json.")
        if manifest["repo"].get("root") != "<redacted>":
            fail("manifest repo.root is not redacted.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed after clean slice:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 9 clean/hygiene audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
