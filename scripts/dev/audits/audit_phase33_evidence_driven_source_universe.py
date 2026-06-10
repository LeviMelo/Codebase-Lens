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
    return subprocess.run(
        args,
        cwd=cwd,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> None:
    result = _run(["git", *args], cwd=repo)
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def _make_repo(base: Path) -> Path:
    repo = base / "evidence_driven_repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "cbl@example.invalid")
    _git(repo, "config", "user.name", "CBL Test")

    files = {
        "pyproject.toml": "[project]\nname='fixture'\nversion='0.0.0'",
        ".env.example": "TOKEN=example-only",
        ".env": "TOKEN=secret",
        "src/pkg/output/denominator.py": "def denominator():\n    return 1",
        "src/pkg/data/schema.py": "SCHEMA = {'ok': True}",
        "src/pkg/cache/store.py": "def store():\n    return 'ok'",
        "src/pkg/r_scripts/fetch.R": "cat('fetch')",
        "scripts/check_r_microdatasus.R": "cat('check')",
        "config/intents/alagoas_smoke.json": json.dumps({"execution_scale": "smoke"}),
        "config/registries/sidra_table_seed.jsonl": '{"table_id":"9606"}',
        "tests/fixtures/sidra_flat_fixture.json": json.dumps({"payload": [1]}),
        "tests/fixtures/small.csv": "a,b\n1,2",
        "data/small_tracked_fixture.csv": "a,b\n1,2",
        ".codecontext/latest/old.md": "generated",
        "model.parquet": "not really parquet but suffix must be excluded",
    }
    for relative, text in files.items():
        _write(repo / relative, text)
    _git(repo, "add", ".")
    return repo


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbl_source_universe_") as tmp:
        repo = _make_repo(Path(tmp))
        result = _run(
            [
                sys.executable,
                "-m",
                "codebase_lens",
                "dump",
                "--repo",
                str(repo),
                "--no-archive",
            ],
            cwd=ROOT,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode

        latest = repo / ".codecontext/latest"
        dump = (latest / "codebase_dump.md").read_text(encoding="utf-8")
        index = json.loads((latest / "codebase_dump_index.json").read_text(encoding="utf-8"))
        paths = {item["path"] for item in index.get("files", [])}

        required = {
            "src/pkg/output/denominator.py",
            "src/pkg/data/schema.py",
            "src/pkg/cache/store.py",
            "src/pkg/r_scripts/fetch.R",
            "scripts/check_r_microdatasus.R",
            "config/intents/alagoas_smoke.json",
            "config/registries/sidra_table_seed.jsonl",
            "tests/fixtures/sidra_flat_fixture.json",
            "tests/fixtures/small.csv",
            ".env.example",
        }
        missing = sorted(required - paths)
        forbidden = sorted(
            item
            for item in [".env", ".codecontext/latest/old.md", "model.parquet", "data/small_tracked_fixture.csv"]
            if item in paths
        )
        heading_missing = sorted(path for path in required if f"### FILE: `{path}`" not in dump)

        if missing or forbidden or heading_missing:
            print(
                json.dumps(
                    {
                        "missing": missing,
                        "forbidden": forbidden,
                        "heading_missing": heading_missing,
                        "all_paths": sorted(paths),
                    },
                    indent=2,
                )
            )
            return 1

    print("PASS: Phase 33 evidence-driven source universe audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
