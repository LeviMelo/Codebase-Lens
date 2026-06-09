from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one occurrence for {label}, found {count}.")
    return text.replace(old, new, 1)


def patch_dump_report(root: Path) -> None:
    path = root / "src" / "codebase_lens" / "reports" / "dump.py"
    text = _read(path)

    if "def _normalize_scope_paths(" not in text:
        marker = '''def _filter_records(records: tuple[Any, ...], *, tracked_only: bool, include_untracked: bool, include_tests: bool, include_docs: bool, include_config: bool, include_json: bool) -> tuple[list[Any], list[dict[str, Any]]]:\n'''
        helper = '''def _normalize_scope_paths(repo_root: Path, raw_scope_paths: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:\n    """Normalize repo-relative dump scope paths.\n\n    Scope paths are explicit filters over the already-safe file universe. They do\n    not redefine the repository root and they do not bypass hard exclusions.\n    """\n\n    if not raw_scope_paths:\n        return ()\n\n    values: list[str] = []\n    for raw in raw_scope_paths:\n        text = str(raw).strip()\n        if not text:\n            continue\n        target = resolve_user_path(repo_root, text, allow_absolute=False, allow_hard_excluded=False)\n        if not target.exists():\n            raise ValueError(f"Dump scope does not exist: {text}")\n        relative = to_posix_relative(repo_root, target).strip("/").replace("\\\\", "/")\n        if relative in {"", "."}:\n            continue\n        if relative not in values:\n            values.append(relative)\n\n    return tuple(values)\n\n\ndef _record_in_scope(path: str, scope_paths: tuple[str, ...]) -> bool:\n    if not scope_paths:\n        return True\n    normalized = path.replace("\\\\", "/").strip("/")\n    for scope in scope_paths:\n        if normalized == scope or normalized.startswith(scope.rstrip("/") + "/"):\n            return True\n    return False\n\n\n'''
        text = _replace_once(text, marker, helper + marker, label="dump scope helper insertion")

    old_sig = '''def write_codebase_dump(layout: OutputLayout, repo_root: str | Path, *, max_file_bytes: int, tracked_only: bool = True, include_untracked: bool = False, include_tests: bool = True, include_docs: bool = True, include_config: bool = True, include_json: bool = False, out_file: str | None = None, output_format: str = "markdown", line_numbers: bool = True, max_total_bytes: int = 0) -> DumpBundleResult:\n'''
    new_sig = '''def write_codebase_dump(layout: OutputLayout, repo_root: str | Path, *, max_file_bytes: int, tracked_only: bool = True, include_untracked: bool = False, include_tests: bool = True, include_docs: bool = True, include_config: bool = True, include_json: bool = False, out_file: str | None = None, output_format: str = "markdown", line_numbers: bool = True, max_total_bytes: int = 0, scope_paths: tuple[str, ...] | list[str] | None = None) -> DumpBundleResult:\n'''
    if old_sig in text:
        text = text.replace(old_sig, new_sig, 1)

    old_block = '''    universe = discover_file_universe(root, max_file_bytes=max_file_bytes)\n    selected, dump_omissions = _filter_records(universe.included_files, tracked_only=tracked_only, include_untracked=include_untracked, include_tests=include_tests, include_docs=include_docs, include_config=include_config, include_json=include_json)\n    selected_paths = [record.path for record in selected]\n'''
    new_block = '''    universe = discover_file_universe(root, max_file_bytes=max_file_bytes)\n    normalized_scope_paths = _normalize_scope_paths(root, scope_paths)\n    scoped_records = tuple(\n        record\n        for record in universe.included_files\n        if _record_in_scope(str(getattr(record, "path", "")), normalized_scope_paths)\n    )\n    if normalized_scope_paths and not scoped_records:\n        raise ValueError(f"Dump scope selected no scan-eligible files: {', '.join(normalized_scope_paths)}")\n\n    selected, dump_omissions = _filter_records(scoped_records, tracked_only=tracked_only, include_untracked=include_untracked, include_tests=include_tests, include_docs=include_docs, include_config=include_config, include_json=include_json)\n    selected_paths = [record.path for record in selected]\n    if normalized_scope_paths and not selected_paths:\n        raise ValueError(f"Dump scope selected no source-like files after filters: {', '.join(normalized_scope_paths)}")\n'''
    if old_block in text:
        text = text.replace(old_block, new_block, 1)
    elif "normalized_scope_paths = _normalize_scope_paths" not in text:
        raise RuntimeError("Could not patch dump scope filtering block.")

    old_header = '''    lines: list[str] = ["# CBL Codebase Dump", "", f"Repository: `{root.name}`", f"Format: `{output_format}`", f"Tracked only: `{str(tracked_only).lower()}`", f"Include untracked: `{str(include_untracked).lower()}`", f"Line numbers: `{str(line_numbers).lower()}`", "Source truncation: `disabled for included files`", "Safety: hard exclusions and redaction enabled", "", "## Counts", "", f"- Included source files: {len(selected_paths)}", f"- Python files analyzed: {len(python_files)}", f"- Symbols indexed: {len(symbols)}", f"- Source bytes emitted: {source_bytes}", f"- Dump-filter omissions: {len(dump_omissions)}", f"- Scanner omissions: {len(universe.omitted_files)}", "", "## File Tree", "", "~~~~text", _tree(selected_paths) or "<empty>", "~~~~", "", "## Module Docstring Index", "", *_render_docstring_index(module_payload), "## Symbol Index", "", *_render_symbol_index(symbols), "## Omitted Files", ""]\n'''
    new_header = '''    scope_label = ", ".join(normalized_scope_paths) if normalized_scope_paths else "<repository>"\n    lines: list[str] = ["# CBL Codebase Dump", "", f"Repository: `{root.name}`", f"Scope: `{scope_label}`", f"Format: `{output_format}`", f"Tracked only: `{str(tracked_only).lower()}`", f"Include untracked: `{str(include_untracked).lower()}`", f"Line numbers: `{str(line_numbers).lower()}`", "Source truncation: `disabled for included files`", "Safety: hard exclusions and redaction enabled", "", "## Counts", "", f"- Included source files: {len(selected_paths)}", f"- Python files analyzed: {len(python_files)}", f"- Symbols indexed: {len(symbols)}", f"- Source bytes emitted: {source_bytes}", f"- Dump-filter omissions: {len(dump_omissions)}", f"- Scanner omissions: {len(universe.omitted_files)}", "", "## File Tree", "", "~~~~text", _tree(selected_paths) or "<empty>", "~~~~", "", "## Module Docstring Index", "", *_render_docstring_index(module_payload), "## Symbol Index", "", *_render_symbol_index(symbols), "## Omitted Files", ""]\n'''
    if old_header in text:
        text = text.replace(old_header, new_header, 1)
    elif "scope_label = " not in text:
        raise RuntimeError("Could not patch dump markdown header.")

    old_index = '''    index_payload = {"schema": {"name": "cbl.codebase_dump", "version": 1}, "mode": "tracked_source_dump", "line_numbers": line_numbers, "source_truncation": "disabled_for_included_files", "files": files_payload, "module_docstrings": module_payload, "symbols": symbol_payload, "omitted_files": all_omissions, "counts": {"included_files": len(selected_paths), "python_files_analyzed": len(python_files), "symbols": len(symbols), "source_bytes": source_bytes, "dump_filter_omissions": len(dump_omissions), "scanner_omissions": len(universe.omitted_files)}, "warnings": warnings}\n'''
    new_index = '''    index_payload = {"schema": {"name": "cbl.codebase_dump", "version": 2}, "mode": "tracked_source_dump", "scope_paths": list(normalized_scope_paths), "line_numbers": line_numbers, "source_truncation": "disabled_for_included_files", "files": files_payload, "module_docstrings": module_payload, "symbols": symbol_payload, "omitted_files": all_omissions, "counts": {"included_files": len(selected_paths), "python_files_analyzed": len(python_files), "symbols": len(symbols), "source_bytes": source_bytes, "dump_filter_omissions": len(dump_omissions), "scanner_omissions": len(universe.omitted_files)}, "warnings": warnings}\n'''
    if old_index in text:
        text = text.replace(old_index, new_index, 1)
    elif '"scope_paths": list(normalized_scope_paths)' not in text:
        raise RuntimeError("Could not patch dump index payload.")

    _write(path, text)


