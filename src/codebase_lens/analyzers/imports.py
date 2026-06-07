from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.models import ImportRecord
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class PythonImportAnalysisResult:
    path: str
    imports: tuple[ImportRecord, ...]
    syntax_errors: tuple[str, ...]


def _raw_line(source_lines: list[str], lineno: int) -> str:
    if lineno < 1 or lineno > len(source_lines):
        return ""
    return source_lines[lineno - 1].strip()


def _candidate_module_paths(root: Path, parts: list[str]) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for base in (root / "src", root):
        candidates.append(base.joinpath(*parts).with_suffix(".py"))
        candidates.append(base.joinpath(*parts) / "__init__.py")
    return tuple(candidates)


def _module_parts_for_relative_import(repo_root: Path, file_path: Path, level: int, module: str | None) -> list[str]:
    try:
        relative = file_path.relative_to(repo_root / "src")
    except ValueError:
        relative = file_path.relative_to(repo_root)

    package_parts = list(relative.parent.parts)

    if file_path.name == "__init__.py":
        package_parts = list(relative.parent.parts)

    climb = max(level - 1, 0)
    if climb:
        package_parts = package_parts[:-climb] if climb <= len(package_parts) else []

    if module:
        package_parts.extend(part for part in module.split(".") if part)

    return package_parts


def resolve_project_import(
    repo_root: str | Path,
    file_path: str | Path,
    *,
    module: str | None,
    name: str | None,
    level: int = 0,
) -> str | None:
    root = Path(repo_root).resolve()
    target_file = Path(file_path).resolve()

    if level > 0:
        parts = _module_parts_for_relative_import(root, target_file, level, module)
    elif module:
        parts = [part for part in module.split(".") if part]
    else:
        return None

    candidate_parts = list(parts)
    if name and name != "*":
        candidate_parts_with_name = [*candidate_parts, name]
    else:
        candidate_parts_with_name = candidate_parts

    for candidate in _candidate_module_paths(root, candidate_parts_with_name):
        if candidate.is_file():
            return to_posix_relative(root, candidate)

    for candidate in _candidate_module_paths(root, candidate_parts):
        if candidate.is_file():
            return to_posix_relative(root, candidate)

    return None


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, *, repo_root: Path, file_path: Path, source: str) -> None:
        self.repo_root = repo_root
        self.file_path = file_path
        self.relative_path = to_posix_relative(repo_root, file_path)
        self.source_lines = source.splitlines()
        self.imports: list[ImportRecord] = []

    def visit_Import(self, node: ast.Import) -> None:
        raw = _raw_line(self.source_lines, int(getattr(node, "lineno", 1)))
        for alias in node.names:
            module = alias.name
            record = ImportRecord(
                path=self.relative_path,
                line=int(getattr(node, "lineno", 1)),
                module=module,
                name=None,
                alias=alias.asname,
                level=0,
                raw=raw,
                resolved_project_path=resolve_project_import(
                    self.repo_root,
                    self.file_path,
                    module=module,
                    name=None,
                    level=0,
                ),
                confidence="medium",
            )
            self.imports.append(record)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raw = _raw_line(self.source_lines, int(getattr(node, "lineno", 1)))
        module = node.module
        level = int(getattr(node, "level", 0))

        for alias in node.names:
            record = ImportRecord(
                path=self.relative_path,
                line=int(getattr(node, "lineno", 1)),
                module=module,
                name=alias.name,
                alias=alias.asname,
                level=level,
                raw=raw,
                resolved_project_path=resolve_project_import(
                    self.repo_root,
                    self.file_path,
                    module=module,
                    name=alias.name,
                    level=level,
                ),
                confidence="medium" if record_like_import_is_dynamic(module, alias.name) else "high",
            )
            self.imports.append(record)


def record_like_import_is_dynamic(module: str | None, name: str | None) -> bool:
    if name == "*":
        return True
    if module is None and name is None:
        return True
    return False


def collect_imports_for_file(repo_root: str | Path, file_path: str | Path) -> PythonImportAnalysisResult:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return PythonImportAnalysisResult(
            path=relative,
            imports=(),
            syntax_errors=(f"{relative}: skipped: {read_result.skipped_reason}",),
        )

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return PythonImportAnalysisResult(path=relative, imports=(), syntax_errors=(message,))

    visitor = _ImportVisitor(repo_root=root, file_path=target, source=source)
    visitor.visit(tree)

    return PythonImportAnalysisResult(
        path=relative,
        imports=tuple(sorted(visitor.imports, key=lambda item: (item.path, item.line, item.module or "", item.name or ""))),
        syntax_errors=(),
    )


def collect_python_imports(repo_root: str | Path, python_files: list[str | Path]) -> tuple[PythonImportAnalysisResult, ...]:
    root = Path(repo_root).resolve()
    results = [collect_imports_for_file(root, root / Path(path)) for path in python_files]
    return tuple(results)


def flatten_import_results(results: tuple[PythonImportAnalysisResult, ...]) -> tuple[ImportRecord, ...]:
    records: list[ImportRecord] = []
    for result in results:
        records.extend(result.imports)
    return tuple(sorted(records, key=lambda item: (item.path, item.line, item.module or "", item.name or "")))


def filter_imports_by_module(imports: tuple[ImportRecord, ...], module_query: str | None) -> tuple[ImportRecord, ...]:
    if not module_query:
        return imports

    lowered = module_query.lower()
    filtered = []
    for record in imports:
        haystack = " ".join(
            part
            for part in (
                record.module,
                record.name,
                record.alias,
                record.resolved_project_path,
                record.raw,
            )
            if part
        ).lower()
        if lowered in haystack:
            filtered.append(record)

    return tuple(filtered)
