from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/contracts/__init__.py": r'''
from codebase_lens.contracts.architecture import ContractResult, ContractViolation, evaluate_contract, load_contract_spec

__all__ = [
    "ContractResult",
    "ContractViolation",
    "evaluate_contract",
    "load_contract_spec",
]
''',

    "src/codebase_lens/contracts/architecture.py": r'''
from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from codebase_lens.core.paths import is_hard_excluded_relative, resolve_user_path, to_posix_relative
from codebase_lens.core.textio import read_text_with_policy
from codebase_lens.scanners.universe import discover_file_universe


@dataclass(frozen=True)
class ContractViolation:
    rule_id: str
    severity: str
    message: str
    path: str | None
    line: int | None
    evidence: str | None


@dataclass(frozen=True)
class ContractResult:
    contract_id: str
    name: str
    violations: tuple[ContractViolation, ...]
    warnings: tuple[str, ...]
    counts: dict[str, int]


def builtin_cbl_contract() -> dict[str, Any]:
    return {
        "id": "cbl-monolithic-scaffold-v1",
        "name": "CBL Monolithic Scaffolding Contract",
        "required_files": [
            "pyproject.toml",
            "src/codebase_lens/__init__.py",
            "src/codebase_lens/__main__.py",
            "src/codebase_lens/cli.py",
            "src/codebase_lens/core/constants.py",
            "src/codebase_lens/core/errors.py",
            "src/codebase_lens/core/paths.py",
            "src/codebase_lens/core/redaction.py",
            "src/codebase_lens/core/textio.py",
            "src/codebase_lens/git/discover.py",
            "src/codebase_lens/git/status.py",
            "src/codebase_lens/git/diff.py",
            "src/codebase_lens/scanners/universe.py",
            "src/codebase_lens/scanners/inventory.py",
            "src/codebase_lens/scanners/tree.py",
            "src/codebase_lens/analyzers/python_ast.py",
            "src/codebase_lens/analyzers/imports.py",
            "src/codebase_lens/analyzers/excerpts.py",
            "src/codebase_lens/analyzers/cli_static.py",
            "src/codebase_lens/analyzers/routes_static.py",
            "src/codebase_lens/analyzers/changed_symbols.py",
            "src/codebase_lens/analyzers/tests.py",
            "src/codebase_lens/analyzers/callers.py",
            "src/codebase_lens/reports/manifest.py",
            "src/codebase_lens/reports/json.py",
            "src/codebase_lens/contracts/architecture.py",
        ],
        "required_symbols": [
            {
                "path": "src/codebase_lens/cli.py",
                "symbols": [
                    "build_parser",
                    "main",
                    "_run_doctor",
                    "_run_tree",
                    "_run_file",
                    "_run_symbols",
                    "_run_imports",
                    "_run_cli_static",
                    "_run_routes_static",
                    "_run_diff",
                    "_run_changed",
                    "_run_tests_inventory",
                    "_run_callers",
                    "_run_contract",
                ],
            },
            {
                "path": "src/codebase_lens/contracts/architecture.py",
                "symbols": [
                    "ContractViolation",
                    "ContractResult",
                    "builtin_cbl_contract",
                    "load_contract_spec",
                    "evaluate_contract",
                ],
            },
        ],
        "forbidden_imports": [
            {
                "id": "core-no-upward-imports",
                "from": "src/codebase_lens/core/**/*.py",
                "disallow": [
                    "codebase_lens.analyzers",
                    "codebase_lens.scanners",
                    "codebase_lens.reports",
                    "codebase_lens.git",
                    "codebase_lens.contracts",
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "git-no-upward-imports",
                "from": "src/codebase_lens/git/**/*.py",
                "disallow": [
                    "codebase_lens.analyzers",
                    "codebase_lens.scanners",
                    "codebase_lens.reports",
                    "codebase_lens.contracts",
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "scanners-no-analyzer-report-imports",
                "from": "src/codebase_lens/scanners/**/*.py",
                "disallow": [
                    "codebase_lens.analyzers",
                    "codebase_lens.reports",
                    "codebase_lens.contracts",
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "analyzers-no-report-or-cli-imports",
                "from": "src/codebase_lens/analyzers/**/*.py",
                "disallow": [
                    "codebase_lens.reports",
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "reports-no-cli-imports",
                "from": "src/codebase_lens/reports/**/*.py",
                "disallow": [
                    "codebase_lens.cli",
                ],
            },
            {
                "id": "contracts-no-cli-imports",
                "from": "src/codebase_lens/contracts/**/*.py",
                "disallow": [
                    "codebase_lens.cli",
                ],
            },
        ],
    }


def _load_yaml_if_available(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise ValueError(
            "YAML contract files require PyYAML. Use JSON for dependency-free contract specs."
        ) from exc

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Contract spec must parse to an object.")
    return payload


def load_contract_spec(repo_root: str | Path, spec_path: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()

    if spec_path is None:
        return builtin_cbl_contract()

    target = resolve_user_path(root, spec_path, allow_absolute=True, allow_hard_excluded=False)
    if not target.is_file():
        raise ValueError(f"Contract spec does not exist: {spec_path}")

    suffix = target.suffix.lower()
    if suffix == ".json":
        payload = json.loads(target.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        payload = _load_yaml_if_available(target)
    else:
        raise ValueError("Contract spec must be .json, .yaml, or .yml.")

    if not isinstance(payload, dict):
        raise ValueError("Contract spec must be a JSON/YAML object.")

    return payload


def _path_matches(pattern: str, path: str) -> bool:
    normalized_pattern = pattern.replace("\\", "/").strip("/")
    normalized_path = path.replace("\\", "/").strip("/")

    if normalized_pattern.endswith("/**/*.py"):
        prefix = normalized_pattern[: -len("/**/*.py")]
        return normalized_path.startswith(prefix + "/") and normalized_path.endswith(".py")

    if normalized_pattern.endswith("/**"):
        prefix = normalized_pattern[: -len("/**")]
        return normalized_path.startswith(prefix + "/")

    return fnmatch(normalized_path, normalized_pattern)


def _normalize_imported_name(module: str | None, name: str | None) -> str:
    if module and name:
        return f"{module}.{name}"
    if module:
        return module
    if name:
        return name
    return ""


def _import_edges_for_file(repo_root: Path, relative_path: str) -> tuple[tuple[int, str, str], ...]:
    target = repo_root / relative_path
    read_result = read_text_with_policy(target)

    if read_result.skipped_reason or read_result.text is None:
        return ()

    try:
        tree = ast.parse(read_result.text, filename=relative_path)
    except SyntaxError:
        return ()

    edges: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = _normalize_imported_name(alias.name, None)
                edges.append((int(getattr(node, "lineno", 1)), imported, f"import {alias.name}"))

        elif isinstance(node, ast.ImportFrom):
            module = node.module
            for alias in node.names:
                imported = _normalize_imported_name(module, alias.name)
                raw = f"from {module or ''} import {alias.name}"
                edges.append((int(getattr(node, "lineno", 1)), imported, raw))

    return tuple(edges)


def _top_level_symbols(repo_root: Path, relative_path: str) -> tuple[str, ...]:
    target = repo_root / relative_path
    read_result = read_text_with_policy(target)

    if read_result.skipped_reason or read_result.text is None:
        return ()

    try:
        tree = ast.parse(read_result.text, filename=relative_path)
    except SyntaxError:
        return ()

    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
    return tuple(symbols)


def _required_files_violations(repo_root: Path, spec: dict[str, Any]) -> list[ContractViolation]:
    violations: list[ContractViolation] = []

    for raw_path in spec.get("required_files", []) or []:
        if not isinstance(raw_path, str):
            violations.append(
                ContractViolation(
                    rule_id="required-file-invalid",
                    severity="error",
                    message="required_files entries must be strings.",
                    path=None,
                    line=None,
                    evidence=repr(raw_path),
                )
            )
            continue

        normalized = raw_path.replace("\\", "/").strip("/")
        if is_hard_excluded_relative(normalized):
            violations.append(
                ContractViolation(
                    rule_id="required-file-hard-excluded",
                    severity="error",
                    message=f"Required file points to a hard-excluded path: {normalized}",
                    path=normalized,
                    line=None,
                    evidence=normalized,
                )
            )
            continue

        if not (repo_root / normalized).is_file():
            violations.append(
                ContractViolation(
                    rule_id="required-file-missing",
                    severity="error",
                    message=f"Required file is missing: {normalized}",
                    path=normalized,
                    line=None,
                    evidence=normalized,
                )
            )

    return violations


def _required_symbols_violations(repo_root: Path, spec: dict[str, Any]) -> list[ContractViolation]:
    violations: list[ContractViolation] = []

    for entry in spec.get("required_symbols", []) or []:
        if not isinstance(entry, dict):
            violations.append(
                ContractViolation(
                    rule_id="required-symbol-entry-invalid",
                    severity="error",
                    message="required_symbols entries must be objects.",
                    path=None,
                    line=None,
                    evidence=repr(entry),
                )
            )
            continue

        raw_path = entry.get("path")
        raw_symbols = entry.get("symbols", [])

        if not isinstance(raw_path, str) or not isinstance(raw_symbols, list):
            violations.append(
                ContractViolation(
                    rule_id="required-symbol-entry-invalid",
                    severity="error",
                    message="required_symbols entries need string path and list symbols.",
                    path=raw_path if isinstance(raw_path, str) else None,
                    line=None,
                    evidence=repr(entry),
                )
            )
            continue

        relative_path = raw_path.replace("\\", "/").strip("/")
        available = set(_top_level_symbols(repo_root, relative_path))

        for symbol in raw_symbols:
            if not isinstance(symbol, str):
                violations.append(
                    ContractViolation(
                        rule_id="required-symbol-invalid",
                        severity="error",
                        message="Required symbol names must be strings.",
                        path=relative_path,
                        line=None,
                        evidence=repr(symbol),
                    )
                )
                continue

            if symbol not in available:
                violations.append(
                    ContractViolation(
                        rule_id="required-symbol-missing",
                        severity="error",
                        message=f"Required symbol is missing: {symbol}",
                        path=relative_path,
                        line=None,
                        evidence=symbol,
                    )
                )

    return violations


def _forbidden_import_violations(repo_root: Path, spec: dict[str, Any]) -> tuple[list[ContractViolation], int]:
    violations: list[ContractViolation] = []
    rules = spec.get("forbidden_imports", []) or []

    universe = discover_file_universe(repo_root)
    python_paths = [
        record.path
        for record in universe.included_files
        if Path(record.path).suffix.lower() in {".py", ".pyw", ".pyi"}
    ]

    for rule in rules:
        if not isinstance(rule, dict):
            violations.append(
                ContractViolation(
                    rule_id="forbidden-import-rule-invalid",
                    severity="error",
                    message="forbidden_imports entries must be objects.",
                    path=None,
                    line=None,
                    evidence=repr(rule),
                )
            )
            continue

        rule_id = str(rule.get("id") or "forbidden-import")
        from_pattern = rule.get("from")
        disallow = rule.get("disallow", [])

        if not isinstance(from_pattern, str) or not isinstance(disallow, list):
            violations.append(
                ContractViolation(
                    rule_id=rule_id,
                    severity="error",
                    message="Forbidden import rule needs string 'from' and list 'disallow'.",
                    path=None,
                    line=None,
                    evidence=repr(rule),
                )
            )
            continue

        disallowed_prefixes = [item for item in disallow if isinstance(item, str)]

        for path in python_paths:
            if not _path_matches(from_pattern, path):
                continue

            for line, imported, raw in _import_edges_for_file(repo_root, path):
                for prefix in disallowed_prefixes:
                    if imported == prefix or imported.startswith(prefix + "."):
                        violations.append(
                            ContractViolation(
                                rule_id=rule_id,
                                severity="error",
                                message=f"Forbidden import from {path}: {imported}",
                                path=path,
                                line=line,
                                evidence=raw,
                            )
                        )

    return violations, len(python_paths)


def evaluate_contract(repo_root: str | Path, spec: dict[str, Any] | None = None) -> ContractResult:
    root = Path(repo_root).resolve()
    payload = spec or builtin_cbl_contract()

    contract_id = str(payload.get("id") or "unnamed-contract")
    name = str(payload.get("name") or contract_id)

    violations: list[ContractViolation] = []
    warnings: list[str] = []

    violations.extend(_required_files_violations(root, payload))
    violations.extend(_required_symbols_violations(root, payload))
    import_violations, python_files_checked = _forbidden_import_violations(root, payload)
    violations.extend(import_violations)

    required_files_count = len(payload.get("required_files", []) or [])
    required_symbols_count = sum(
        len(entry.get("symbols", []))
        for entry in payload.get("required_symbols", []) or []
        if isinstance(entry, dict) and isinstance(entry.get("symbols", []), list)
    )
    forbidden_import_rules_count = len(payload.get("forbidden_imports", []) or [])

    error_count = sum(1 for item in violations if item.severity == "error")
    warning_count = sum(1 for item in violations if item.severity == "warning") + len(warnings)

    return ContractResult(
        contract_id=contract_id,
        name=name,
        violations=tuple(sorted(violations, key=lambda item: (item.severity, item.rule_id, item.path or "", item.line or 0))),
        warnings=tuple(warnings),
        counts={
            "violations": len(violations),
            "errors": error_count,
            "warnings": warning_count,
            "required_files_checked": required_files_count,
            "required_symbols_checked": required_symbols_count,
            "forbidden_import_rules_checked": forbidden_import_rules_count,
            "python_files_checked": python_files_checked,
        },
    )
''',

    "tests/test_contract_integration.py": r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


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


def test_builtin_contract_and_custom_violation_contract(tmp_path: Path) -> None:
    builtin = run_cbl("contract", "--no-archive")
    assert builtin.returncode == 0, builtin.stdout + builtin.stderr
    assert "CBL contract: OK" in builtin.stdout
    assert "C:\\Users\\" not in builtin.stdout

    builtin_path = ROOT / ".codecontext" / "latest" / "contract_report.json"
    manifest_path = ROOT / ".codecontext" / "latest" / "manifest.json"

    assert builtin_path.is_file()
    assert manifest_path.is_file()

    builtin_payload = json.loads(builtin_path.read_text(encoding="utf-8"))
    assert builtin_payload["counts"]["errors"] == 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "contract"
    assert manifest["outputs"]["contract_report_json"] == ".codecontext/latest/contract_report.json"
    assert manifest["repo"]["root"] == "<redacted>"

    repo = tmp_path / "contract_repo"
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
    assert violated.returncode == 0, violated.stdout + violated.stderr
    assert "Violations: 1" in violated.stdout

    report = json.loads((repo / ".codecontext" / "latest" / "contract_report.json").read_text(encoding="utf-8"))
    assert report["counts"]["errors"] == 1
    assert report["violations"][0]["rule_id"] == "no-forbidden"
''',

    "scripts/dev/audits/audit_phase7_contracts.py": r'''
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
''',
}


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative_path: str, content: str) -> None:
    target = ROOT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(normalize(content), encoding="utf-8", newline="\n")


def patch_constants() -> None:
    path = ROOT / "src/codebase_lens/core/constants.py"
    text = path.read_text(encoding="utf-8")

    if "EXIT_CONTRACT_FAILURE" in text:
        return

    marker = "EXIT_PATH_SAFETY_VIOLATION = 4\n"
    if marker not in text:
        raise RuntimeError("Could not patch constants.py: EXIT_PATH_SAFETY_VIOLATION marker not found.")

    text = text.replace(marker, marker + "EXIT_CONTRACT_FAILURE = 5\n", 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_reports_json() -> None:
    path = ROOT / "src/codebase_lens/reports/json.py"
    text = path.read_text(encoding="utf-8")

    if "contract_result_payload" in text:
        return

    import_marker = "from codebase_lens.analyzers.tests import TestInventoryResult\n"
    if import_marker not in text:
        raise RuntimeError("Could not patch reports/json.py: TestInventoryResult import marker not found.")

    text = text.replace(
        import_marker,
        import_marker + "from codebase_lens.contracts.architecture import ContractResult\n",
        1,
    )

    append = r'''


def contract_result_payload(result: ContractResult) -> dict[str, Any]:
    return {
        "contract_id": result.contract_id,
        "name": result.name,
        "violations": [asdict(record) for record in result.violations],
        "warnings": list(result.warnings),
        "counts": dict(result.counts),
    }
'''
    text = text.rstrip() + append + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_cli() -> None:
    path = ROOT / "src/codebase_lens/cli.py"
    text = path.read_text(encoding="utf-8")

    replacements = [
        (
            "from codebase_lens.analyzers.tests import collect_test_inventory\n",
            "from codebase_lens.analyzers.tests import collect_test_inventory\n"
            "from codebase_lens.contracts.architecture import evaluate_contract, load_contract_spec\n",
        ),
        (
            "    EXIT_GENERAL_ERROR,\n"
            "    EXIT_INVALID_ARGUMENTS,\n",
            "    EXIT_CONTRACT_FAILURE,\n"
            "    EXIT_GENERAL_ERROR,\n"
            "    EXIT_INVALID_ARGUMENTS,\n",
        ),
        (
            "    caller_records_payload,\n"
            "    changed_files_payload,\n",
            "    caller_records_payload,\n"
            "    changed_files_payload,\n"
            "    contract_result_payload,\n",
        ),
        (
            "    contract.set_defaults(handler=_run_partial)\n",
            "    contract.set_defaults(handler=_run_contract)\n",
        ),
    ]

    for old, new in replacements:
        if old not in text:
            if new in text:
                continue
            raise RuntimeError(f"Could not patch cli.py; missing expected marker:\n{old}")
        text = text.replace(old, new, 1)

    insert_before = "\ndef _run_tests_inventory(args: argparse.Namespace) -> int:\n"
    if insert_before not in text:
        raise RuntimeError("Could not patch cli.py: _run_tests_inventory insertion marker not found.")

    if "def _run_contract(args: argparse.Namespace)" not in text:
        inserted = r'''

def _run_contract(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root
        spec = load_contract_spec(repo_root, args.spec)
        result = evaluate_contract(repo_root, spec)
        payload = contract_result_payload(result)

        layout = prepare_output_layout(repo_root, args.out, archive=not args.no_archive)
        contract_path = write_json_report(layout.latest_dir / "contract_report.json", payload)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "contract",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "contract_report_json": ".codecontext/latest/contract_report.json",
                },
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)
        copy_latest_to_run(layout)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except PathSafetyError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_PATH_SAFETY_VIOLATION
    except ValueError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_INVALID_ARGUMENTS
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not write contract report: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        status = "OK" if result.counts["errors"] == 0 else "VIOLATIONS"
        print(f"CBL contract: {status}")
        print(f"Contract: {result.name}")
        print(f"Violations: {result.counts['violations']}")
        print(f"Errors: {result.counts['errors']}")
        print(f"Warnings: {result.counts['warnings']}")
        print(f"Python files checked: {result.counts['python_files_checked']}")
        print(f"Contract report: {display_path(repo_root, contract_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")

    if result.counts["errors"] and not args.no_fail_exit:
        return EXIT_CONTRACT_FAILURE

    return 0

'''
        text = text.replace(insert_before, inserted + insert_before, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_constants()
    patch_reports_json()
    patch_cli()

    print("Slice 008 applied: Phase 7 architecture contracts implemented.")
    print("Run the Phase 7 audit and integration tests before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())