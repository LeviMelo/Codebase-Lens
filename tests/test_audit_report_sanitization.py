from __future__ import annotations

import json
import tempfile
from pathlib import Path

from codebase_lens.core.audit_artifacts import (
    audit_payload_contains_local_paths,
    sanitize_audit_payload,
    sanitize_audit_string,
    write_audit_report_pair,
)


def test_sanitize_audit_string_redacts_common_local_paths() -> None:
    home = str(Path.home())
    temp_dir = tempfile.gettempdir()

    text = f"home={home}; temp={temp_dir}; win=C:\\Users\\Example\\AppData\\Local\\Temp\\abc\\repo"

    sanitized = sanitize_audit_string(text)

    assert home not in sanitized
    assert temp_dir not in sanitized
    assert "C:\\Users\\Example" not in sanitized
    assert "AppData\\Local\\Temp" not in sanitized
    assert "<USER_HOME>" in sanitized or "<TEMP_DIR>" in sanitized


def test_sanitize_audit_payload_recurses_through_nested_structures() -> None:
    home = str(Path.home())
    temp_dir = tempfile.gettempdir()

    payload = {
        "target_repo": f"{temp_dir}\\cbl_fixture\\repo",
        "nested": {
            "home": home,
            "items": [
                f"{home}\\project",
                Path(temp_dir) / "another" / "repo",
            ],
        },
    }

    sanitized = sanitize_audit_payload(payload)
    blob = json.dumps(sanitized, sort_keys=True)

    assert home not in blob
    assert temp_dir not in blob
    assert not audit_payload_contains_local_paths(sanitized)
    assert "<TEMP_DIR>" in blob or "<USER_HOME>" in blob


def test_write_audit_report_pair_sanitizes_persisted_reports(tmp_path: Path) -> None:
    home = str(Path.home())
    temp_dir = tempfile.gettempdir()
    payload = {
        "schema": {"name": "test.audit", "version": 1},
        "ok": True,
        "external_repo": {
            "target_repo": f"{temp_dir}\\cbl_fixture\\target",
            "runner_cwd": f"{home}\\runner",
        },
    }

    stable_path, latest_path = write_audit_report_pair(tmp_path, "path sanitization audit", payload)

    assert stable_path.is_file()
    assert latest_path.is_file()

    for path in (stable_path, latest_path):
        written = json.loads(path.read_text(encoding="utf-8"))
        blob = json.dumps(written, sort_keys=True)

        assert home not in blob
        assert temp_dir not in blob
        assert not audit_payload_contains_local_paths(written)
        assert "<TEMP_DIR>" in blob or "<USER_HOME>" in blob
