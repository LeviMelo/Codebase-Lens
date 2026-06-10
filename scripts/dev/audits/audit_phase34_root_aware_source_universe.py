from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return env


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=_env(), text=True, capture_output=True, check=False)


def _git(repo: Path, *args: str) -> None:
    result = _run(["git", *args], cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbl_root_aware_universe_") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "cbl@example.invalid")
        _git(repo, "config", "user.name", "CBL Test")

        files = {
            "pyproject.toml": "[project]\nname='fixture'\nversion='0.0.0'",
            "src/pkg/output/bundle.py": "def bundle():\n    return 1",
            "src/pkg/data/transforms.py": "def transform():\n    return 2",
            "src/pkg/cache/store.py": "def store():\n    return 3",
            "src/pkg/r_scripts/fetch.R": "cat('fetch')",
            "scripts/check_r.R": "cat('check')",
            "config/intents/smoke.json": json.dumps({"intent": "smoke"}),
            "config/registries/seed.jsonl": '{"id":1}',
            "tests/fixtures/payload.json": json.dumps({"payload": [1]}),
            "output/generated.py": "def poison_should_not_be_scanned():\n    pass",
            "outputs/poison.py": "def output_poison_should_not_be_scanned():\n    pass",
            "data/raw/poison.py": "def data_poison_should_not_be_scanned():\n    pass",
            ".codecontext/latest/old.md": "generated",
            ".env": "TOKEN=secret",
        }
        for relative, content in files.items():
            _write(repo / relative, content)
        _git(repo, "add", ".")

        result = _run([sys.executable, "-m", "codebase_lens", "dump", "--repo", str(repo), "--no-archive"], cwd=ROOT)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode

        dump = (repo / ".codecontext/latest/codebase_dump.md").read_text(encoding="utf-8")
        index = json.loads((repo / ".codecontext/latest/codebase_dump_index.json").read_text(encoding="utf-8"))
        paths = {item["path"] for item in index.get("files", [])}

        required = {
            "src/pkg/output/bundle.py",
            "src/pkg/data/transforms.py",
            "src/pkg/cache/store.py",
            "src/pkg/r_scripts/fetch.R",
            "scripts/check_r.R",
            "config/intents/smoke.json",
            "config/registries/seed.jsonl",
        }
        forbidden = {
            "tests/fixtures/payload.json",
            "output/generated.py",
            "outputs/poison.py",
            "data/raw/poison.py",
            ".codecontext/latest/old.md",
            ".env",
        }

        missing = sorted(required - paths)
        leaked = sorted(forbidden & paths)
        poison_markers = [
            "poison_should_not_be_scanned",
            "output_poison_should_not_be_scanned",
            "data_poison_should_not_be_scanned",
        ]
        marker_leaks = [marker for marker in poison_markers if marker in dump]

        if missing or leaked or marker_leaks:
            print(json.dumps({"missing": missing, "leaked": leaked, "marker_leaks": marker_leaks, "paths": sorted(paths)}, indent=2))
            return 1

        result_json = _run([sys.executable, "-m", "codebase_lens", "dump", "--repo", str(repo), "--include-json", "--no-archive"], cwd=ROOT)
        if result_json.returncode != 0:
            print(result_json.stdout)
            print(result_json.stderr)
            return result_json.returncode
        index_json = json.loads((repo / ".codecontext/latest/codebase_dump_index.json").read_text(encoding="utf-8"))
        paths_json = {item["path"] for item in index_json.get("files", [])}
        if "tests/fixtures/payload.json" not in paths_json:
            print(json.dumps({"missing_include_json_fixture": True, "paths": sorted(paths_json)}, indent=2))
            return 1
        if "output/generated.py" in paths_json or "data/raw/poison.py" in paths_json:
            print(json.dumps({"unsafe_include_json_leak": sorted({"output/generated.py", "data/raw/poison.py"} & paths_json)}, indent=2))
            return 1

    print("PASS: Phase 34 root-aware source universe audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
