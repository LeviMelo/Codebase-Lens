from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FIXTURE_MATRIX = r'''
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class FixtureIssue:
    severity: str
    code: str
    message: str
    fixture: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FixtureCaseResult:
    name: str
    ok: bool
    skipped: bool
    command: tuple[str, ...]
    returncode: int | None
    duration_seconds: float
    counts: dict[str, Any]
    source_prefixes: tuple[str, ...]
    issues: tuple[FixtureIssue, ...]


@dataclass(frozen=True)
class FixtureMatrixResult:
    ok: bool
    cases: tuple[FixtureCaseResult, ...]
    issues: tuple[FixtureIssue, ...]
    counts: dict[str, int]


PACK_REQUIRED_ARTIFACTS = (
    "manifest.json",
    "handoff_projection.json",
    "handoff_projection.md",
    "ai_handoff.md",
    "evidence_graph.json",
    "graph_summary.md",
    "symbol_graph.json",
    "symbol_graph.md",
    "file_inventory.json",
)


RAW_SECRET_MARKERS = (
    "sk-live-fixture-secret",
    "fixture-password-123",
    "fixture-token-abc",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _src_root() -> Path:
    return _repo_root() / "src"


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    src = str(_src_root())
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return env


def _run_cbl(args: list[str], *, cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        env=_python_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _write_pyproject(repo: Path, package_name: str) -> None:
    _write(
        repo / "pyproject.toml",
        "\n".join(
            [
                "[project]",
                f"name = '{package_name.replace('_', '-')}'",
                "version = '0.0.0'",
                "",
            ]
        ),
    )


def _write_init_with_import_trap(package: Path) -> None:
    _write(
        package / "__init__.py",
        "raise RuntimeError('CBL imported a fixture package instead of parsing it statically')",
    )


def _create_basic_package(repo: Path) -> dict[str, Any]:
    package = repo / "src" / "basic_pkg"
    tests = repo / "tests"
    _write_pyproject(repo, "basic_pkg")
    _write_init_with_import_trap(package)

    _write(
        package / "core.py",
        """
from __future__ import annotations

class Item:
    def __init__(self, name: str) -> None:
        self.name = normalize_name(name)

def normalize_name(name: str) -> str:
    return name.strip().lower()

def build_item(name: str) -> Item:
    return Item(name)
""",
    )

    _write(
        package / "service.py",
        """
from __future__ import annotations

from basic_pkg.core import Item, build_item

def render_item(name: str) -> str:
    item = build_item(name)
    return f"item:{item.name}"
""",
    )

    _write(
        tests / "test_service.py",
        """
from basic_pkg.service import render_item

def test_render_item():
    assert render_item(" A ") == "item:a"
""",
    )

    return {
        "source_prefix": "src/basic_pkg/",
        "min_symbols": 4,
        "min_imports": 2,
        "min_tests": 1,
    }


def _create_argparse_cli_package(repo: Path) -> dict[str, Any]:
    package = repo / "src" / "cli_pkg"
    _write_pyproject(repo, "cli_pkg")
    _write_init_with_import_trap(package)

    _write(
        package / "handlers.py",
        """
from __future__ import annotations

def build_value(raw: str) -> str:
    return raw.strip().upper()

def show_value(raw: str) -> str:
    return f"value={build_value(raw)}"
""",
    )

    _write(
        package / "cli.py",
        """
from __future__ import annotations

import argparse

from cli_pkg.handlers import build_value, show_value

def _run_build(raw: str) -> str:
    return build_value(raw)

def _run_show(raw: str) -> str:
    return show_value(raw)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    build = sub.add_parser("build")
    build.set_defaults(handler=_run_build)

    show = sub.add_parser("show")
    show.set_defaults(handler=_run_show)

    return parser
""",
    )

    return {
        "source_prefix": "src/cli_pkg/",
        "min_symbols": 4,
        "min_imports": 2,
        "min_commands": 2,
    }


def _create_route_package(repo: Path) -> dict[str, Any]:
    package = repo / "src" / "web_pkg"
    _write_pyproject(repo, "web_pkg")
    _write_init_with_import_trap(package)

    _write(
        package / "app.py",
        """
from __future__ import annotations

class FakeApp:
    def get(self, path: str):
        def decorate(func):
            return func
        return decorate

    def post(self, path: str):
        def decorate(func):
            return func
        return decorate

app = FakeApp()

@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

@app.post("/items")
def create_item() -> dict[str, str]:
    return {"created": "yes"}
""",
    )

    return {
        "source_prefix": "src/web_pkg/",
        "min_symbols": 5,
        "min_routes": 2,
    }


def _create_safety_redaction_package(repo: Path) -> dict[str, Any]:
    package = repo / "src" / "safety_pkg"
    _write_pyproject(repo, "safety_pkg")
    _write_init_with_import_trap(package)

    _write(
        repo / ".env",
        """
OPENAI_API_KEY=sk-live-fixture-secret
PASSWORD=fixture-password-123
""",
    )

    _write(
        package / "config.py",
        """
from __future__ import annotations

API_KEY = "sk-live-fixture-secret"
TOKEN = "fixture-token-abc"
PASSWORD = "fixture-password-123"

def public_config() -> dict[str, str]:
    return {"mode": "test", "api_key": API_KEY}
""",
    )

    return {
        "source_prefix": "src/safety_pkg/",
        "min_symbols": 1,
        "forbid_raw_secrets": True,
        "forbid_env_scan": True,
    }


def _create_codecontext_recursion_package(repo: Path) -> dict[str, Any]:
    package = repo / "src" / "recursion_pkg"
    poison = repo / ".codecontext" / "latest"
    _write_pyproject(repo, "recursion_pkg")
    _write_init_with_import_trap(package)

    _write(
        package / "core.py",
        """
from __future__ import annotations

def live_function() -> str:
    return "live"
""",
    )

    _write(
        poison / "poison.py",
        """
def poison_should_not_be_scanned():
    return "poison"
""",
    )

    _write(
        poison / "poison.md",
        """
This .codecontext content must not be scanned as source.
""",
    )

    return {
        "source_prefix": "src/recursion_pkg/",
        "min_symbols": 1,
        "forbid_codecontext_scan": True,
    }


def _git_available() -> bool:
    if shutil.which("git") is None:
        return False
    result = subprocess.run(
        ["git", "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def _create_git_changed_package(repo: Path) -> dict[str, Any]:
    package = repo / "src" / "git_pkg"
    _write_pyproject(repo, "git_pkg")
    _write_init_with_import_trap(package)

    _write(
        package / "core.py",
        """
from __future__ import annotations

def stable() -> str:
    return "stable"
""",
    )

    init = _run_git(repo, "init")
    if init.returncode != 0:
        return {"skip": True, "skip_reason": init.stderr or init.stdout or "git init failed"}

    _run_git(repo, "config", "user.email", "fixture@example.invalid")
    _run_git(repo, "config", "user.name", "CBL Fixture")
    _run_git(repo, "add", ".")
    commit = _run_git(repo, "commit", "-m", "initial fixture commit")
    if commit.returncode != 0:
        return {"skip": True, "skip_reason": commit.stderr or commit.stdout or "git commit failed"}

    _write(
        package / "core.py",
        """
from __future__ import annotations

def stable() -> str:
    return "changed"

def new_changed_symbol() -> str:
    return stable()
""",
    )

    _write(
        package / "new_file.py",
        """
from __future__ import annotations

def untracked_symbol() -> str:
    return "untracked"
""",
    )

    return {
        "source_prefix": "src/git_pkg/",
        "min_symbols": 2,
        "changed_only": True,
        "min_changed_files": 1,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _graph_node_paths(evidence_graph_path: Path) -> list[str]:
    payload = _load_json(evidence_graph_path)
    nodes = payload.get("nodes", [])
    paths: list[str] = []

    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("path"), str):
                paths.append(node["path"])

    return paths


def _contains_codecontext_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith(".codecontext/") or "/.codecontext/" in normalized


def _read_latest_text_blob(latest: Path) -> str:
    values: list[str] = []
    for name in (
        "ai_handoff.md",
        "handoff_projection.md",
        "handoff_projection.json",
        "manifest.json",
        "file_inventory.json",
        "evidence_graph.json",
    ):
        path = latest / name
        if path.is_file():
            values.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(values)


def _validate_pack_outputs(
    *,
    fixture_name: str,
    latest: Path,
    expectations: dict[str, Any],
) -> tuple[dict[str, Any], tuple[FixtureIssue, ...]]:
    issues: list[FixtureIssue] = []
    projection = _load_json(latest / "handoff_projection.json")
    evidence_graph = _load_json(latest / "evidence_graph.json")

    counts = projection.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}

    project_profile = projection.get("project_profile", {})
    source_prefixes_raw = project_profile.get("source_prefixes", []) if isinstance(project_profile, dict) else []
    source_prefixes = tuple(str(item) for item in source_prefixes_raw if isinstance(item, str))

    missing = [name for name in PACK_REQUIRED_ARTIFACTS if not (latest / name).is_file()]
    if missing:
        issues.append(
            FixtureIssue(
                severity="error",
                code="missing_pack_artifacts",
                message="Fixture pack missed mandatory artifacts.",
                fixture=fixture_name,
                details={"missing": missing},
            )
        )

    expected_prefix = expectations.get("source_prefix")
    if isinstance(expected_prefix, str) and expected_prefix not in source_prefixes:
        issues.append(
            FixtureIssue(
                severity="error",
                code="source_prefix_not_inferred",
                message="Projection did not infer the expected source prefix.",
                fixture=fixture_name,
                details={"expected": expected_prefix, "actual": list(source_prefixes)},
            )
        )

    numeric_expectations = {
        "min_symbols": "symbols",
        "min_imports": "imports",
        "min_commands": "commands",
        "min_routes": "routes",
        "min_tests": "test_functions",
        "min_changed_files": "changed_files",
    }
    for expectation_key, count_key in numeric_expectations.items():
        minimum = expectations.get(expectation_key)
        if minimum is None:
            continue
        actual = int(counts.get(count_key) or 0)
        if actual < int(minimum):
            issues.append(
                FixtureIssue(
                    severity="error",
                    code="count_below_expectation",
                    message=f"Projection count {count_key!r} was below expectation.",
                    fixture=fixture_name,
                    details={"count": count_key, "minimum": int(minimum), "actual": actual},
                )
            )

    node_paths = _graph_node_paths(latest / "evidence_graph.json")
    scanned_codecontext = [path for path in node_paths if _contains_codecontext_path(path)]
    if scanned_codecontext:
        issues.append(
            FixtureIssue(
                severity="error",
                code="codecontext_recursively_scanned",
                message=".codecontext content was scanned as target source.",
                fixture=fixture_name,
                details={"paths": scanned_codecontext[:20]},
            )
        )

    if expectations.get("forbid_env_scan"):
        env_paths = [path for path in node_paths if path == ".env" or path.startswith(".env.")]
        if env_paths:
            issues.append(
                FixtureIssue(
                    severity="error",
                    code="env_file_scanned",
                    message="Hard-excluded .env content was scanned.",
                    fixture=fixture_name,
                    details={"paths": env_paths},
                )
            )

    if expectations.get("forbid_raw_secrets"):
        blob = _read_latest_text_blob(latest)
        leaked = [marker for marker in RAW_SECRET_MARKERS if marker in blob]
        if leaked:
            issues.append(
                FixtureIssue(
                    severity="error",
                    code="raw_secret_leaked",
                    message="Raw fixture secret leaked into CBL outputs.",
                    fixture=fixture_name,
                    details={"markers": leaked},
                )
            )

    if evidence_graph and not isinstance(evidence_graph.get("nodes"), list):
        issues.append(
            FixtureIssue(
                severity="error",
                code="malformed_evidence_graph",
                message="Evidence graph JSON exists but nodes is not a list.",
                fixture=fixture_name,
            )
        )

    return {
        "counts": dict(counts),
        "source_prefixes": list(source_prefixes),
    }, tuple(issues)


FixtureCreator = Callable[[Path], dict[str, Any]]


def _run_fixture_case(
    *,
    workspace: Path,
    name: str,
    creator: FixtureCreator,
) -> FixtureCaseResult:
    repo = workspace / name
    repo.mkdir(parents=True, exist_ok=True)
    expectations = creator(repo)

    if expectations.get("skip"):
        issue = FixtureIssue(
            severity="warning",
            code="fixture_skipped",
            message=str(expectations.get("skip_reason") or "Fixture skipped."),
            fixture=name,
        )
        return FixtureCaseResult(
            name=name,
            ok=True,
            skipped=True,
            command=(),
            returncode=None,
            duration_seconds=0.0,
            counts={},
            source_prefixes=(),
            issues=(issue,),
        )

    runner = workspace / f"{name}_runner"
    runner.mkdir(parents=True, exist_ok=True)

    args = [
        "pack",
        "--repo",
        str(repo),
        "--issue",
        f"release fixture matrix: {name}",
        "--budget",
        "16000",
        "--no-archive",
    ]
    if expectations.get("changed_only"):
        args.append("--changed")

    started = time.perf_counter()
    result = _run_cbl(args, cwd=runner, timeout=60)
    duration = time.perf_counter() - started

    issues: list[FixtureIssue] = []

    if result.returncode != 0:
        issues.append(
            FixtureIssue(
                severity="error",
                code="pack_failed",
                message="cbl pack failed for fixture repository.",
                fixture=name,
                details={
                    "returncode": result.returncode,
                    "stdout_tail": result.stdout[-1500:],
                    "stderr_tail": result.stderr[-1500:],
                },
            )
        )
        return FixtureCaseResult(
            name=name,
            ok=False,
            skipped=False,
            command=tuple(args),
            returncode=result.returncode,
            duration_seconds=round(duration, 3),
            counts={},
            source_prefixes=(),
            issues=tuple(issues),
        )

    latest = repo / ".codecontext" / "latest"
    output_info, output_issues = _validate_pack_outputs(
        fixture_name=name,
        latest=latest,
        expectations=expectations,
    )
    issues.extend(output_issues)

    ok = not any(issue.severity == "error" for issue in issues)

    return FixtureCaseResult(
        name=name,
        ok=ok,
        skipped=False,
        command=tuple(args),
        returncode=result.returncode,
        duration_seconds=round(duration, 3),
        counts=dict(output_info.get("counts") or {}),
        source_prefixes=tuple(output_info.get("source_prefixes") or ()),
        issues=tuple(issues),
    )


def run_release_fixture_matrix(*, include_git_fixture: bool = True) -> FixtureMatrixResult:
    creators: list[tuple[str, FixtureCreator]] = [
        ("basic_package", _create_basic_package),
        ("argparse_cli_package", _create_argparse_cli_package),
        ("route_static_package", _create_route_package),
        ("safety_redaction_package", _create_safety_redaction_package),
        ("codecontext_recursion_package", _create_codecontext_recursion_package),
    ]

    if include_git_fixture:
        if _git_available():
            creators.append(("git_changed_package", _create_git_changed_package))
        else:
            def skipped_git(repo: Path) -> dict[str, Any]:
                return {"skip": True, "skip_reason": "git executable is unavailable; git fixture skipped."}

            creators.append(("git_changed_package", skipped_git))

    with tempfile.TemporaryDirectory(prefix="cbl_release_fixture_matrix_") as temp_dir:
        workspace = Path(temp_dir)
        cases = tuple(
            _run_fixture_case(workspace=workspace, name=name, creator=creator)
            for name, creator in creators
        )

    issues = tuple(issue for case in cases for issue in case.issues)
    ok = all(case.ok for case in cases) and not any(issue.severity == "error" for issue in issues)

    return FixtureMatrixResult(
        ok=ok,
        cases=cases,
        issues=issues,
        counts={
            "cases": len(cases),
            "passed": sum(1 for case in cases if case.ok and not case.skipped),
            "skipped": sum(1 for case in cases if case.skipped),
            "failed": sum(1 for case in cases if not case.ok),
            "issues": len(issues),
            "errors": sum(1 for issue in issues if issue.severity == "error"),
            "warnings": sum(1 for issue in issues if issue.severity == "warning"),
        },
    )


def release_fixture_matrix_payload(result: FixtureMatrixResult) -> dict[str, Any]:
    return {
        "schema": {
            "name": "cbl.release_fixture_matrix",
            "version": 1,
        },
        "ok": result.ok,
        "counts": dict(result.counts),
        "cases": [asdict(case) for case in result.cases],
        "issues": [asdict(issue) for issue in result.issues],
    }


def write_release_fixture_matrix_report(path: str | Path, result: FixtureMatrixResult) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(release_fixture_matrix_payload(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
'''

