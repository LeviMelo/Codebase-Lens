from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


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


def test_symbols_command_writes_symbols_json() -> None:
    result = run_cbl("symbols", "--path", "src/codebase_lens/cli.py", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL symbols: OK" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    symbols_path = ROOT / ".codecontext" / "latest" / "symbols.json"
    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"

    assert symbols_path.is_file()
    assert manifest_path.is_file()

    payload = json.loads(symbols_path.read_text(encoding="utf-8"))
    names = {record["name"] for record in payload["symbols"]}
    assert "build_parser" in names
    assert "main" in names

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "symbols"
    assert manifest["outputs"]["symbols_json"] == ".codecontext/latest/symbols.json"


def test_symbols_command_can_print_json() -> None:
    result = run_cbl("symbols", "--path", "src/codebase_lens/cli.py", "--query", "build_parser", "--json", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["counts"]["total"] >= 1
    assert any(record["name"] == "build_parser" for record in payload["symbols"])


def test_symbol_command_writes_symbol_excerpt() -> None:
    result = run_cbl("symbol", "build_parser", "--path", "src/codebase_lens/cli.py", "--first", "--context", "2", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL Symbol Excerpt" in result.stdout
    assert "Symbol: build_parser" in result.stdout
    assert "Definition: src/codebase_lens/cli.py" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    excerpt_path = ROOT / ".codecontext" / "latest" / "symbol_excerpt.md"
    matches_path = ROOT / ".codecontext" / "latest" / "symbol_matches.json"

    assert excerpt_path.is_file()
    assert matches_path.is_file()

    matches = json.loads(matches_path.read_text(encoding="utf-8"))
    assert matches["count"] >= 1


def test_imports_command_writes_imports_json() -> None:
    result = run_cbl("imports", "--path", "src/codebase_lens/cli.py", "--module", "codebase_lens", "--no-archive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL imports: OK" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    imports_path = ROOT / ".codecontext" / "latest" / "imports.json"
    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"

    assert imports_path.is_file()
    assert manifest_path.is_file()

    payload = json.loads(imports_path.read_text(encoding="utf-8"))
    assert payload["counts"]["total"] >= 1
    assert any("codebase_lens" in (record["module"] or "") or "codebase_lens" in record["raw"] for record in payload["imports"])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "imports"
    assert manifest["outputs"]["imports_json"] == ".codecontext/latest/imports.json"
