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
    "src/codebase_lens/analyzers/python_ast.py": [
        "PythonAnalysisResult",
        "collect_symbols_for_file",
        "collect_python_symbols",
        "flatten_symbol_results",
        "find_symbol_matches",
    ],
    "src/codebase_lens/analyzers/imports.py": [
        "PythonImportAnalysisResult",
        "collect_imports_for_file",
        "collect_python_imports",
        "flatten_import_results",
        "filter_imports_by_module",
        "resolve_project_import",
    ],
    "src/codebase_lens/reports/json.py": [
        "write_json_report",
        "symbol_records_payload",
        "import_records_payload",
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


def main() -> int:
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    symbols = run_cbl("symbols", "--path", "src/codebase_lens/cli.py", "--no-archive")
    if symbols.returncode != 0:
        fail(f"cbl symbols failed:\nSTDOUT:\n{symbols.stdout}\nSTDERR:\n{symbols.stderr}")
    if "CBL symbols: OK" not in symbols.stdout:
        fail("cbl symbols did not report success.")
    if "C:\\Users\\" in symbols.stdout:
        fail("cbl symbols leaked an absolute Windows user path.")

    symbols_path = ROOT / ".codecontext" / "latest" / "symbols.json"
    if not symbols_path.is_file():
        fail("cbl symbols did not write symbols.json.")
    symbols_payload = json.loads(symbols_path.read_text(encoding="utf-8"))
    symbol_names = {record["name"] for record in symbols_payload["symbols"]}
    if "build_parser" not in symbol_names:
        fail("symbols.json does not include build_parser from cli.py.")

    symbol_json = run_cbl("symbols", "--path", "src/codebase_lens/cli.py", "--query", "build_parser", "--json", "--no-archive")
    if symbol_json.returncode != 0:
        fail("cbl symbols --json failed.")
    try:
        parsed_symbol_stdout = json.loads(symbol_json.stdout)
    except json.JSONDecodeError as exc:
        fail(f"cbl symbols --json did not emit valid JSON: {exc}")
    if not any(record["name"] == "build_parser" for record in parsed_symbol_stdout["symbols"]):
        fail("cbl symbols --json did not include build_parser.")

    symbol = run_cbl("symbol", "build_parser", "--path", "src/codebase_lens/cli.py", "--first", "--context", "2", "--no-archive")
    if symbol.returncode != 0:
        fail(f"cbl symbol failed:\nSTDOUT:\n{symbol.stdout}\nSTDERR:\n{symbol.stderr}")
    if "CBL Symbol Excerpt" not in symbol.stdout:
        fail("cbl symbol did not emit a symbol excerpt.")
    if "Definition: src/codebase_lens/cli.py" not in symbol.stdout:
        fail("cbl symbol did not emit a relative definition line.")
    if "C:\\Users\\" in symbol.stdout:
        fail("cbl symbol leaked an absolute Windows user path.")

    excerpt_path = ROOT / ".codecontext" / "latest" / "symbol_excerpt.md"
    matches_path = ROOT / ".codecontext" / "latest" / "symbol_matches.json"
    if not excerpt_path.is_file():
        fail("cbl symbol did not write symbol_excerpt.md.")
    if not matches_path.is_file():
        fail("cbl symbol did not write symbol_matches.json.")

    imports = run_cbl("imports", "--path", "src/codebase_lens/cli.py", "--module", "codebase_lens", "--no-archive")
    if imports.returncode != 0:
        fail(f"cbl imports failed:\nSTDOUT:\n{imports.stdout}\nSTDERR:\n{imports.stderr}")
    if "CBL imports: OK" not in imports.stdout:
        fail("cbl imports did not report success.")
    if "C:\\Users\\" in imports.stdout:
        fail("cbl imports leaked an absolute Windows user path.")

    imports_path = ROOT / ".codecontext" / "latest" / "imports.json"
    if not imports_path.is_file():
        fail("cbl imports did not write imports.json.")

    imports_payload = json.loads(imports_path.read_text(encoding="utf-8"))
    if imports_payload["counts"]["total"] < 1:
        fail("imports.json contains no imports for cli.py.")
    if not any("codebase_lens" in (record["module"] or "") or "codebase_lens" in record["raw"] for record in imports_payload["imports"]):
        fail("imports.json does not include codebase_lens imports.")

    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["command"]["subcommand"] != "imports":
        fail("manifest command.subcommand should be imports after cbl imports.")
    if manifest["outputs"].get("imports_json") != ".codecontext/latest/imports.json":
        fail("manifest does not declare imports_json output.")

    print("PASS: Phase 3 Python evidence audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