AUDIT = r'''
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def main() -> int:
    sys.path.insert(0, str(SRC))

    for relative in [
        "src/codebase_lens/contracts/fixture_matrix.py",
        "src/codebase_lens/contracts/command_surface.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.fixture_matrix import (
        run_release_fixture_matrix,
        write_release_fixture_matrix_report,
    )

    result = run_release_fixture_matrix(include_git_fixture=True)

    latest = ROOT / ".codecontext" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    report_path = latest / "fixture_matrix_audit.json"
    write_release_fixture_matrix_report(report_path, result)

    payload = json.loads(report_path.read_text(encoding="utf-8"))

    if payload.get("schema", {}).get("name") != "cbl.release_fixture_matrix":
        fail("Fixture matrix report has wrong schema name.")

    required_cases = {
        "basic_package",
        "argparse_cli_package",
        "route_static_package",
        "safety_redaction_package",
        "codecontext_recursion_package",
    }
    observed_cases = {case.get("name") for case in payload.get("cases", [])}
    missing_cases = sorted(required_cases - observed_cases)
    if missing_cases:
        fail(f"Fixture matrix did not run required cases: {missing_cases}")

    if not result.ok:
        formatted = json.dumps(payload.get("issues", []), indent=2, sort_keys=True)
        fail(f"Release fixture matrix failed:\n{formatted}")

    if payload.get("counts", {}).get("passed", 0) < 5:
        fail(f"Too few fixture cases passed: {payload.get('counts')}")

    print("PASS: Phase 21 release fixture matrix audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST = r'''
