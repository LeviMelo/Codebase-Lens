from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    ".gitattributes": r'''
# CBL repository text normalization policy.
# Keep source and generated design/test files stable across Windows and Unix checkouts.

* text=auto

*.py text eol=lf
*.pyi text eol=lf
*.toml text eol=lf
*.md text eol=lf
*.json text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
*.txt text eol=lf
*.gitattributes text eol=lf
*.gitignore text eol=lf

*.ps1 text eol=crlf
*.bat text eol=crlf
*.cmd text eol=crlf
''',

    "src/codebase_lens/reports/cleanup.py": r'''
from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from codebase_lens.core.paths import resolve_user_path
from codebase_lens.reports.manifest import OutputLayout, write_json


@dataclass(frozen=True)
class CleanedRunRecord:
    path: str
    action: str
    reason: str


@dataclass(frozen=True)
class CleanResult:
    out_dir: str
    runs_dir: str
    keep: int
    remove_all: bool
    deleted: tuple[CleanedRunRecord, ...]
    kept: tuple[CleanedRunRecord, ...]
    errors: tuple[CleanedRunRecord, ...]
    counts: dict[str, int]


def _safe_output_dir(repo_root: Path, out_dir: str | Path) -> Path:
    raw = Path(out_dir)
    if raw.is_absolute():
        raise ValueError("Absolute --out paths are not allowed for clean.")
    return resolve_user_path(repo_root, raw, allow_absolute=False, allow_hard_excluded=True)


def _run_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.exists():
        return []
    return sorted(
        [item for item in runs_dir.iterdir() if item.is_dir()],
        key=lambda item: (item.stat().st_mtime_ns, item.name),
        reverse=True,
    )


def _relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _delete_run(repo_root: Path, runs_dir: Path, run_dir: Path) -> CleanedRunRecord:
    resolved_runs = runs_dir.resolve()
    resolved_run = run_dir.resolve()

    try:
        resolved_run.relative_to(resolved_runs)
    except ValueError:
        return CleanedRunRecord(
            path=_relative(repo_root, run_dir),
            action="error",
            reason="refused to delete path outside runs directory",
        )

    try:
        shutil.rmtree(resolved_run)
    except OSError as exc:
        return CleanedRunRecord(
            path=_relative(repo_root, run_dir),
            action="error",
            reason=f"delete failed: {exc}",
        )

    return CleanedRunRecord(
        path=_relative(repo_root, run_dir),
        action="deleted",
        reason="matched clean policy",
    )


def clean_archives(
    repo_root: str | Path,
    *,
    out_dir: str | Path = ".codecontext",
    keep: int = 10,
    remove_all: bool = False,
) -> CleanResult:
    root = Path(repo_root).resolve()
    if keep < 0:
        raise ValueError("--keep must be >= 0.")

    output_dir = _safe_output_dir(root, out_dir)
    runs_dir = output_dir / "runs"

    runs = _run_dirs(runs_dir)

    if remove_all:
        keep_set: set[Path] = set()
    else:
        keep_set = set(runs[:keep])

    deleted: list[CleanedRunRecord] = []
    kept: list[CleanedRunRecord] = []
    errors: list[CleanedRunRecord] = []

    for run_dir in runs:
        if run_dir in keep_set:
            kept.append(
                CleanedRunRecord(
                    path=_relative(root, run_dir),
                    action="kept",
                    reason=f"within newest {keep} run(s)",
                )
            )
            continue

        record = _delete_run(root, runs_dir, run_dir)
        if record.action == "error":
            errors.append(record)
        else:
            deleted.append(record)

    return CleanResult(
        out_dir=_relative(root, output_dir),
        runs_dir=_relative(root, runs_dir),
        keep=keep,
        remove_all=remove_all,
        deleted=tuple(deleted),
        kept=tuple(kept),
        errors=tuple(errors),
        counts={
            "runs_seen": len(runs),
            "deleted": len(deleted),
            "kept": len(kept),
            "errors": len(errors),
        },
    )


def clean_result_payload(result: CleanResult) -> dict[str, object]:
    return {
        "schema": {
            "name": "cbl.clean_report",
            "version": 1,
        },
        "out_dir": result.out_dir,
        "runs_dir": result.runs_dir,
        "keep": result.keep,
        "remove_all": result.remove_all,
        "deleted": [asdict(record) for record in result.deleted],
        "kept": [asdict(record) for record in result.kept],
        "errors": [asdict(record) for record in result.errors],
        "counts": dict(result.counts),
    }


def write_clean_report(layout: OutputLayout, result: CleanResult) -> Path:
    target = layout.latest_dir / "clean_report.json"
    write_json(target, clean_result_payload(result))
    return target
''',

    "tests/test_clean_integration.py": r'''
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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
    repo = tmp_path / "clean_repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'clean-repo'\n", encoding="utf-8")

    runs = repo / ".codecontext" / "runs"
    runs.mkdir(parents=True)

    for index in range(3):
        run_dir = runs / f"20260101T00000{index}Z"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        time.sleep(0.01)

    return repo


def test_clean_command_deletes_old_archives_and_writes_report(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cbl("clean", "--repo", str(repo), "--keep", "1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CBL clean: OK" in result.stdout
    assert "C:\\Users\\" not in result.stdout

    latest = repo / ".codecontext" / "latest"
    report_path = latest / "clean_report.json"
    manifest_path = latest / "manifest.json"

    assert report_path.is_file()
    assert manifest_path.is_file()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["counts"]["runs_seen"] == 3
    assert report["counts"]["kept"] == 1
    assert report["counts"]["deleted"] == 2
    assert report["counts"]["errors"] == 0

    remaining_runs = [item for item in (repo / ".codecontext" / "runs").iterdir() if item.is_dir()]
    assert len(remaining_runs) == 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"]["subcommand"] == "clean"
    assert manifest["outputs"]["clean_report_json"] == ".codecontext/latest/clean_report.json"
    assert manifest["repo"]["root"] == "<redacted>"
''',

    "scripts/dev/audits/audit_phase9_clean_hygiene.py": r'''
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"

REQUIRED_SYMBOLS = {
    "src/codebase_lens/reports/cleanup.py": [
        "CleanedRunRecord",
        "CleanResult",
        "clean_archives",
        "clean_result_payload",
        "write_clean_report",
    ],
    "src/codebase_lens/cli.py": [
        "_run_clean",
    ],
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def names_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
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


def make_repo(base: Path) -> Path:
    repo = base / "clean_repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'clean-repo'\n", encoding="utf-8")

    runs = repo / ".codecontext" / "runs"
    runs.mkdir(parents=True)

    for index in range(4):
        run_dir = runs / f"20260101T00000{index}Z"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        time.sleep(0.01)

    return repo


def main() -> int:
    if not (ROOT / ".gitattributes").is_file():
        fail(".gitattributes is missing.")

    gitattributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    if "*.py text eol=lf" not in gitattributes:
        fail(".gitattributes does not enforce LF for Python files.")

    for relative_path, symbols in REQUIRED_SYMBOLS.items():
        path = ROOT / relative_path
        if not path.is_file():
            fail(f"Missing required file: {relative_path}")
        available = names_in_file(path)
        missing = sorted(set(symbols) - available)
        if missing:
            fail(f"{relative_path} missing symbols: {missing}")

    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))

        clean = run_cbl("clean", "--repo", str(repo), "--keep", "2")
        if clean.returncode != 0:
            fail(f"cbl clean failed:\nSTDOUT:\n{clean.stdout}\nSTDERR:\n{clean.stderr}")
        if "CBL clean: OK" not in clean.stdout:
            fail("cbl clean did not report success.")
        if "C:\\Users\\" in clean.stdout:
            fail("cbl clean leaked an absolute Windows user path.")

        latest = repo / ".codecontext" / "latest"
        report_path = latest / "clean_report.json"
        manifest_path = latest / "manifest.json"

        if not report_path.is_file():
            fail("cbl clean did not write clean_report.json.")
        if not manifest_path.is_file():
            fail("cbl clean did not write manifest.json.")

        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["counts"]["runs_seen"] != 4:
            fail("clean report has wrong runs_seen count.")
        if report["counts"]["kept"] != 2:
            fail("clean report has wrong kept count.")
        if report["counts"]["deleted"] != 2:
            fail("clean report has wrong deleted count.")
        if report["counts"]["errors"] != 0:
            fail("clean report has deletion errors.")

        remaining_runs = [item for item in (repo / ".codecontext" / "runs").iterdir() if item.is_dir()]
        if len(remaining_runs) != 2:
            fail("clean command did not leave exactly two runs.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["command"]["subcommand"] != "clean":
            fail("manifest command.subcommand is not clean.")
        if manifest["outputs"].get("clean_report_json") != ".codecontext/latest/clean_report.json":
            fail("manifest does not declare clean_report_json.")
        if manifest["repo"].get("root") != "<redacted>":
            fail("manifest repo.root is not redacted.")

    contract = run_cbl("contract", "--no-archive")
    if contract.returncode != 0:
        fail(f"cbl contract failed after clean slice:\nSTDOUT:\n{contract.stdout}\nSTDERR:\n{contract.stderr}")

    print("PASS: Phase 9 clean/hygiene audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
}


def normalize(content: str) -> str:
    return dedent(content).strip("\n") + "\n"


def write_file(relative_path: str, content: str) -> None:
    target = ROOT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(normalize(content), encoding="utf-8", newline="\n")


def patch_cli() -> None:
    path = ROOT / "src/codebase_lens/cli.py"
    text = path.read_text(encoding="utf-8")

    replacements = [
        (
            "from codebase_lens.reports.manifest import build_manifest, copy_latest_to_run, prepare_output_layout, write_manifest_bundle\n",
            "from codebase_lens.reports.cleanup import clean_archives, write_clean_report\n"
            "from codebase_lens.reports.manifest import build_manifest, copy_latest_to_run, prepare_output_layout, write_manifest_bundle\n",
        ),
        (
            "    clean.set_defaults(handler=_run_partial)\n",
            "    clean.set_defaults(handler=_run_clean)\n",
        ),
    ]

    for old, new in replacements:
        if old not in text:
            if new in text:
                continue
            raise RuntimeError(f"Could not patch cli.py; missing expected marker:\n{old}")
        text = text.replace(old, new, 1)

    insert_before = "\ndef _run_partial(args: argparse.Namespace) -> int:\n"
    if insert_before not in text:
        raise RuntimeError("Could not patch cli.py: _run_partial insertion marker not found.")

    if "def _run_clean(args: argparse.Namespace)" not in text:
        inserted = r'''

