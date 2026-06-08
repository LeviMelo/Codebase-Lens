from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

AUDIT_ARTIFACTS = r'''
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


WINDOWS_TEMP_RE = re.compile(
    r"(?i)[A-Z]:\\Users\\[^\\/\r\n\t\"']+\\AppData\\Local\\Temp(?:\\[^,\r\n\"']*)?"
)
WINDOWS_USER_RE = re.compile(
    r"(?i)[A-Z]:\\Users\\[^\\/\r\n\t\"']+"
)
POSIX_TEMP_RE = re.compile(
    r"(?:(?:/tmp|/var/tmp|/private/var/folders)/[^,\r\n\"']*)"
)


def _safe_audit_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        raise ValueError("Audit artifact name cannot be empty.")
    if not cleaned.endswith(".json"):
        cleaned += ".json"
    return cleaned


def stable_audit_dir(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / ".codecontext" / "audits"


def latest_dir(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / ".codecontext" / "latest"


def _path_text_variants(path: str | Path | None) -> tuple[str, ...]:
    if path is None:
        return ()

    raw = str(path)
    if not raw:
        return ()

    variants = {
        raw,
        raw.replace("\\", "/"),
        raw.replace("/", "\\"),
    }

    try:
        resolved = str(Path(raw).expanduser().resolve(strict=False))
        variants.add(resolved)
        variants.add(resolved.replace("\\", "/"))
        variants.add(resolved.replace("/", "\\"))
    except OSError:
        pass

    return tuple(sorted((item for item in variants if item), key=len, reverse=True))


def _specific_sensitive_path_replacements() -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []

    for value, placeholder in (
        (tempfile.gettempdir(), "<TEMP_DIR>"),
        (os.environ.get("TMP"), "<TEMP_DIR>"),
        (os.environ.get("TEMP"), "<TEMP_DIR>"),
        (os.environ.get("USERPROFILE"), "<USER_HOME>"),
        (os.environ.get("HOME"), "<USER_HOME>"),
        (Path.home(), "<USER_HOME>"),
    ):
        for variant in _path_text_variants(value):
            candidates.append((variant, placeholder))

    deduped: dict[str, str] = {}
    for needle, placeholder in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
        deduped.setdefault(needle, placeholder)

    return tuple(deduped.items())


def sanitize_audit_string(value: str) -> str:
    sanitized = value

    for needle, placeholder in _specific_sensitive_path_replacements():
        if needle:
            sanitized = sanitized.replace(needle, placeholder)

    sanitized = WINDOWS_TEMP_RE.sub("<TEMP_DIR>", sanitized)
    sanitized = POSIX_TEMP_RE.sub("<TEMP_DIR>", sanitized)
    sanitized = WINDOWS_USER_RE.sub("<USER_HOME>", sanitized)

    return sanitized


def sanitize_audit_payload(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_audit_string(value)

    if isinstance(value, Path):
        return sanitize_audit_string(str(value))

    if isinstance(value, dict):
        return {
            str(key): sanitize_audit_payload(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [sanitize_audit_payload(item) for item in value]

    if isinstance(value, tuple):
        return [sanitize_audit_payload(item) for item in value]

    if isinstance(value, set):
        return sorted(sanitize_audit_payload(item) for item in value)

    return value


def audit_payload_contains_local_paths(value: Any) -> bool:
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False)

    forbidden_fragments = [
        "AppData\\\\Local\\\\Temp",
        "AppData/Local/Temp",
        "C:\\\\Users\\\\",
        "C:/Users/",
        "/tmp/",
        "/var/tmp/",
        "/private/var/folders/",
    ]

    home = str(Path.home())
    temp_dir = tempfile.gettempdir()

    for variant in [*_path_text_variants(home), *_path_text_variants(temp_dir)]:
        if variant and variant in blob:
            return True

    return any(fragment in blob for fragment in forbidden_fragments)


def write_stable_audit_report(repo_root: str | Path, name: str, payload: dict[str, Any]) -> Path:
    destination = stable_audit_dir(repo_root) / _safe_audit_name(name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_audit_payload(payload)
    destination.write_text(
        json.dumps(sanitized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def write_latest_audit_report(repo_root: str | Path, name: str, payload: dict[str, Any]) -> Path:
    destination = latest_dir(repo_root) / _safe_audit_name(name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_audit_payload(payload)
    destination.write_text(
        json.dumps(sanitized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def write_audit_report_pair(repo_root: str | Path, name: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    stable = write_stable_audit_report(repo_root, name, payload)
    latest = write_latest_audit_report(repo_root, name, payload)
    return stable, latest
'''

AUDIT = r'''
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def run_python(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_parseable(relative: str) -> None:
    path = ROOT / relative
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{relative} is not parseable: {exc}")


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    sys.path.insert(0, str(SRC))

    for relative in [
        "src/codebase_lens/core/audit_artifacts.py",
        "src/codebase_lens/contracts/release_safety.py",
        "src/codebase_lens/contracts/fixture_matrix.py",
        "src/codebase_lens/contracts/command_surface.py",
    ]:
        assert_parseable(relative)

    from codebase_lens.core.audit_artifacts import audit_payload_contains_local_paths

    commands = [
        [sys.executable, "scripts/dev/audits/audit_phase20_public_command_stability.py"],
        [sys.executable, "scripts/dev/audits/audit_phase21_release_fixture_matrix.py"],
        [sys.executable, "scripts/dev/audits/audit_phase22_release_safety.py"],
    ]

    for command in commands:
        result = run_python(command)
        if result.returncode != 0:
            fail(
                "Required release audit failed before sanitization check.\n"
                f"Command: {' '.join(command)}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

    audit_dir = ROOT / ".codecontext" / "audits"
    expected = [
        audit_dir / "command_surface_audit.json",
        audit_dir / "fixture_matrix_audit.json",
        audit_dir / "release_safety_audit.json",
    ]

    for path in expected:
        if not path.is_file():
            fail(f"Expected stable audit report missing: {path}")

        payload = load_json(path)
        if audit_payload_contains_local_paths(payload):
            fail(f"Stable audit report still contains local absolute path fragments: {path}")

        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if "C:\\\\Users\\\\" in blob or "C:/Users/" in blob:
            fail(f"Stable audit report leaked Windows user path: {path}")
        if "AppData\\\\Local\\\\Temp" in blob or "AppData/Local/Temp" in blob:
            fail(f"Stable audit report leaked Windows temp path: {path}")
        if "/tmp/" in blob or "/var/tmp/" in blob or "/private/var/folders/" in blob:
            fail(f"Stable audit report leaked POSIX temp path: {path}")

    print("PASS: Phase 23 audit report path sanitization passed.")
    print(f"Stable audit directory: {audit_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST = r'''
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

    required_file = "scripts/dev/audits/audit_phase23_audit_report_sanitization.py"
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

    write_file("src/codebase_lens/core/audit_artifacts.py", AUDIT_ARTIFACTS, modified)
    write_file("scripts/dev/audits/audit_phase23_audit_report_sanitization.py", AUDIT, modified)
    write_file("tests/test_audit_report_sanitization.py", TEST, modified)
    patch_contract(modified)

    assert_parseable(modified)

    print("Slice 018B applied: stable audit report path sanitization added.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())