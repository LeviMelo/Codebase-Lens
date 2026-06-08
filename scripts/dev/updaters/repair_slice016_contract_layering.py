from __future__ import annotations

import ast
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()
TARGET = ROOT / "src" / "codebase_lens" / "contracts" / "command_surface.py"
TEST_TARGET = ROOT / "tests" / "test_public_command_stability.py"


STATIC_INSPECT_BLOCK = r'''
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
'''


TEST_REPLACEMENT = r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from codebase_lens.contracts.command_surface import (
    audit_command_surface,
    command_surface_result_payload,
    inspect_public_command_surface,
)

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


def test_command_surface_contract_module_does_not_import_cli_layer() -> None:
    source = (ROOT / "src" / "codebase_lens" / "contracts" / "command_surface.py").read_text(encoding="utf-8")

    assert "from codebase_lens import cli" not in source
    assert "import codebase_lens.cli" not in source
    assert "codebase_lens.cli" not in source

    contract = run_cbl("contract", "--no-archive")
    assert contract.returncode == 0, contract.stdout + contract.stderr
'''


def normalize(text: str) -> str:
    return dedent(text).strip("\n") + "\n"


def remove_functions(source: str, names: set[str]) -> str:
    tree = ast.parse(source)
    spans: list[tuple[int, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            if node.end_lineno is None:
                raise RuntimeError(f"AST node for {node.name} has no end_lineno.")
            spans.append((node.lineno, node.end_lineno))

    lines = source.splitlines()
    remove_lines: set[int] = set()
    for start, end in spans:
        remove_lines.update(range(start, end + 1))

    return "\n".join(
        line
        for index, line in enumerate(lines, start=1)
        if index not in remove_lines
    ).rstrip() + "\n"


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")

    source = source.replace("import argparse\n", "import ast\n")
    source = source.replace("import shutil\n", "")

    source = remove_functions(
        source,
        {
            "_load_cli_objects",
            "_parser_subcommands",
            "inspect_public_command_surface",
        },
    )

    marker = "def run_help_smoke_checks(public_commands: tuple[str, ...]) -> tuple[CommandSurfaceIssue, ...]:"
    if marker not in source:
        raise RuntimeError("Could not find run_help_smoke_checks insertion marker.")

    source = source.replace(marker, normalize(STATIC_INSPECT_BLOCK) + "\n" + marker)

    ast.parse(source)
    TARGET.write_text(source, encoding="utf-8", newline="\n")

    TEST_TARGET.write_text(normalize(TEST_REPLACEMENT), encoding="utf-8", newline="\n")
    ast.parse(TEST_TARGET.read_text(encoding="utf-8"))

    print("Slice 016 contract-layering repair applied.")
    print("command_surface.py now inspects PUBLIC_COMMANDS and argparse subcommands statically without importing cli.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())