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


def prompt_intelligence_enabled() -> bool:
    raw = os.environ.get("PROMPT_INTELLIGENCE_ENABLED", "true").strip().casefold()
    if raw not in {"true", "false", "1", "0", "yes", "no"}:
        raise KnowledgeError(
            "invalid_configuration", "PROMPT_INTELLIGENCE_ENABLED must be a boolean"
        )
    return raw in {"true", "1", "yes"}


def prompt_max_input_chars() -> int:
    return positive_int("PROMPT_MAX_INPUT_CHARS", 8000, 32000)


def prompt_max_output_chars() -> int:
    return positive_int("PROMPT_MAX_OUTPUT_CHARS", 24000, 48000)


def prompt_max_grounding_packages() -> int:
    return positive_int("PROMPT_MAX_GROUNDING_PACKAGES", 5, 10)


def prompt_default_target() -> str:
    value = os.environ.get("PROMPT_DEFAULT_TARGET", "codex").strip().casefold()
    if value not in {"codex", "chatgpt", "generic"}:
        raise KnowledgeError(
            "invalid_configuration", "PROMPT_DEFAULT_TARGET must be codex, chatgpt or generic"
        )
    return value


def prompt_default_detail_level() -> str:
    value = os.environ.get("PROMPT_DEFAULT_DETAIL_LEVEL", "standard").strip().casefold()
    if value not in {"concise", "standard", "comprehensive"}:
        raise KnowledgeError(
            "invalid_configuration",
            "PROMPT_DEFAULT_DETAIL_LEVEL must be concise, standard or comprehensive",
        )
    return value
