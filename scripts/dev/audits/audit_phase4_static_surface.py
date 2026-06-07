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
    "src/codebase_lens/analyzers/cli_static.py": [
        "CliStaticAnalysisResult",
        "collect_cli_commands_for_file",
        "collect_cli_commands",
        "flatten_cli_results",
    ],
    "src/codebase_lens/analyzers/routes_static.py": [
        "RouteStaticAnalysisResult",
        "collect_routes_for_file",
        "collect_routes",
        "flatten_route_results",
    ],
    "src/codebase_lens/reports/json.py": [
        "command_records_payload",
        "route_records_payload",
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


def make_surface_repo(base: Path) -> Path:
    repo = base / "surface_repo"
    package = repo / "src" / "demo"
    package.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'surface-repo'\n", encoding="utf-8")
    (package / "commands.py").write_text(
        "\n".join(
            [
                "import argparse",
                "import click",
                "import typer",
                "",
                "app = typer.Typer()",
                "",
                "@app.command('serve')",
                "def serve():",
                "    pass",
                "",
                "@click.command(name='sync')",
                "def sync_command():",
                "    pass",
                "",
                "def build_parser():",
                "    parser = argparse.ArgumentParser()",
                "    sub = parser.add_subparsers(dest='command')",
                "    doctor = sub.add_parser('doctor', help='check readiness')",
                "    doctor.set_defaults(handler=run_doctor)",
                "    return parser",
                "",
                "def run_doctor(args):",
                "    return 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (package / "routes.py").write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "from flask import Flask",
                "",
                "router = APIRouter()",
                "app = Flask(__name__)",
                "",
                "@router.get('/health')",
                "def health():",
                "    return {'ok': True}",
                "",
                "@router.post('/items')",
                "def create_item():",
                "    return {'id': 1}",
                "",
                "@app.route('/legacy', methods=['GET', 'POST'])",
                "def legacy():",
                "    return 'legacy'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return repo


def main() -> int:
    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    project_cli = run_cbl("cli", "--path", "src/codebase_lens/cli.py", "--no-archive")
    if project_cli.returncode != 0:
        fail(f"cbl cli on project cli.py failed:\nSTDOUT:\n{project_cli.stdout}\nSTDERR:\n{project_cli.stderr}")
    if "CBL cli: OK" not in project_cli.stdout:
        fail("cbl cli did not report success.")
    if "C:\\Users\\" in project_cli.stdout:
        fail("cbl cli leaked an absolute Windows user path.")

    commands_path = ROOT / ".codecontext" / "latest" / "commands.json"
    if not commands_path.is_file():
        fail("cbl cli did not write commands.json.")

    commands_payload = json.loads(commands_path.read_text(encoding="utf-8"))
    project_commands = {record["command_path"] for record in commands_payload["commands"]}
    required_project_commands = {"doctor", "tree", "symbols", "imports", "cli", "routes", "pack"}
    if not required_project_commands <= project_commands:
        fail(f"commands.json is missing project commands: {sorted(required_project_commands - project_commands)}")

    with tempfile.TemporaryDirectory() as tmp:
        repo = make_surface_repo(Path(tmp))

        cli_result = run_cbl("cli", "--repo", str(repo), "--no-archive")
        if cli_result.returncode != 0:
            fail(f"fixture cbl cli failed:\nSTDOUT:\n{cli_result.stdout}\nSTDERR:\n{cli_result.stderr}")
        if "C:\\Users\\" in cli_result.stdout:
            fail("fixture cbl cli leaked an absolute Windows user path.")

        fixture_commands = json.loads((repo / ".codecontext" / "latest" / "commands.json").read_text(encoding="utf-8"))
        command_paths = {record["command_path"] for record in fixture_commands["commands"]}
        if not {"serve", "sync", "doctor"} <= command_paths:
            fail(f"fixture commands missing expected commands: {sorted({'serve', 'sync', 'doctor'} - command_paths)}")
        if fixture_commands["counts"]["typer"] < 1 or fixture_commands["counts"]["click"] < 1 or fixture_commands["counts"]["argparse"] < 1:
            fail("fixture command framework counts are invalid.")

        routes_result = run_cbl("routes", "--repo", str(repo), "--no-archive")
        if routes_result.returncode != 0:
            fail(f"fixture cbl routes failed:\nSTDOUT:\n{routes_result.stdout}\nSTDERR:\n{routes_result.stderr}")
        if "C:\\Users\\" in routes_result.stdout:
            fail("fixture cbl routes leaked an absolute Windows user path.")

        routes_payload = json.loads((repo / ".codecontext" / "latest" / "routes.json").read_text(encoding="utf-8"))
        route_keys = {(record["method"], record["route_path"]) for record in routes_payload["routes"]}
        required_routes = {("GET", "/health"), ("POST", "/items"), ("GET", "/legacy"), ("POST", "/legacy")}
        if not required_routes <= route_keys:
            fail(f"fixture routes missing expected routes: {sorted(required_routes - route_keys)}")

        manifest = json.loads((repo / ".codecontext" / "latest" / "manifest.json").read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "routes":
            fail("manifest command.subcommand is not routes after cbl routes.")
        if manifest["outputs"].get("routes_json") != ".codecontext/latest/routes.json":
            fail("manifest does not declare routes_json.")

    print("PASS: Phase 4 static surface audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