def patch_cli(root: Path) -> None:
    path = root / "src" / "codebase_lens" / "cli.py"
    text = _read(path)

    if 'dump.add_argument("--path"' not in text:
        anchor = '    dump.add_argument("--include-untracked", action="store_true", help="Also include safe untracked, non-ignored source files.")\n'
        insert = anchor + '    dump.add_argument("--path", action="append", default=[], help="Restrict dump to a repository-relative file or directory. Repeatable. Example: --path src")\n    dump.add_argument("--cwd-scope", action="store_true", help="Restrict dump to the current working directory inside the detected repository root.")\n'
        text = _replace_once(text, anchor, insert, label="dump path arguments")

    old_call = '''        result = write_codebase_dump(layout, repo_root, max_file_bytes=args.max_file_bytes, tracked_only=args.tracked_only, include_untracked=args.include_untracked, include_tests=not args.exclude_tests, include_docs=not args.exclude_docs, include_config=not args.exclude_config, include_json=args.include_json, out_file=args.out_file, output_format=args.output_format, line_numbers=not args.no_line_numbers, max_total_bytes=args.max_total_bytes)\n'''
    new_call = '''        scope_paths = tuple(args.path or ())\n        if args.cwd_scope:\n            cwd_scope = to_posix_relative(repo_root, Path.cwd()).strip("/")\n            if cwd_scope and cwd_scope != ".":\n                scope_paths = (*scope_paths, cwd_scope)\n\n        result = write_codebase_dump(layout, repo_root, max_file_bytes=args.max_file_bytes, tracked_only=args.tracked_only, include_untracked=args.include_untracked, include_tests=not args.exclude_tests, include_docs=not args.exclude_docs, include_config=not args.exclude_config, include_json=args.include_json, out_file=args.out_file, output_format=args.output_format, line_numbers=not args.no_line_numbers, max_total_bytes=args.max_total_bytes, scope_paths=scope_paths)\n'''
    if old_call in text:
        text = text.replace(old_call, new_call, 1)
    elif "scope_paths = tuple(args.path or ())" not in text:
        raise RuntimeError("Could not patch _run_dump write_codebase_dump call.")

    old_print = '''        print(f"Included source files: {result.counts.get('included_files', 0)}")\n'''
    new_print = '''        print(f"Scope: {', '.join(scope_paths) if scope_paths else '<repository>'}")\n        print(f"Included source files: {result.counts.get('included_files', 0)}")\n'''
    if old_print in text and "print(f\"Scope: {', '.join(scope_paths)" not in text:
        text = text.replace(old_print, new_print, 1)

    _write(path, text)


