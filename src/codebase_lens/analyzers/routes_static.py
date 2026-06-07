from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codebase_lens.core.models import RouteRecord
from codebase_lens.core.paths import to_posix_relative
from codebase_lens.core.textio import read_text_with_policy


@dataclass(frozen=True)
class RouteStaticAnalysisResult:
    path: str
    routes: tuple[RouteRecord, ...]
    syntax_errors: tuple[str, ...]
    limitations: tuple[str, ...]


HTTP_METHOD_DECORATORS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "options": "OPTIONS",
    "head": "HEAD",
    "websocket": "WEBSOCKET",
}


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_methods(node: ast.AST | None) -> list[str]:
    if isinstance(node, ast.List) or isinstance(node, ast.Tuple) or isinstance(node, ast.Set):
        values: list[str] = []
        for item in node.elts:
            literal = _literal_string(item)
            if literal:
                values.append(literal.upper())
        return values
    literal = _literal_string(node)
    if literal:
        return [literal.upper()]
    return []


def _call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _call_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"


def _route_path_from_call(call: ast.Call) -> str | None:
    if call.args:
        value = _literal_string(call.args[0])
        if value:
            return value
    for keyword in call.keywords:
        if keyword.arg in {"path", "rule"}:
            value = _literal_string(keyword.value)
            if value:
                return value
    return None


def _methods_from_route_call(call: ast.Call, decorator_attr: str) -> list[str | None]:
    if decorator_attr in HTTP_METHOD_DECORATORS:
        return [HTTP_METHOD_DECORATORS[decorator_attr]]

    for keyword in call.keywords:
        if keyword.arg == "methods":
            methods = _literal_methods(keyword.value)
            if methods:
                return methods

    if decorator_attr == "route":
        return ["GET"]

    return [None]


def _framework_for_decorator(full_name: str, decorator_attr: str) -> str:
    lowered = full_name.lower()
    if decorator_attr == "route":
        return "flask"
    if decorator_attr in HTTP_METHOD_DECORATORS:
        return "fastapi"
    if "flask" in lowered:
        return "flask"
    if "router" in lowered or "app" in lowered:
        return "fastapi"
    return "unknown"


def collect_routes_for_file(repo_root: str | Path, file_path: str | Path) -> RouteStaticAnalysisResult:
    root = Path(repo_root).resolve()
    target = Path(file_path).resolve()
    relative = to_posix_relative(root, target)

    read_result = read_text_with_policy(target)
    if read_result.skipped_reason:
        return RouteStaticAnalysisResult(
            path=relative,
            routes=(),
            syntax_errors=(f"{relative}: skipped: {read_result.skipped_reason}",),
            limitations=(),
        )

    source = read_result.text or ""

    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        message = f"{relative}:{exc.lineno or 0}:{exc.offset or 0}: {exc.msg}"
        return RouteStaticAnalysisResult(path=relative, routes=(), syntax_errors=(message,), limitations=())

    records: list[RouteRecord] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue

            attr = decorator.func.attr.lower()
            if attr not in HTTP_METHOD_DECORATORS and attr != "route":
                continue

            route_path = _route_path_from_call(decorator)
            methods = _methods_from_route_call(decorator, attr)
            framework = _framework_for_decorator(_call_name(decorator.func), attr)

            for method in methods:
                records.append(
                    RouteRecord(
                        framework=framework,
                        method=method,
                        route_path=route_path,
                        function_name=node.name,
                        path=relative,
                        start_line=int(getattr(node, "lineno", 1)),
                        end_line=int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                        decorators=[_safe_unparse(decorator)],
                        confidence="high" if route_path else "medium",
                    )
                )

    return RouteStaticAnalysisResult(
        path=relative,
        routes=tuple(sorted(records, key=lambda item: (item.path, item.route_path or "", item.method or "", item.function_name))),
        syntax_errors=(),
        limitations=("Static route analysis does not import FastAPI or Flask applications.",),
    )


def collect_routes(repo_root: str | Path, python_files: list[str | Path], *, framework: str = "all") -> tuple[RouteStaticAnalysisResult, ...]:
    root = Path(repo_root).resolve()
    results: list[RouteStaticAnalysisResult] = []

    for path in python_files:
        result = collect_routes_for_file(root, root / Path(path))
        if framework != "all":
            filtered = tuple(record for record in result.routes if record.framework == framework)
            result = RouteStaticAnalysisResult(
                path=result.path,
                routes=filtered,
                syntax_errors=result.syntax_errors,
                limitations=result.limitations,
            )
        results.append(result)

    return tuple(results)


def flatten_route_results(results: tuple[RouteStaticAnalysisResult, ...]) -> tuple[RouteRecord, ...]:
    records: list[RouteRecord] = []
    for result in results:
        records.extend(result.routes)
    return tuple(sorted(records, key=lambda item: (item.path, item.route_path or "", item.method or "", item.function_name)))
