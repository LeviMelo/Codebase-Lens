from __future__ import annotations

import json
from pathlib import Path

from codebase_lens.contracts.release_safety import (
    release_safety_audit_payload,
    run_release_safety_audit,
)
from codebase_lens.core.audit_artifacts import write_audit_report_pair


def test_release_safety_audit_passes_hostile_fixture() -> None:
    result = run_release_safety_audit()
    payload = release_safety_audit_payload(result)

    assert result.ok, json.dumps(payload["issues"], indent=2, sort_keys=True)
    assert payload["schema"]["name"] == "cbl.release_safety_audit"
    assert payload["counts"]["errors"] == 0

    external = payload["external_repo"]
    assert "src/safety_pkg/" in external["source_prefixes"]
    assert external["pack_returncode"] == 0
    assert external["unsafe_path_check"]["returncode"] != 0


def test_stable_audit_artifact_writer_preserves_reports(tmp_path: Path) -> None:
    payload = {
        "schema": {"name": "test.audit", "version": 1},
        "ok": True,
    }

    stable_path, latest_path = write_audit_report_pair(tmp_path, "release safety audit", payload)

    assert stable_path == tmp_path / ".codecontext" / "audits" / "release_safety_audit.json"
    assert latest_path == tmp_path / ".codecontext" / "latest" / "release_safety_audit.json"
    assert stable_path.is_file()
    assert latest_path.is_file()

    stable_payload = json.loads(stable_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))

    assert stable_payload == payload
    assert latest_payload == payload


def test_release_safety_contract_module_does_not_import_cli_layer() -> None:
    import inspect
    import codebase_lens.contracts.release_safety as release_safety

    source = inspect.getsource(release_safety)

    assert "from codebase_lens import cli" not in source
    assert "import codebase_lens.cli" not in source
    assert "codebase_lens.cli" not in source