def _run_clean(args: argparse.Namespace) -> int:
    try:
        root_info = _detect_root(args)
        repo_root = root_info.root

        result = clean_archives(
            repo_root,
            out_dir=args.out,
            keep=args.keep,
            remove_all=args.all,
        )

        layout = prepare_output_layout(repo_root, args.out, archive=False)
        clean_path = write_clean_report(layout, result)

        manifest = build_manifest(
            **_base_manifest_args(
                args,
                repo_root,
                "clean",
                {
                    "manifest_json": ".codecontext/latest/manifest.json",
                    "clean_report_json": ".codecontext/latest/clean_report.json",
                },
            )
        )
        manifest_path = write_manifest_bundle(layout, manifest)

    except RootDetectionError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_ROOT_DETECTION_FAILURE
    except PathSafetyError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_PATH_SAFETY_VIOLATION
    except ValueError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_INVALID_ARGUMENTS
    except OSError as exc:
        print(redact_console_text(f"ERROR: Could not clean archive runs: {exc}"))
        return EXIT_OUTPUT_WRITE_FAILURE
    except CblError as exc:
        print(redact_console_text(f"ERROR: {exc}"))
        return EXIT_GENERAL_ERROR

    if not args.quiet:
        print("CBL clean: OK")
        print(f"Runs seen: {result.counts['runs_seen']}")
        print(f"Deleted: {result.counts['deleted']}")
        print(f"Kept: {result.counts['kept']}")
        print(f"Errors: {result.counts['errors']}")
        print(f"Clean report: {display_path(repo_root, clean_path, absolute=args.absolute_paths)}")
        print(f"Output manifest: {display_path(repo_root, manifest_path, absolute=args.absolute_paths)}")
        for error in result.errors:
            print(f"WARNING: {error.path}: {redact_console_text(error.reason)}")

    return 0 if result.counts["errors"] == 0 else EXIT_GENERAL_ERROR