def patch_docs(root: Path) -> None:
    for rel in ("README.md", "docs/LOCAL_WORKFLOW.md"):
        path = root / rel
        if not path.exists():
            continue
        text = _read(path)
        marker = "CBL dump scoping"
        if marker not in text:
            addition = (
                "\n## CBL dump scoping\n\n"
                "`cbl dump --no-archive` intentionally dumps from the detected repository root. "
                "Changing the shell directory into `src` does not narrow the dump. "
                "Use `cbl dump --path src --no-archive` to dump only `src/`. "
                "Use `cbl dump --cwd-scope --no-archive` when the current working directory should define the dump scope. "
                "Scope paths are filters over the safe file universe; they do not bypass hard exclusions, redaction, or `.codecontext/` exclusion.\n"
            )
            text = text.rstrip() + addition + "\n"
            _write(path, text)


def write_tests(root: Path) -> None:
    path = root / "tests" / "test_dump_scope.py"
    text = '''from __future__ import annotations\n\nimport json\nimport os\nimport subprocess\nimport sys\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef env() -> dict[str, str]:\n    values = os.environ.copy()\n    src = str(ROOT / "src")\n    current = values.get("PYTHONPATH", "")\n    values["PYTHONPATH"] = src if not current else src + os.pathsep + current\n    return values\n\n\ndef run_cbl(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:\n    return subprocess.run(\n        [sys.executable, "-m", "codebase_lens", *args],\n        cwd=cwd,\n        env=env(),\n        text=True,\n        capture_output=True,\n        check=False,\n        timeout=90,\n    )\n\n\ndef _read_latest_dump() -> tuple[str, dict[str, object]]:\n    latest = ROOT / ".codecontext" / "latest"\n    text = (latest / "codebase_dump.md").read_text(encoding="utf-8")\n    index = json.loads((latest / "codebase_dump_index.json").read_text(encoding="utf-8"))\n    return text, index\n\n\ndef test_dump_path_scope_limits_dump_to_src_tree() -> None:\n    result = run_cbl("dump", "--path", "src", "--no-archive")\n    assert result.returncode == 0, result.stdout + result.stderr\n\n    text, index = _read_latest_dump()\n\n    assert "Scope: `src`" in text\n    assert "### FILE: `src/codebase_lens/cli.py`" in text\n    assert "### FILE: `README.md`" not in text\n    assert "### FILE: `docs/" not in text\n    assert "### FILE: `scripts/" not in text\n    assert index["scope_paths"] == ["src"]\n    assert index["files"]\n    assert all(str(item["path"]).startswith("src/") for item in index["files"])\n\n\ndef test_dump_cwd_scope_uses_current_directory_as_scope() -> None:\n    result = run_cbl("dump", "--cwd-scope", "--no-archive", cwd=ROOT / "src")\n    assert result.returncode == 0, result.stdout + result.stderr\n\n    text, index = _read_latest_dump()\n\n    assert "Scope: `src`" in text\n    assert "### FILE: `src/codebase_lens/cli.py`" in text\n    assert "### FILE: `README.md`" not in text\n    assert index["scope_paths"] == ["src"]\n    assert all(str(item["path"]).startswith("src/") for item in index["files"])\n'''
    _write(path, text)


