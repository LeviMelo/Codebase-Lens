from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

COMMAND_SURFACE = r'''
from __future__ import annotations

import argparse
import json
import os
import shutil
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
    "tree.md",
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


def _load_cli_objects() -> tuple[Any, Any]:
    from codebase_lens import cli

    public_commands = getattr(cli, "PUBLIC_COMMANDS", None)
    build_parser = getattr(cli, "build_parser", None)
    if public_commands is None:
        raise RuntimeError("codebase_lens.cli.PUBLIC_COMMANDS is missing.")
    if build_parser is None:
        raise RuntimeError("codebase_lens.cli.build_parser is missing.")
    return public_commands, build_parser


def _parser_subcommands(parser: argparse.ArgumentParser) -> tuple[str, ...]:
    commands: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            commands.update(str(name) for name in action.choices)
    return tuple(sorted(commands))


def inspect_public_command_surface() -> tuple[tuple[str, ...], tuple[str, ...], tuple[CommandSurfaceIssue, ...]]:
    issues: list[CommandSurfaceIssue] = []

    try:
        public_commands_obj, build_parser = _load_cli_objects()
    except Exception as exc:  # pragma: no cover - exercised by audit subprocess on failure
        return (), (), (
            CommandSurfaceIssue(
                severity="error",
                code="cli_import_failed",
                message="Could not import CLI public command surface.",
                details={"exception": repr(exc)},
            ),
        )

    public_commands = tuple(sorted(str(command) for command in public_commands_obj))

    try:
        parser = build_parser()
    except Exception as exc:
        return public_commands, (), (
            CommandSurfaceIssue(
                severity="error",
                code="build_parser_failed",
                message="build_parser() raised an exception.",
                details={"exception": repr(exc)},
            ),
        )

    parser_commands = _parser_subcommands(parser)

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
'''

AUDIT = r'''
from __future__ import annotations

import ast
import json
import os
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
        "src/codebase_lens/cli.py",
        "src/codebase_lens/contracts/command_surface.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.contracts.command_surface import (
        audit_command_surface,
        write_command_surface_audit_report,
    )

    result = audit_command_surface(include_help=True, include_external_pack=True)

    latest = ROOT / ".codecontext" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    report_path = latest / "command_surface_audit.json"
    write_command_surface_audit_report(report_path, result)

    if not report_path.is_file():
        fail("command_surface_audit.json was not written.")

    payload = json.loads(report_path.read_text(encoding="utf-8"))

    if payload.get("schema", {}).get("name") != "cbl.command_surface_audit":
        fail("command surface audit report has wrong schema name.")

    if not result.ok:
        formatted = json.dumps(payload.get("issues", []), indent=2, sort_keys=True)
        fail(f"Public command stability gate failed:\n{formatted}")

    public_commands = set(payload.get("public_commands", []))
    parser_subcommands = set(payload.get("parser_subcommands", []))
    if public_commands != parser_subcommands:
        fail(f"Public command mismatch: public={sorted(public_commands)} parser={sorted(parser_subcommands)}")

    if len(public_commands) < 10:
        fail(f"Unexpectedly small public command surface: {sorted(public_commands)}")

    external = payload.get("external_repo", {})
    if not external.get("manifest_exists"):
        fail("External --repo pack did not write manifest.json.")
    if not external.get("projection_exists"):
        fail("External --repo pack did not write handoff_projection.json.")
    if external.get("missing_core_artifacts"):
        fail(f"External --repo pack missed core artifacts: {external['missing_core_artifacts']}")
    if external.get("scanned_codecontext_paths"):
        fail(f"External --repo pack recursively scanned .codecontext: {external['scanned_codecontext_paths']}")

    print("PASS: Phase 20 public command stability audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST = r'''
from __future__ import annotations

import json
from pathlib import Path

from codebase_lens.contracts.command_surface import (
    audit_command_surface,
    command_surface_result_payload,
    inspect_public_command_surface,
)


def test_public_commands_match_argparse_subcommands() -> None:
    public_commands, parser_subcommands, issues = inspect_public_command_surface()

    assert not issues
    assert public_commands
    assert set(public_commands) == set(parser_subcommands)
    assert "pack" in public_commands
    assert "graph" in public_commands
    assert "contract" in public_commands


def test_command_surface_help_and_external_repo_pack_are_stable() -> None:
    result = audit_command_surface(include_help=True, include_external_pack=True)
    payload = command_surface_result_payload(result)

    assert result.ok, json.dumps(payload["issues"], indent=2, sort_keys=True)
    assert payload["schema"]["name"] == "cbl.command_surface_audit"
    assert set(payload["public_commands"]) == set(payload["parser_subcommands"])

    external = payload["external_repo"]
    assert external["manifest_exists"]
    assert external["projection_exists"]
    assert external["evidence_graph_exists"]
    assert not external["missing_core_artifacts"]
    assert not external["scanned_codecontext_paths"]
    assert "src/demo_pkg/" in external["projection_source_prefixes"]
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
        "src/codebase_lens/contracts/command_surface.py",
        "scripts/dev/audits/audit_phase20_public_command_stability.py",
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

    write_file("src/codebase_lens/contracts/command_surface.py", COMMAND_SURFACE, modified)
    write_file("scripts/dev/audits/audit_phase20_public_command_stability.py", AUDIT, modified)
    write_file("tests/test_public_command_stability.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 016 applied: public command stability gate added.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())