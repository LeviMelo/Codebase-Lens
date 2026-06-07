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


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "snapshot_pack_repo"
    package = repo / "src" / "demo"
    tests = repo / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)

    (repo / "pyproject.toml").write_text("[project]\nname = 'snapshot-pack-repo'\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".codecontext/\n", encoding="utf-8")

    (package / "app.py").write_text(
        "\n".join(
            [
                "import argparse",
                "",
                "def target(value):",
                "    return value + 1",
                "",
                "def build_parser():",
                "    parser = argparse.ArgumentParser()",
                "    sub = parser.add_subparsers(dest='command')",
                "    run = sub.add_parser('run')",
                "    run.set_defaults(handler=target)",
                "    return parser",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (tests / "test_app.py").write_text(
        "\n".join(
            [
                "from demo.app import target",
                "",
                "def test_target():",
                "    assert target(1) == 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return repo


def test_snapshot_and_pack_generate_coherent_handoff_outputs(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    snapshot = run_cbl("snapshot", "--repo", str(repo), "--no-archive")
    assert snapshot.returncode == 0, snapshot.stdout + snapshot.stderr
    assert "CBL snapshot: OK" in snapshot.stdout
    assert "C:\\Users\\" not in snapshot.stdout

    latest = repo / ".codecontext" / "latest"
    expected_snapshot = {
        "file_inventory.json",
        "repo_tree.txt",
        "symbols.json",
        "imports.json",
        "commands.json",
        "routes.json",
        "tests_inventory.json",
        "snapshot_index.json",
        "manifest.json",
    }
    assert expected_snapshot <= {item.name for item in latest.iterdir()}

    snapshot_index = json.loads((latest / "snapshot_index.json").read_text(encoding="utf-8"))
    assert snapshot_index["counts"]["symbols"] >= 2
    assert snapshot_index["counts"]["commands"] >= 1
    assert snapshot_index["counts"]["test_functions"] >= 1

    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "snapshot"
    assert manifest["repo"]["root"] == "<redacted>"
    assert manifest["outputs"]["snapshot_index_json"] == ".codecontext/latest/snapshot_index.json"

    pack = run_cbl("pack", "--repo", str(repo), "--issue", "exercise handoff", "--no-archive")
    assert pack.returncode == 0, pack.stdout + pack.stderr
    assert "CBL pack: OK" in pack.stdout
    assert "C:\\Users\\" not in pack.stdout

    expected_pack = {
        "ai_handoff.md",
        "pack_index.json",
        "snapshot_index.json",
        "symbols.json",
        "imports.json",
        "commands.json",
        "tests_inventory.json",
        "manifest.json",
    }
    assert expected_pack <= {item.name for item in latest.iterdir()}

    handoff = (latest / "ai_handoff.md").read_text(encoding="utf-8")
    assert "# CBL AI Handoff Pack" in handoff
    assert "exercise handoff" in handoff
    assert "C:\\Users\\" not in handoff

    pack_index = json.loads((latest / "pack_index.json").read_text(encoding="utf-8"))
    assert pack_index["issue"] == "exercise handoff"
    assert pack_index["outputs"]["ai_handoff_md"] == ".codecontext/latest/ai_handoff.md"

    pack_manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    assert pack_manifest["command"]["subcommand"] == "pack"
    assert pack_manifest["outputs"]["pack_index_json"] == ".codecontext/latest/pack_index.json"
