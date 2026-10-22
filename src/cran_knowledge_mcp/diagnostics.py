"""Sanitized server-side diagnostics for unexpected application errors."""

import logging
import os
import re

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}\Z")


def safe_operation_id(value: str | None) -> str:
    """Return a bounded identifier, never arbitrary request text."""
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else "unknown_operation"


def log_internal_failure(logger: logging.Logger, operation: str | None, exc: Exception) -> None:
    """Log a useful default diagnostic; traceback text is an explicit opt-in."""
    operation_id = safe_operation_id(operation)
    error_type = safe_operation_id(type(exc).__name__)
    logger.error("Internal operation failed (operation=%s error_type=%s)", operation_id, error_type)
    if os.environ.get("LOG_INTERNAL_TRACEBACKS", "").strip().casefold() == "true":
        logger.debug(
            "Verbose internal traceback enabled (operation=%s error_type=%s)",
            operation_id,
            error_type,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def awaitable_operation_id(operation) -> str:
    """Get a coroutine's code-level name without inspecting call arguments."""
    code = getattr(operation, "cr_code", None)
    return safe_operation_id(getattr(code, "co_name", None))
