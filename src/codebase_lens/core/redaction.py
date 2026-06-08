from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SECRET_KEYS = (
    "API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "SECRET",
    "TOKEN",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "CLIENT_SECRET",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_CLIENT_SECRET",
    "DATABASE_URL",
    "POSTGRES_URL",
    "MYSQL_URL",
    "REDIS_URL",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "SLACK_TOKEN",
    "DISCORD_TOKEN",
    "JWT_SECRET",
)

PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----.*?-----END (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)

SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?P<prefix>(?P<key>["']?(?:API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|SECRET|TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|CLIENT_SECRET|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AZURE_CLIENT_SECRET|DATABASE_URL|POSTGRES_URL|MYSQL_URL|REDIS_URL|GOOGLE_APPLICATION_CREDENTIALS|GITHUB_TOKEN|GITLAB_TOKEN|SLACK_TOKEN|DISCORD_TOKEN|JWT_SECRET)["']?)\s*(?:=|:)\s*)(?P<quote>["']?)(?P<value>[^"'\s,}\]]+)(?P=quote)""",
    re.IGNORECASE,
)

SECRET_VALUE_RE = re.compile(
    r"(?:sk-[A-Za-z0-9][A-Za-z0-9_-]{8,}|fixture-(?:password|token)-[A-Za-z0-9_-]+|postgres://[^\s\"'`]+|mysql://[^\s\"'`]+|redis://[^\s\"'`]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RedactionStats:
    enabled: bool
    redacted_occurrences_count: int
    patterns_hit: tuple[str, ...]


@dataclass(frozen=True)
class RedactionResult:
    text: str
    stats: RedactionStats


def _canonical_key(raw_key: str) -> str:
    key = raw_key.strip().strip('"').strip("'").upper()
    return key


def redact_text(text: str, *, enabled: bool = True) -> RedactionResult:
    if not enabled:
        return RedactionResult(text=text, stats=RedactionStats(False, 0, ()))

    occurrences = 0
    patterns_hit: set[str] = set()

    def private_key_replacer(match: re.Match[str]) -> str:
        nonlocal occurrences
        occurrences += 1
        patterns_hit.add("PRIVATE_KEY")
        return "<REDACTED_PRIVATE_KEY_BLOCK>"

    redacted = PRIVATE_KEY_BLOCK_RE.sub(private_key_replacer, text)

    def assignment_replacer(match: re.Match[str]) -> str:
        nonlocal occurrences
        value = match.group("value")
        if value in {"<REDACTED>", "<REDACTED_PRIVATE_KEY_BLOCK>"}:
            return match.group(0)

        occurrences += 1
        key = _canonical_key(match.group("key"))
        patterns_hit.add(key)
        return f"{match.group('prefix')}{match.group('quote')}<REDACTED>{match.group('quote')}"

    redacted = SECRET_ASSIGNMENT_RE.sub(assignment_replacer, redacted)

    def value_replacer(match: re.Match[str]) -> str:
        nonlocal occurrences
        value = match.group(0)
        if value.startswith("<REDACTED"):
            return value
        occurrences += 1
        patterns_hit.add("SECRET_VALUE")
        return "<REDACTED_SECRET_VALUE>"

    redacted = SECRET_VALUE_RE.sub(value_replacer, redacted)

    return RedactionResult(
        text=redacted,
        stats=RedactionStats(
            enabled=True,
            redacted_occurrences_count=occurrences,
            patterns_hit=tuple(sorted(patterns_hit)),
        ),
    )


def redact_console_text(text: str) -> str:
    return redact_text(text).text



def redact_string(value: str, *, enabled: bool = True) -> str:
    return redact_text(value, enabled=enabled).text


def redact_jsonable(value: Any, *, enabled: bool = True) -> Any:
    if not enabled:
        return value
    if isinstance(value, str):
        return redact_string(value, enabled=enabled)
    if isinstance(value, dict):
        return {str(key): redact_jsonable(item, enabled=enabled) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_jsonable(item, enabled=enabled) for item in value]
    if isinstance(value, tuple):
        return [redact_jsonable(item, enabled=enabled) for item in value]
    return value
