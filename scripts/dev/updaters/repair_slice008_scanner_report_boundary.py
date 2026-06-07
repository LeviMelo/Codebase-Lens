from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()

FILES: dict[str, str] = {
    "src/codebase_lens/scanners/inventory.py": r'''
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def file_universe_to_inventory(result) -> dict[str, Any]:
    """Convert a scanner FileUniverseResult into a serializable inventory payload.

    This module intentionally does not write files and does not import report-layer
    helpers. Scanner modules own file-universe semantics; report modules own output
    persistence.
    """

    return {
        "schema": {
            "name": "cbl.file_inventory",
            "version": 1,
        },
        "repo": {
            "root": "<redacted>",
            "root_redacted_for_ai": True,
        },
        "counts": dict(getattr(result, "counts", {})),
        "redaction": _jsonable(getattr(result, "redaction", None)),
        "files": [_jsonable(record) for record in getattr(result, "included_files", ())],
        "omissions": [_jsonable(record) for record in getattr(result, "omissions", ())],
        "warnings": list(getattr(result, "warnings", ())),
    }
''',

    "src/codebase_lens/scanners/tree.py": r'''
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def _insert_path(root: dict[str, Any], path: str) -> None:
    current = root
    parts = [part for part in PurePosixPath(path).parts if part not in {"", "."}]
    for index, part in enumerate(parts):
        is_leaf = index == len(parts) - 1
        if is_leaf:
            current.setdefault("__files__", set()).add(part)
        else:
            current = current.setdefault(part, {})


def _render_node(node: dict[str, Any], lines: list[str], *, prefix: str, depth: int, max_depth: int) -> None:
    if depth >= max_depth:
        hidden_dirs = [key for key in node.keys() if key != "__files__"]
        hidden_files = list(node.get("__files__", set()))
        hidden_count = len(hidden_dirs) + len(hidden_files)
        if hidden_count:
            lines.append(f"{prefix}... ({hidden_count} entries hidden by depth limit)")
        return

    dir_names = sorted(key for key in node.keys() if key != "__files__")
    file_names = sorted(node.get("__files__", set()))

    for dirname in dir_names:
        lines.append(f"{prefix}{dirname}/")
        child = node[dirname]
        if isinstance(child, dict):
            _render_node(child, lines, prefix=prefix + "  ", depth=depth + 1, max_depth=max_depth)

    for filename in file_names:
        lines.append(f"{prefix}{filename}")


def render_tree_report(
    result,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> str:
    """Render a scanner FileUniverseResult as text without report-layer imports."""

    included_files = list(getattr(result, "included_files", ()))
    omissions = list(getattr(result, "omissions", ()))
    counts = dict(getattr(result, "counts", {}))

    tree: dict[str, Any] = {}
    for record in included_files:
        path = getattr(record, "path", None)
        if isinstance(path, str) and path:
            _insert_path(tree, path)

    lines: list[str] = [
        "# CBL Repository Tree",
        "",
        "Evidence scope: scanner file universe",
        f"Included files: {counts.get('included_count', len(included_files))}",
        f"Tracked included: {counts.get('tracked_included_count', 0)}",
        f"Untracked included: {counts.get('untracked_included_count', 0)}",
        f"Ignored count: {counts.get('ignored_count', 0)}",
        f"Hard-excluded count: {counts.get('hard_excluded_count', 0)}",
        f"Binary skipped: {counts.get('binary_skipped_count', 0)}",
        f"Large skipped: {counts.get('large_skipped_count', 0)}",
        "",
        "Tree:",
    ]

    if not tree:
        lines.append("(no included files)")
    else:
        _render_node(tree, lines, prefix="", depth=0, max_depth=max_depth)

    if show_sizes:
        lines.extend(["", "File sizes:"])
        for record in sorted(included_files, key=lambda item: getattr(item, "path", "")):
            path = getattr(record, "path", "")
            size = getattr(record, "size_bytes", None)
            if path:
                lines.append(f"{path}\t{size if size is not None else 'unknown'} bytes")

    if show_skipped:
        lines.extend(["", "Skipped/omitted files:"])
        if not omissions:
            lines.append("(none)")
        else:
            for record in omissions:
                path = getattr(record, "path", "")
                reason = getattr(record, "reason", "unknown")
                evidence = getattr(record, "evidence", None)
                suffix = f" ({evidence})" if evidence else ""
                lines.append(f"{path}: {reason}{suffix}")

    return "\n".join(lines)
''',

    "src/codebase_lens/reports/scanner_outputs.py": r'''
from __future__ import annotations

from pathlib import Path

from codebase_lens.reports.manifest import OutputLayout, write_json
from codebase_lens.scanners.inventory import file_universe_to_inventory
from codebase_lens.scanners.tree import render_tree_report


def write_file_inventory(layout: OutputLayout, result) -> Path:
    target = layout.latest_dir / "file_inventory.json"
    write_json(target, file_universe_to_inventory(result))
    return target


def write_tree_report(
    layout: OutputLayout,
    result,
    *,
    max_depth: int = 4,
    show_sizes: bool = False,
    show_skipped: bool = False,
) -> Path:
    target = layout.latest_dir / "repo_tree.txt"
    target.write_text(
        render_tree_report(
            result,
            max_depth=max_depth,
            show_sizes=show_sizes,
            show_skipped=show_skipped,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target
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

    old_a = "from codebase_lens.scanners.inventory import write_file_inventory\n"
    old_b = "from codebase_lens.scanners.tree import write_tree_report\n"
    new = "from codebase_lens.reports.scanner_outputs import write_file_inventory, write_tree_report\n"

    if old_a not in text:
        raise RuntimeError("Could not patch cli.py: scanner inventory import not found.")
    if old_b not in text:
        raise RuntimeError("Could not patch cli.py: scanner tree import not found.")
    if new in text:
        text = text.replace(old_a, "")
        text = text.replace(old_b, "")
    else:
        text = text.replace(old_a, new, 1)
        text = text.replace(old_b, "", 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_builtin_contract() -> None:
    path = ROOT / "src/codebase_lens/contracts/architecture.py"
    text = path.read_text(encoding="utf-8")

    marker = '            "src/codebase_lens/reports/json.py",\n'
    addition = '            "src/codebase_lens/reports/scanner_outputs.py",\n'

    if addition not in text:
        if marker not in text:
            raise RuntimeError("Could not patch architecture.py: reports/json.py required-file marker not found.")
        text = text.replace(marker, marker + addition, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_phase7_audit() -> None:
    path = ROOT / "scripts/dev/audits/audit_phase7_contracts.py"
    text = path.read_text(encoding="utf-8")

    marker = '''    "src/codebase_lens/reports/json.py": [
        "contract_result_payload",
    ],
'''
    addition = '''    "src/codebase_lens/reports/scanner_outputs.py": [
        "write_file_inventory",
        "write_tree_report",
    ],
'''

    if addition not in text:
        if marker not in text:
            raise RuntimeError("Could not patch audit_phase7_contracts.py: reports/json.py marker not found.")
        text = text.replace(marker, marker + addition, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for relative_path, content in FILES.items():
        write_file(relative_path, content)

    patch_cli()
    patch_builtin_contract()
    patch_phase7_audit()

    print("Repair applied: scanner modules no longer import report-layer modules.")
    print("Re-run contract, Phase 7 audit, pytest, and git diff --check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())