def write_audit(root: Path) -> None:
    path = root / "scripts" / "dev" / "audits" / "audit_phase31_dump_scoping.py"
    text = '''from __future__ import annotations\n\nimport json\nimport os\nimport subprocess\nimport sys\nfrom dataclasses import asdict, dataclass\nfrom pathlib import Path\nfrom typing import Any\n\n\n@dataclass(frozen=True)\nclass DumpScopeIssue:\n    severity: str\n    code: str\n    message: str\n    details: dict[str, Any]\n\n\n@dataclass(frozen=True)\nclass DumpScopeAuditResult:\n    ok: bool\n    issues: tuple[DumpScopeIssue, ...]\n    counts: dict[str, int]\n\n\ndef _repo_root() -> Path:\n    return Path(__file__).resolve().parents[3]\n\n\ndef _env(root: Path) -> dict[str, str]:\n    values = os.environ.copy()\n    src = str(root / "src")\n    current = values.get("PYTHONPATH", "")\n    values["PYTHONPATH"] = src if not current else src + os.pathsep + current\n    return values\n\n\ndef _run(root: Path, args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:\n    return subprocess.run(\n        [sys.executable, "-m", "codebase_lens", *args],\n        cwd=cwd or root,\n        env=_env(root),\n        text=True,\n        capture_output=True,\n        check=False,\n        timeout=90,\n    )\n\n\ndef _latest_index(root: Path) -> dict[str, Any]:\n    return json.loads((root / ".codecontext" / "latest" / "codebase_dump_index.json").read_text(encoding="utf-8"))\n\n\ndef _latest_markdown(root: Path) -> str:\n    return (root / ".codecontext" / "latest" / "codebase_dump.md").read_text(encoding="utf-8")\n\n\ndef _check_scoped_dump(root: Path, *, args: list[str], cwd: Path | None = None) -> list[DumpScopeIssue]:\n    issues: list[DumpScopeIssue] = []\n    result = _run(root, args, cwd=cwd)\n    if result.returncode != 0:\n        return [DumpScopeIssue("error", "dump_command_failed", "Scoped dump command failed.", {"args": args, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]})]\n\n    text = _latest_markdown(root)\n    index = _latest_index(root)\n    files = index.get("files", [])\n\n    if "Scope: `src`" not in text:\n        issues.append(DumpScopeIssue("error", "scope_marker_missing", "Scoped dump markdown does not declare Scope: `src`.", {"args": args}))\n    if "### FILE: `src/codebase_lens/cli.py`" not in text:\n        issues.append(DumpScopeIssue("error", "src_file_missing", "Scoped dump did not include an expected src file.", {"args": args}))\n    for forbidden in ("### FILE: `README.md`", "### FILE: `docs/", "### FILE: `scripts/"):\n        if forbidden in text:\n            issues.append(DumpScopeIssue("error", "out_of_scope_file_rendered", "Scoped dump rendered a file outside src/.", {"args": args, "marker": forbidden}))\n    if index.get("scope_paths") != ["src"]:\n        issues.append(DumpScopeIssue("error", "index_scope_paths_wrong", "Dump index does not record scope_paths=['src'].", {"args": args, "scope_paths": index.get("scope_paths")}))\n    if not files:\n        issues.append(DumpScopeIssue("error", "empty_scoped_files", "Scoped dump selected no files.", {"args": args}))\n    for item in files:\n        path = str(item.get("path", "")) if isinstance(item, dict) else ""\n        if not path.startswith("src/"):\n            issues.append(DumpScopeIssue("error", "index_out_of_scope_file", "Dump index contains a file outside src/.", {"args": args, "path": path}))\n            break\n    return issues\n\n\ndef run_dump_scoping_audit() -> DumpScopeAuditResult:\n    root = _repo_root()\n    issues: list[DumpScopeIssue] = []\n    issues.extend(_check_scoped_dump(root, args=["dump", "--path", "src", "--no-archive"]))\n    issues.extend(_check_scoped_dump(root, args=["dump", "--cwd-scope", "--no-archive"], cwd=root / "src"))\n\n    return DumpScopeAuditResult(\n        ok=not any(issue.severity == "error" for issue in issues),\n        issues=tuple(issues),\n        counts={"issues": len(issues), "errors": sum(1 for issue in issues if issue.severity == "error")},\n    )\n\n\ndef main() -> int:\n    root = _repo_root()\n    result = run_dump_scoping_audit()\n    report = {"schema": {"name": "cbl.dump_scoping_audit", "version": 1}, "ok": result.ok, "issues": [asdict(issue) for issue in result.issues], "counts": result.counts}\n    stable = root / ".codecontext" / "audits" / "dump_scoping_audit.json"\n    stable.parent.mkdir(parents=True, exist_ok=True)\n    stable.write_text(json.dumps(report, indent=2, sort_keys=True) + "\\n", encoding="utf-8")\n    if result.ok:\n        print("PASS: Phase 31 dump scoping audit passed.")\n        print(f"Stable audit report: {stable}")\n        return 0\n    for issue in result.issues:\n        print(f"FAIL: {issue.code}: {issue.message}")\n    print(f"FAIL: Phase 31 dump scoping audit failed. Report: {stable}")\n    return 1\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'''
    _write(path, text)


