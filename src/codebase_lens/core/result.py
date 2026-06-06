from __future__ import annotations

from dataclasses import dataclass

from .constants import EXIT_GENERAL_ERROR, EXIT_SUCCESS, PARTIAL_IMPLEMENTATION_MESSAGE


@dataclass(frozen=True)
class CblCommandResult:
    command: str
    status: str
    exit_code: int
    message: str
    detail: str | None = None

    @classmethod
    def success(cls, command: str, message: str, detail: str | None = None) -> "CblCommandResult":
        return cls(command, "success", EXIT_SUCCESS, message, detail)

    @classmethod
    def partial(cls, command: str, detail: str) -> "CblCommandResult":
        return cls(command, "partial", EXIT_GENERAL_ERROR, PARTIAL_IMPLEMENTATION_MESSAGE, detail)


def emit_result(result: CblCommandResult, *, quiet: bool = False) -> None:
    if quiet:
        return
    print(f"CBL command: {result.command}")
    print(f"Status: {result.status}")
    print(result.message)
    if result.detail:
        print(f"Detail: {result.detail}")
