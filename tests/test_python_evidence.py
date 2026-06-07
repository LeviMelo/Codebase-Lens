from __future__ import annotations

from pathlib import Path

from codebase_lens.analyzers.imports import collect_imports_for_file, resolve_project_import
from codebase_lens.analyzers.python_ast import collect_symbols_for_file, find_symbol_matches


def test_collect_symbols_for_file_detects_classes_functions_methods_and_decorators(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source_dir = repo / "src" / "pkg"
    source_dir.mkdir(parents=True)
    source = source_dir / "module.py"
    source.write_text(
        "\n".join(
            [
                "def top_level(a: int) -> int:",
                "    return a + 1",
                "",
                "class Worker:",
                "    \"\"\"Worker docstring.\"\"\"",
                "    @classmethod",
                "    def build(cls):",
                "        return cls()",
                "",
                "    async def run(self):",
                "        return None",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = collect_symbols_for_file(repo, source)

    assert result.syntax_errors == ()
    names = {(record.kind, record.qualified_name) for record in result.symbols}
    assert ("function", "top_level") in names
    assert ("class", "Worker") in names
    assert ("method", "Worker.build") in names
    assert ("method", "Worker.run") in names

    build = [record for record in result.symbols if record.qualified_name == "Worker.build"][0]
    assert "classmethod" in build.decorators
    assert build.start_line == 7
    assert build.end_line == 8

    matches = find_symbol_matches(result.symbols, "build")
    assert len(matches) == 1
    assert matches[0].qualified_name == "Worker.build"


def test_collect_imports_resolves_project_imports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    package = repo / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helpers.py").write_text("VALUE = 1\n", encoding="utf-8")
    source = package / "module.py"
    source.write_text(
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                "from .helpers import VALUE",
                "from pkg import helpers",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = collect_imports_for_file(repo, source)

    assert result.syntax_errors == ()
    imports = result.imports
    assert any(record.module == "os" for record in imports)
    assert any(record.module == "pathlib" and record.name == "Path" for record in imports)
    assert any(record.module == "helpers" and record.name == "VALUE" and record.resolved_project_path == "src/pkg/helpers.py" for record in imports)
    assert any(record.module == "pkg" and record.name == "helpers" and record.resolved_project_path == "src/pkg/helpers.py" for record in imports)

    resolved = resolve_project_import(repo, source, module="pkg.helpers", name=None, level=0)
    assert resolved == "src/pkg/helpers.py"


def test_syntax_errors_are_reported_without_raising(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bad = repo / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")

    symbol_result = collect_symbols_for_file(repo, bad)
    import_result = collect_imports_for_file(repo, bad)

    assert symbol_result.symbols == ()
    assert import_result.imports == ()
    assert symbol_result.syntax_errors
    assert import_result.syntax_errors
