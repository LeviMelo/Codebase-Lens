from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileRecord:
    path: str
    absolute_path: str
    status: str
    git_status: str | None
    extension: str | None
    size_bytes: int
    sha256: str | None
    is_text: bool
    is_binary: bool
    is_large: bool
    is_included: bool
    skip_reason: str | None
    language: str | None
    line_count: int | None
    redacted: bool


@dataclass(frozen=True)
class SymbolRecord:
    id: str
    name: str
    qualified_name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    signature: str | None
    decorators: list[str]
    parent: str | None
    docstring_summary: str | None
    imports_used: list[str]
    is_exported: bool | None
    confidence: str


@dataclass(frozen=True)
class ImportRecord:
    path: str
    line: int
    module: str | None
    name: str | None
    alias: str | None
    level: int
    raw: str
    resolved_project_path: str | None
    confidence: str


@dataclass(frozen=True)
class CommandRecord:
    framework: str
    command_path: str
    function_name: str | None
    path: str
    start_line: int
    end_line: int
    decorators: list[str]
    help_text: str | None
    confidence: str
    limitations: list[str]


@dataclass(frozen=True)
class RouteRecord:
    framework: str
    method: str | None
    route_path: str | None
    function_name: str
    path: str
    start_line: int
    end_line: int
    decorators: list[str]
    confidence: str


@dataclass(frozen=True)
class TestRecord:
    path: str
    test_kind: str
    test_functions: list[str]
    test_classes: list[str]
    likely_targets: list[str]
    confidence: str


@dataclass(frozen=True)
class ContractFinding:
    rule_id: str
    severity: str
    status: str
    title: str
    message: str
    evidence: list[str]
    confidence: str
    remediation_hint: str | None


@dataclass(frozen=True)
class OmissionRecord:
    path: str
    reason: str
    size_bytes: int | None
    category: str | None
