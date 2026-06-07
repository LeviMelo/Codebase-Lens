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


def make_static_surface_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "surface_repo"
    app = repo / "src" / "demo"
    app.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'surface-repo'\n", encoding="utf-8")

    (app / "commands.py").write_text(
        "\n".join(
            [
                "import argparse",
                "import click",
                "import typer",
                "",
                "typer_app = typer.Typer()",
                "",
                "@typer_app.command('serve')",
                "def serve_app(port: int = 8000):",
                "    return port",
                "",
                "@click.command(name='sync')",
                "def sync_command():",
                "    return None",
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

    (app / "routes.py").write_text(
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


def test_static_surface_commands_integrate_scanner_analyzers_reports_and_manifest(tmp_path: Path) -> None:
    repo = make_static_surface_repo(tmp_path)

    cli_result = run_cbl("cli", "--repo", str(repo), "--no-archive")
    assert cli_result.returncode == 0, cli_result.stdout + cli_result.stderr
    assert "CBL cli: OK" in cli_result.stdout
    assert "C:\\Users\\" not in cli_result.stdout

    commands_path = repo / ".codecontext" / "latest" / "commands.json"
    manifest_path = repo / ".codecontext" / "latest" / "manifest.json"
    assert commands_path.is_file()
    assert manifest_path.is_file()

    commands_payload = json.loads(commands_path.read_text(encoding="utf-8"))
    command_paths = {record["command_path"] for record in commands_payload["commands"]}

    assert {"serve", "sync", "doctor"} <= command_paths
    assert commands_payload["counts"]["typer"] >= 1
    assert commands_payload["counts"]["click"] >= 1
    assert commands_payload["counts"]["argparse"] >= 1

    cli_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert cli_manifest["command"]["subcommand"] == "cli"
    assert cli_manifest["outputs"]["commands_json"] == ".codecontext/latest/commands.json"

    routes_result = run_cbl("routes", "--repo", str(repo), "--no-archive")
    assert routes_result.returncode == 0, routes_result.stdout + routes_result.stderr
    assert "CBL routes: OK" in routes_result.stdout
    assert "C:\\Users\\" not in routes_result.stdout

    routes_path = repo / ".codecontext" / "latest" / "routes.json"
    assert routes_path.is_file()

    routes_payload = json.loads(routes_path.read_text(encoding="utf-8"))
    route_keys = {(record["method"], record["route_path"]) for record in routes_payload["routes"]}

    assert ("GET", "/health") in route_keys
    assert ("POST", "/items") in route_keys
    assert ("GET", "/legacy") in route_keys
    assert ("POST", "/legacy") in route_keys

    routes_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert routes_manifest["command"]["subcommand"] == "routes"
    assert routes_manifest["outputs"]["routes_json"] == ".codecontext/latest/routes.json"


def test_explicit_repo_inside_larger_git_tree_is_honored(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)

    subprocess.run(["git", "init"], cwd=outer, text=True, capture_output=True, check=False)

    (inner / "pyproject.toml").write_text("[project]\nname = 'inner'\n", encoding="utf-8")
    (inner / "app.py").write_text("print('inner')\n", encoding="utf-8")

    result = run_cbl("tree", "--repo", str(inner), "--no-archive")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repository: inner" in result.stdout
    assert (inner / ".codecontext" / "latest" / "repo_tree.txt").is_file()
