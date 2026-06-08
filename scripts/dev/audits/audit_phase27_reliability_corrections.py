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
RAW_SECRET_MARKERS = (
    "sk-live-fixture-secret",
    "fixture-password-123",
    "fixture-token-abc",
    "postgres://fixture-secret",
)


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def env() -> dict[str, str]:
    value = os.environ.copy()
    current = value.get("PYTHONPATH", "")
    src = str(SRC)
    value["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return value


def run_cbl(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env(),
        timeout=90,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def load_json(path: Path) -> dict:
    if not path.is_file():
        fail(f"missing JSON artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"JSON artifact is not an object: {path}")
    return value


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def make_repo(base: Path) -> Path:
    repo = base / "reliability_repo"
    pkg = repo / "src" / "demo_pkg"
    tests = repo / "tests"

    write(repo / "pyproject.toml", """
[project]
name = 'demo-pkg'
version = '0.0.0'
""")
    write(pkg / "__init__.py", "raise RuntimeError('CBL imported target package')")
    write(pkg / "core.py", """
from __future__ import annotations

API_KEY = "sk-live-fixture-secret"

class TestRecord:
    pass

class Service:
    def run(self, value: str) -> str:
        return self.normalize(value)

    def normalize(self, value: str) -> str:
        return value.strip().lower()

def test_helper():
    return "not a real pytest test"

def factory(flag: bool):
    if flag:
        def inner(api_key="sk-live-fixture-secret"):
            return Service()
        return inner()
    return Service()
""")
    write(pkg / "routes.py", """
from __future__ import annotations

class App:
    def get(self, path: str):
        def decorate(func):
            return func
        return decorate

app = App()

@app.get('/fixture-password-123')
def unsafe_route():
    return {'ok': True}
""")
    write(pkg / "cli.py", """
from __future__ import annotations

import argparse

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command')
    unsafe = sub.add_parser('unsafe', help='fixture-token-abc')
    unsafe.set_defaults(handler=lambda: None)
    return parser
""")
    write(tests / "test_core.py", """
from demo_pkg.core import Service

def test_service_normalize():
    assert Service().normalize(' A ') == 'a'
""")
    write(tests / "conftest.py", """
import pytest

@pytest.fixture
def sample_service():
    return object()
""")
    write(pkg / "large_notes.md", "sk-live-fixture-secret\n" + ("x" * 120000))
    (pkg / "binary_payload.bin").write_bytes(b"\x00\x01sk-live-fixture-secret")
    write(repo / ".env", "OPENAI_API_KEY=sk-live-fixture-secret")
    return repo


def scan_for_raw_secrets(root: Path) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".json", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in RAW_SECRET_MARKERS:
            if marker in text:
                hits.append(f"{path.name}:{marker}")
    return hits


def main() -> int:
    for relative in [
        "src/codebase_lens/scanners/inventory.py",
        "src/codebase_lens/scanners/tree.py",
        "src/codebase_lens/analyzers/tests.py",
        "src/codebase_lens/analyzers/symbol_graph.py",
        "src/codebase_lens/analyzers/graph_query.py",
        "scripts/dev/audits/audit_phase27_reliability_corrections.py",
    ]:
        assert_parseable(relative)

    with tempfile.TemporaryDirectory(prefix="cbl_reliability_") as temp_dir:
        repo = make_repo(Path(temp_dir))

        snapshot = run_cbl("snapshot", "--repo", str(repo), "--max-file-bytes", "4096", "--no-archive", cwd=ROOT)
        if snapshot.returncode != 0:
            fail(f"snapshot failed:\nSTDOUT:\n{snapshot.stdout}\nSTDERR:\n{snapshot.stderr}")
        latest = repo / ".codecontext" / "latest"

        inventory = load_json(latest / "file_inventory.json")
        omissions = load_json(latest / "omissions.json")
        omitted_paths = {item.get("path") for item in inventory.get("omitted_files", []) if isinstance(item, dict)}
        if "src/demo_pkg/large_notes.md" not in omitted_paths:
            fail("file_inventory.json did not expose the large skipped file under omitted_files.")
        if not omissions.get("omitted_files"):
            fail("omissions.json did not expose omitted_files.")

        tests_payload = load_json(latest / "test_inventory.json")
        test_paths = {item.get("path") for item in tests_payload.get("tests", []) if isinstance(item, dict)}
        if test_paths != {"tests/test_core.py"}:
            fail(f"test inventory counted non-test paths as real tests: {sorted(test_paths)}")
        if tests_payload.get("counts", {}).get("test_functions") != 1:
            fail("test inventory should count exactly one real test function.")
        if tests_payload.get("counts", {}).get("test_like_symbols", 0) < 2:
            fail("test inventory did not preserve production test-like symbols as diagnostics.")

        symbol_graph = load_json(latest / "symbol_graph.json")
        graph_nodes = symbol_graph.get("nodes", [])
        names = {node.get("qualified_name"): node for node in graph_nodes if isinstance(node, dict)}
        if "factory.inner" not in names:
            fail("symbol graph missed nested definition under control flow: factory.inner")
        if names.get("Service.run", {}).get("kind") != "method":
            fail("symbol graph did not classify class function Service.run as method.")
        caller_edges = []
        for node in graph_nodes:
            if isinstance(node, dict):
                for caller in node.get("called_by", []) or []:
                    if isinstance(caller, dict):
                        caller_edges.append((node.get("qualified_name"), caller.get("path"), caller.get("symbol"), caller.get("line")))
        if len(caller_edges) != len(set(caller_edges)):
            fail("symbol graph contains duplicate called_by edges.")

        graph = run_cbl("graph", "--repo", str(repo), "--symbol", "factory", "--depth", "1", "--limit", "80", "--no-archive", cwd=ROOT)
        if graph.returncode != 0:
            fail(f"graph failed:\nSTDOUT:\n{graph.stdout}\nSTDERR:\n{graph.stderr}")
        graph_query = load_json(latest / "graph_query.json")
        if graph_query.get("query", {}).get("unresolved_mode") != "seed":
            fail("graph query default unresolved mode is not seed.")
        if graph_query.get("counts", {}).get("edges", 9999) > 250:
            fail("graph query selected too many edges after noise-control patch.")

        pack = run_cbl("pack", "--repo", str(repo), "--issue", "slice022 reliability safety", "--max-file-bytes", "4096", "--no-archive", cwd=ROOT)
        if pack.returncode != 0:
            fail(f"pack failed:\nSTDOUT:\n{pack.stdout}\nSTDERR:\n{pack.stderr}")
        leaks = scan_for_raw_secrets(latest)
        if leaks:
            fail(f"raw secret markers leaked into AI-facing artifacts: {leaks[:20]}")

    print("PASS: Phase 27 reliability corrections audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