from __future__ import annotations

import json

from codebase_lens.contracts.fixture_matrix import (
    release_fixture_matrix_payload,
    run_release_fixture_matrix,
)


def test_release_fixture_matrix_passes_core_external_repositories() -> None:
    result = run_release_fixture_matrix(include_git_fixture=False)
    payload = release_fixture_matrix_payload(result)

    assert result.ok, json.dumps(payload["issues"], indent=2, sort_keys=True)
    assert payload["schema"]["name"] == "cbl.release_fixture_matrix"
    assert payload["counts"]["cases"] == 5
    assert payload["counts"]["failed"] == 0
    assert payload["counts"]["errors"] == 0

    cases = {case["name"]: case for case in payload["cases"]}

    assert "src/basic_pkg/" in cases["basic_package"]["source_prefixes"]
    assert cases["basic_package"]["counts"]["symbols"] >= 4
    assert cases["basic_package"]["counts"]["test_functions"] >= 1

    assert "src/cli_pkg/" in cases["argparse_cli_package"]["source_prefixes"]
    assert cases["argparse_cli_package"]["counts"]["commands"] >= 2

    assert "src/web_pkg/" in cases["route_static_package"]["source_prefixes"]
    assert cases["route_static_package"]["counts"]["routes"] >= 2

    assert "src/safety_pkg/" in cases["safety_redaction_package"]["source_prefixes"]
    assert "src/recursion_pkg/" in cases["codecontext_recursion_package"]["source_prefixes"]


