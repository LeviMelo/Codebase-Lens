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