'''
        text = text.replace(insert_before, inserted + insert_before, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_contract() -> None:
    path = ROOT / "src/codebase_lens/contracts/architecture.py"
    text = path.read_text(encoding="utf-8")

    required_file_marker = '            "src/codebase_lens/reports/scanner_outputs.py",\n'
    required_file_addition = '            "src/codebase_lens/reports/cleanup.py",\n'

    if required_file_addition not in text:
        if required_file_marker not in text:
            raise RuntimeError("Could not patch architecture.py: scanner_outputs required-file marker not found.")
        text = text.replace(required_file_marker, required_file_marker + required_file_addition, 1)

    symbol_marker = '                    "_run_pack",\n'
    symbol_addition = '                    "_run_clean",\n'

    if symbol_addition not in text:
        if symbol_marker not in text:
            raise RuntimeError("Could not patch architecture.py: _run_pack symbol marker not found.")
        text = text.replace(symbol_marker, symbol_marker + symbol_addition, 1)

    extra_required = '''            {
                "path": "src/codebase_lens/reports/cleanup.py",
                "symbols": [
                    "CleanedRunRecord",
                    "CleanResult",
                    "clean_archives",
                    "clean_result_payload",
                    "write_clean_report",
                ],
            },
'''

    insertion_marker = '''            {
                "path": "src/codebase_lens/reports/snapshot.py",
'''
    if extra_required not in text:
        if insertion_marker not in text:
            raise RuntimeError("Could not patch architecture.py: snapshot required-symbol marker not found.")
        text = text.replace(insertion_marker, extra_required + insertion_marker, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_phase0_test() -> None:
    path = ROOT / "tests" / "test_phase0_cli.py"
    text = path.read_text(encoding="utf-8")

    old = '''def test_partial_commands_remain_explicit() -> None:
    result = run_cbl("clean")
    assert result.returncode == 1
    assert "CBL command: clean" in result.stdout
'''

    new = '''def test_clean_command_is_implemented() -> None:
    result = run_cbl("clean", "--keep", "999")
    assert result.returncode == 0
    assert "CBL clean: OK" in result.stdout
'''

    if old not in text:
        if new in text:
            return
        raise RuntimeError("Could not patch tests/test_phase0_cli.py: partial clean test block was not found.")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_cli()
    patch_contract()
    patch_phase0_test()

    print("Slice 010 applied: Phase 9 clean command and line-ending hygiene implemented.")
    print("Run the Phase 9 audit, contract, pytest, and git diff --check before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())