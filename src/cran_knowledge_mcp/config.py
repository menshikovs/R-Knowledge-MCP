"""Validated process configuration from environment variables."""

import os

from .errors import KnowledgeError


def positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise KnowledgeError("invalid_configuration", f"{name} must be a positive number") from exc
    if not 0 < value <= 300:
        raise KnowledgeError("invalid_configuration", f"{name} must be in (0, 300]")
    return value


def positive_int(name: str, default: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise KnowledgeError("invalid_configuration", f"{name} must be a positive integer") from exc
    if not 1 <= value <= maximum:
        raise KnowledgeError("invalid_configuration", f"{name} must be in [1, {maximum}]")
    return value


def cache_ttl(default: int) -> int:
    return positive_int("CACHE_TTL_SECONDS", default, 86400)


def cache_bytes() -> int:
    return positive_int("CACHE_MAX_BYTES", 64 << 20, 256 << 20)


def context7_api_key() -> str | None:
    value = os.environ.get("CONTEXT7_API_KEY", "").strip()
    return value or None


def http_user_agent() -> str:
    value = os.environ.get(
        "HTTP_USER_AGENT",
        "cran-knowledge-mcp/0.1 (+https://github.com/menshikovs/R-Knowledge-MCP)",
    ).strip()
    if not value or len(value) > 200 or any(ord(char) < 32 for char in value):
        raise KnowledgeError(
            "invalid_configuration", "HTTP_USER_AGENT must be 1..200 printable chars"
        )
    return value
