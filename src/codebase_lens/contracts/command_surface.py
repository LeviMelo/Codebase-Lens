from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandSurfaceIssue:
    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandSurfaceAuditResult:
    ok: bool
    public_commands: tuple[str, ...]
    parser_subcommands: tuple[str, ...]
    issues: tuple[CommandSurfaceIssue, ...]
    external_repo: dict[str, Any]


# These are mandatory artifacts for `cbl pack`.
# Do not include command-specific artifacts such as `tree.md`, which belongs to
# the tree-report command surface rather than the handoff pack contract.
CORE_EXTERNAL_PACK_ARTIFACTS = (
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


def _run_python_module(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codebase_lens", *args],
        cwd=cwd,
        env=_python_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )








def _read_source(relative_path: str) -> str:
    return (_repo_root() / relative_path).read_text(encoding="utf-8")


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _public_commands_from_constants_source() -> tuple[str, ...]:
    text = _read_source("src/codebase_lens/core/constants.py")
    tree = ast.parse(text, filename="src/codebase_lens/core/constants.py")

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        if not any(isinstance(target, ast.Name) and target.id == "PUBLIC_COMMANDS" for target in node.targets):
            continue

        if not isinstance(node.value, (ast.Tuple, ast.List)):
            raise RuntimeError("PUBLIC_COMMANDS must be a literal tuple or list of strings.")

        values: list[str] = []
        for item in node.value.elts:
            literal = _literal_string(item)
            if literal is None:
                raise RuntimeError("PUBLIC_COMMANDS contains a non-literal or non-string item.")
            values.append(literal)

        return tuple(sorted(values))

    raise RuntimeError("PUBLIC_COMMANDS assignment not found in src/codebase_lens/core/constants.py.")


def _parser_subcommands_from_cli_source() -> tuple[str, ...]:
    text = _read_source("src/codebase_lens/cli.py")
    tree = ast.parse(text, filename="src/codebase_lens/cli.py")

    commands: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if not isinstance(func, ast.Attribute):
            continue

        if func.attr != "add_parser":
            continue

        if not node.args:
            continue

        command_name = _literal_string(node.args[0])
        if command_name:
            commands.add(command_name)

    return tuple(sorted(commands))


def inspect_public_command_surface() -> tuple[tuple[str, ...], tuple[str, ...], tuple[CommandSurfaceIssue, ...]]:
    issues: list[CommandSurfaceIssue] = []

    try:
        public_commands = _public_commands_from_constants_source()
    except Exception as exc:
        return (), (), (
            CommandSurfaceIssue(
                severity="error",
                code="public_commands_static_parse_failed",
                message="Could not statically parse PUBLIC_COMMANDS.",
                details={"exception": repr(exc)},
            ),
        )

    try:
        parser_commands = _parser_subcommands_from_cli_source()
    except Exception as exc:
        return public_commands, (), (
            CommandSurfaceIssue(
                severity="error",
                code="parser_commands_static_parse_failed",
                message="Could not statically parse argparse subcommands from cli.py.",
                details={"exception": repr(exc)},
            ),
        )

    missing_from_parser = sorted(set(public_commands) - set(parser_commands))
    missing_from_public = sorted(set(parser_commands) - set(public_commands))

    if missing_from_parser:
        issues.append(
            CommandSurfaceIssue(
                severity="error",
                code="public_command_missing_from_parser",
                message="PUBLIC_COMMANDS contains commands that are not registered in argparse.",
                details={"commands": missing_from_parser},
            )
        )

    if missing_from_public:
        issues.append(
            CommandSurfaceIssue(
                severity="error",
                code="parser_command_missing_from_public_commands",
                message="Argparse registers commands that are absent from PUBLIC_COMMANDS.",
                details={"commands": missing_from_public},
            )
        )

    if not public_commands:
        issues.append(
            CommandSurfaceIssue(
                severity="error",
                code="empty_public_commands",
                message="PUBLIC_COMMANDS is empty.",
            )
        )

    return public_commands, parser_commands, tuple(issues)

def run_help_smoke_checks(public_commands: tuple[str, ...]) -> tuple[CommandSurfaceIssue, ...]:
    issues: list[CommandSurfaceIssue] = []
    root = _repo_root()

    top = _run_python_module(["--help"], cwd=root, timeout=20)
    if top.returncode != 0:
        issues.append(
            CommandSurfaceIssue(
                severity="error",
                code="top_level_help_failed",
                message="Top-level CLI --help failed.",
                details={"returncode": top.returncode, "stdout": top.stdout[-1000:], "stderr": top.stderr[-1000:]},
            )
        )
    elif "usage:" not in top.stdout.lower():
        issues.append(
            CommandSurfaceIssue(
                severity="error",
                code="top_level_help_missing_usage",
                message="Top-level CLI --help did not emit usage text.",
                details={"stdout": top.stdout[:1000]},
            )
        )

    for command in public_commands:
        result = _run_python_module([command, "--help"], cwd=root, timeout=20)
        if result.returncode != 0:
            issues.append(
                CommandSurfaceIssue(
                    severity="error",
                    code="subcommand_help_failed",
                    message=f"Subcommand help failed for {command!r}.",
                    details={
                        "command": command,
                        "returncode": result.returncode,
                        "stdout": result.stdout[-1000:],
                        "stderr": result.stderr[-1000:],
                    },
                )
            )
            continue

        output = result.stdout.lower()
        if "usage:" not in output:
            issues.append(
                CommandSurfaceIssue(
                    severity="error",
                    code="subcommand_help_missing_usage",
                    message=f"Subcommand help for {command!r} did not emit usage text.",
                    details={"command": command, "stdout": result.stdout[:1000]},
                )
            )

    return tuple(issues)


def _write_synthetic_external_repo(base: Path) -> Path:
    repo = base / "external_target_repo"
    package = repo / "src" / "demo_pkg"
    tests = repo / "tests"
    package.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    (repo / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                "name = 'demo-pkg'",
                "version = '0.0.0'",
                "",
            ]
        ),
        encoding="utf-8",
    )

    # This must never execute. CBL should parse target code statically, not import it.
    (package / "__init__.py").write_text(
        "raise RuntimeError('CBL imported the target repository package')\n",
        encoding="utf-8",
    )

    (package / "core.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "class Thing:",
                "    def __init__(self, name: str) -> None:",
                "        self.name = name",
                "",
                "def normalize_name(name: str) -> str:",
                "    return name.strip().lower()",
                "",
                "def build_thing(name: str) -> Thing:",
                "    return Thing(normalize_name(name))",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (package / "cli.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "import argparse",
                "from demo_pkg.core import build_thing",
                "",
                "def _run_build(raw: str) -> str:",
                "    thing = build_thing(raw)",
                "    return thing.name",
                "",
                "def build_parser() -> argparse.ArgumentParser:",
                "    parser = argparse.ArgumentParser()",
                "    sub = parser.add_subparsers(dest='command')",
                "    build = sub.add_parser('build')",
                "    build.set_defaults(handler=_run_build)",
                "    return parser",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_core.py").write_text(
        "\n".join(
            [
                "from demo_pkg.core import normalize_name",
                "",
                "def test_normalize_name():",
                "    assert normalize_name('  A  ') == 'a'",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def _graph_node_paths(evidence_graph_path: Path) -> list[str]:
    if not evidence_graph_path.is_file():
        return []

    payload = json.loads(evidence_graph_path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", [])
    paths: list[str] = []
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("path"), str):
                paths.append(node["path"])
    return paths


def run_external_repo_pack_check() -> tuple[dict[str, Any], tuple[CommandSurfaceIssue, ...]]:
    issues: list[CommandSurfaceIssue] = []

    with tempfile.TemporaryDirectory(prefix="cbl_command_surface_") as temp_dir:
        workspace = Path(temp_dir)
        target_repo = _write_synthetic_external_repo(workspace)
        runner_cwd = workspace / "runner"
        runner_cwd.mkdir(parents=True, exist_ok=True)

        result = _run_python_module(
            [
                "pack",
                "--repo",
                str(target_repo),
                "--issue",
                "external repo command surface audit",
                "--budget",
                "12000",
                "--no-archive",
            ],
            cwd=runner_cwd,
            timeout=45,
        )

        latest = target_repo / ".codecontext" / "latest"
        manifest_path = latest / "manifest.json"
        projection_path = latest / "handoff_projection.json"
        evidence_graph_path = latest / "evidence_graph.json"

        external_report: dict[str, Any] = {
            "target_repo": str(target_repo),
            "runner_cwd": str(runner_cwd),
            "returncode": result.returncode,
            "latest_dir_exists": latest.is_dir(),
            "manifest_exists": manifest_path.is_file(),
            "projection_exists": projection_path.is_file(),
            "evidence_graph_exists": evidence_graph_path.is_file(),
            "missing_core_artifacts": [],
            "scanned_codecontext_paths": [],
            "projection_source_prefixes": [],
            "stdout_tail": result.stdout[-1000:],
            "stderr_tail": result.stderr[-1000:],
        }

        if result.returncode != 0:
            issues.append(
                CommandSurfaceIssue(
                    severity="error",
                    code="external_repo_pack_failed",
                    message="cbl pack --repo failed from outside the target repository.",
                    details=external_report,
                )
            )
            return external_report, tuple(issues)

        missing = [
            artifact
            for artifact in CORE_EXTERNAL_PACK_ARTIFACTS
            if not (latest / artifact).is_file()
        ]
        external_report["missing_core_artifacts"] = missing
        if missing:
            issues.append(
                CommandSurfaceIssue(
                    severity="error",
                    code="external_repo_pack_missing_artifacts",
                    message="External repo pack did not write all core latest/ artifacts.",
                    details={"missing": missing},
                )
            )

        scanned_codecontext = [
            path
            for path in _graph_node_paths(evidence_graph_path)
            if path.startswith(".codecontext/") or "/.codecontext/" in path or "\\.codecontext\\" in path
        ]
        external_report["scanned_codecontext_paths"] = scanned_codecontext
        if scanned_codecontext:
            issues.append(
                CommandSurfaceIssue(
                    severity="error",
                    code="codecontext_recursively_scanned",
                    message=".codecontext was scanned as target source in the external repo pack.",
                    details={"paths": scanned_codecontext[:20]},
                )
            )

        if projection_path.is_file():
            projection = json.loads(projection_path.read_text(encoding="utf-8"))
            prefixes = projection.get("project_profile", {}).get("source_prefixes", [])
            external_report["projection_source_prefixes"] = prefixes
            if "src/demo_pkg/" not in prefixes:
                issues.append(
                    CommandSurfaceIssue(
                        severity="error",
                        code="external_repo_source_prefix_not_inferred",
                        message="External repo projection did not infer the synthetic package source prefix.",
                        details={"source_prefixes": prefixes},
                    )
                )

            projection_blob = json.dumps(projection, sort_keys=True)
            if "CBL imported the target repository package" in projection_blob:
                issues.append(
                    CommandSurfaceIssue(
                        severity="error",
                        code="target_repo_import_side_effect_seen",
                        message="Projection contains the target import side-effect marker.",
                    )
                )

    return external_report, tuple(issues)


def audit_command_surface(*, include_help: bool = True, include_external_pack: bool = True) -> CommandSurfaceAuditResult:
    public_commands, parser_commands, parity_issues = inspect_public_command_surface()
    issues: list[CommandSurfaceIssue] = list(parity_issues)
    external_repo: dict[str, Any] = {}

    if include_help:
        issues.extend(run_help_smoke_checks(public_commands))

    if include_external_pack:
        external_repo, external_issues = run_external_repo_pack_check()
        issues.extend(external_issues)

    ok = not any(issue.severity == "error" for issue in issues)

    return CommandSurfaceAuditResult(
        ok=ok,
        public_commands=public_commands,
        parser_subcommands=parser_commands,
        issues=tuple(issues),
        external_repo=external_repo,
    )


def command_surface_result_payload(result: CommandSurfaceAuditResult) -> dict[str, Any]:
    return {
        "schema": {
            "name": "cbl.command_surface_audit",
            "version": 1,
        },
        "ok": result.ok,
        "public_commands": list(result.public_commands),
        "parser_subcommands": list(result.parser_subcommands),
        "counts": {
            "public_commands": len(result.public_commands),
            "parser_subcommands": len(result.parser_subcommands),
            "issues": len(result.issues),
            "errors": sum(1 for issue in result.issues if issue.severity == "error"),
            "warnings": sum(1 for issue in result.issues if issue.severity == "warning"),
        },
        "issues": [asdict(issue) for issue in result.issues],
        "external_repo": result.external_repo,
    }


def write_command_surface_audit_report(path: str | Path, result: CommandSurfaceAuditResult) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(command_surface_result_payload(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