def test_fixture_matrix_contract_module_does_not_import_cli_layer() -> None:
    import inspect
    import codebase_lens.contracts.fixture_matrix as fixture_matrix

    source = inspect.getsource(fixture_matrix)

    assert "from codebase_lens import cli" not in source
    assert "import codebase_lens.cli" not in source
    assert "codebase_lens.cli" not in source
'''


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative: str, content: str, modified: set[Path]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize(content), encoding="utf-8", newline="\n")
    if path.suffix == ".py":
        modified.add(path)


def list_bounds_for_key(text: str, key: str) -> tuple[int, int]:
    match = re.search(rf'(?P<quote>["\']){re.escape(key)}(?P=quote)\s*:\s*\[', text)
    if not match:
        raise RuntimeError(f"Could not find list key {key!r}.")

    open_index = text.find("[", match.start())
    depth = 0
    quote: str | None = None
    escaped = False
    i = open_index

    while i < len(text):
        ch = text[i]

        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch in {"'", '"'}:
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return open_index, i

        i += 1

    raise RuntimeError(f"Could not find closing bracket for {key!r}.")


def insert_before_list_close(text: str, key: str, block: str) -> str:
    _, close = list_bounds_for_key(text, key)
    return text[:close] + block + text[close:]


def patch_contract(modified: set[Path]) -> None:
    path = ROOT / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = path.read_text(encoding="utf-8")

    additions = [
        "src/codebase_lens/contracts/fixture_matrix.py",
        "scripts/dev/audits/audit_phase21_release_fixture_matrix.py",
    ]

    for required_file in additions:
        if f'"{required_file}"' not in text and f"'{required_file}'" not in text:
            text = insert_before_list_close(text, "required_files", f'            "{required_file}",\n')

    path.write_text(text, encoding="utf-8", newline="\n")
    modified.add(path)


def assert_parseable(paths: set[Path]) -> None:
    for path in sorted(paths):
        if path.suffix != ".py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise RuntimeError(f"Generated invalid Python in {path}: {exc}") from exc


def main() -> int:
    modified: set[Path] = set()

    write_file("src/codebase_lens/contracts/fixture_matrix.py", FIXTURE_MATRIX, modified)
    write_file("scripts/dev/audits/audit_phase21_release_fixture_matrix.py", AUDIT, modified)
    write_file("tests/test_release_fixture_matrix.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 017 applied: release fixture matrix added.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())