def patch_architecture(root: Path) -> None:
    path = root / "src" / "codebase_lens" / "contracts" / "architecture.py"
    text = _read(path)
    if '"tests/test_dump_scope.py"' not in text:
        anchor = '            "tests/test_installation_docs.py",\n'
        text = _replace_once(text, anchor, anchor + '            "tests/test_dump_scope.py",\n', label="required dump scope test file")
    if '"scripts/dev/audits/audit_phase31_dump_scoping.py"' not in text:
        anchor = '            "scripts/dev/audits/audit_phase30_installation_docs.py",\n'
        text = _replace_once(text, anchor, anchor + '            "scripts/dev/audits/audit_phase31_dump_scoping.py",\n', label="required dump scope audit file")
    if '"run_dump_scoping_audit"' not in text:
        anchor = '''            {\n                "path": "scripts/dev/audits/audit_phase30_installation_docs.py",\n                "symbols": [\n                    "InstallationDocsIssue",\n                    "InstallationDocsAuditResult",\n                    "run_installation_docs_audit",\n                    "main",\n                ],\n            },\n'''
        addition = anchor + '''            {\n                "path": "scripts/dev/audits/audit_phase31_dump_scoping.py",\n                "symbols": [\n                    "DumpScopeIssue",\n                    "DumpScopeAuditResult",\n                    "run_dump_scoping_audit",\n                    "main",\n                ],\n            },\n'''
        text = _replace_once(text, anchor, addition, label="required dump scope audit symbols")
    _write(path, text)


def parse_modified_python(root: Path) -> None:
    for rel in [
        "src/codebase_lens/reports/dump.py",
        "src/codebase_lens/cli.py",
        "src/codebase_lens/contracts/architecture.py",
        "tests/test_dump_scope.py",
        "scripts/dev/audits/audit_phase31_dump_scoping.py",
    ]:
        path = root / rel
        ast.parse(path.read_text(encoding="utf-8"), filename=rel)


def main() -> int:
    root = _repo_root()
    patch_dump_report(root)
    patch_cli(root)
    patch_docs(root)
    write_tests(root)
    write_audit(root)
    patch_architecture(root)
    parse_modified_python(root)
    print("Slice 026 applied: dump scoping added.")
    print("Use `cbl dump --path src --no-archive` for an explicit src-only dump.")
    print("Use `cbl dump --cwd-scope --no-archive` from inside src/ to scope to the current directory.")
    print("The updater parsed every modified Python file before exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
