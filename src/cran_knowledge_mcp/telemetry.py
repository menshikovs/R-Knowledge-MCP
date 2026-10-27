"""Per-call benchmark signals with bounded projections of discovery fields.

Arbitrary arguments and result text never leave this module. Discovery query text and aliases
are retained only when allowlisted, bounded and free of likely secrets; call fingerprints are
keyed with a per-process random salt that is neither logged nor returned.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import UTC, datetime
from typing import Any

REPEAT_CAPACITY = 4096
_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9.]{0,99}")
_FUNCTION = re.compile(r"[A-Za-z0-9._:<>$@%&*+/=!?|^~-]{1,64}")
_STATUS = re.compile(r"[a-z][a-z_]{0,31}")
REPOSITORIES = frozenset({"cran", "bioconductor", "all"})
_DISCOVERY_TOOLS = frozenset({"get_function_docs", "list_package_functions"})
_MAX_DISCOVERY_QUERY_BYTES = 8192
_MAX_DISCOVERY_ALIASES = 30
_PROTOCOL_CALL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SECRET_TEXT = re.compile(
    r"sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|"
    r"(?:OPENAI_(?:EXECUTOR_)?API_KEY|CODEX_API_KEY|api_key|password|secret|authorization)"
    r"[\"']?\s*[=:]\s*[\"']?[^\s,;]+|"
    r"https?://[^/:\s]+:[^/@\s]+@|[?&](?:token|api_key|access_token|key)=[^&\s]+",
    re.IGNORECASE,
)
# Error codes that report a version the repository cannot serve or that differs from the
# requested one. Installed R package versions are never inspected by this server.
VERSION_MISMATCH_CODES = frozenset({"version_mismatch", "requested_version_unavailable"})


def safe_protocol_call_id(value: Any) -> str | None:
    """Normalize a bounded MCP request ID without retaining token-like values."""
    if type(value) is int and 0 <= value <= 2**53:
        value = str(value)
    if (
        isinstance(value, str)
        and _PROTOCOL_CALL_ID.fullmatch(value)
        and _SECRET_TEXT.search(value) is None
    ):
        return value
    return None


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class RepeatTracker:
    """Classify a call as first, identical, identical after an error, or similar.

    "Identical" means the same tool and normalized arguments. "Similar" means the same tool
    and package argument with different other arguments. Keys are salted digests, so the
    tables cannot be reversed or compared across processes.
    """

    def __init__(self) -> None:
        self._salt = secrets.token_bytes(16)
        self._calls: dict[str, list] = {}  # fingerprint -> [count, last_call_failed]
        self._similar: dict[str, set[str]] = {}  # tool+package digest -> fingerprints

    def _digest(self, text: str) -> str:
        return hmac.new(self._salt, text.encode(), hashlib.sha256).hexdigest()[:12]

    def begin(self, tool: str, arguments: dict[str, Any]):
        """Return (fingerprint, repeat_kind, repeat_count); all None if not computable."""
        try:
            canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=True, default=str)
        except (TypeError, ValueError, RecursionError):
            return None, None, None
        fingerprint = self._digest(f"{tool}:{canonical}")
        package = arguments.get("package") if isinstance(arguments, dict) else None
        similar_key = self._digest(f"{tool}|{package}") if isinstance(package, str) else None
        entry = self._calls.get(fingerprint)
        if entry is not None:
            kind = "identical_after_error" if entry[1] else "identical"
            count = entry[0]
        else:
            known = self._similar.get(similar_key) if similar_key else None
            kind = "similar" if known else "first"
            count = 0
        if len(self._calls) >= REPEAT_CAPACITY and entry is None:
            return fingerprint, None, None  # Table full: repeat information is unknown.
        if entry is None:
            entry = self._calls[fingerprint] = [0, False]
        entry[0] += 1
        if similar_key and len(self._similar) < REPEAT_CAPACITY:
            self._similar.setdefault(similar_key, set()).add(fingerprint)
        return fingerprint, kind, count

    def finish(self, fingerprint: str | None, failed: bool) -> None:
        entry = self._calls.get(fingerprint) if fingerprint else None
        if entry is not None:
            entry[1] = failed


def _json_size(value: Any) -> int | None:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None


def result_signals(arguments: dict[str, Any], result: Any) -> dict[str, Any]:
    """Numeric/categorical facts about one CallToolResult; never any result text."""
    structured = getattr(result, "structuredContent", None)
    structured = structured if isinstance(structured, dict) else None
    texts = [
        item.text
        for item in (getattr(result, "content", None) or [])
        if isinstance(getattr(item, "text", None), str)
    ]
    text_bytes = sum(len(text.encode("utf-8")) for text in texts)
    structured_bytes = _json_size(structured) if structured is not None else None
    duplicated = None
    if structured is not None and len(texts) == 1:
        try:
            duplicated = json.loads(texts[0]) == structured
        except ValueError:
            duplicated = False
    # content and structuredContent normally carry the same JSON; count it once as payload.
    unique = (
        text_bytes if duplicated or structured is None else text_bytes + (structured_bytes or 0)
    )
    is_error = bool(getattr(result, "isError", False))
    status = structured.get("verification_status") if structured else None
    status = status if isinstance(status, str) and _STATUS.fullmatch(status) else None
    errors = structured.get("errors") if structured else None
    sources = structured.get("sources") if structured else None
    if is_error or (status is None and not isinstance(errors, list)):
        partial = None  # Failed, or the tool reports no completeness information.
    else:
        partial = status == "partial" or bool(errors)
    codes = error_codes(structured)
    truncation = structured.get("output_truncation") if structured else None
    repository = (structured or {}).get("repository")
    repository = repository if repository in REPOSITORIES else arguments.get("repository")
    package = arguments.get("package")
    confirmed = (
        isinstance(package, str)
        and _PACKAGE.fullmatch(package)
        and status in {"verified", "partial"}
        and (structured or {}).get("package") == package
    )
    return {
        "verification_status": status,
        "source_count": len(sources) if isinstance(sources, list) else None,
        "partial": partial,
        "version_mismatch": bool(VERSION_MISMATCH_CODES & set(codes)),
        "output_truncated": isinstance(truncation, dict) and truncation.get("truncated") is True,
        "page_truncated": bool(structured and structured.get("truncated") is True),
        "repository": repository if repository in REPOSITORIES else None,
        "package": package if confirmed else None,
        "structured_bytes": structured_bytes,
        "text_content_bytes": text_bytes,
        "content_duplicates_structured": duplicated,
        "useful_bytes": unique,
    }


def discovery_signals(tool_name: str, arguments: dict[str, Any], result: Any) -> dict[str, Any]:
    """Project discovery request/response fields for the benchmark sidecar only.

    The caller gates this projection on benchmark run and trial identifiers. Snapshot tokens,
    arbitrary arguments, documentation and source text are never returned.
    """
    if tool_name not in _DISCOVERY_TOOLS or not isinstance(arguments, dict):
        return {}

    request: dict[str, Any] = {"status": "projected"}
    if isinstance(arguments.get("package"), str) and _PACKAGE.fullmatch(arguments["package"]):
        request["package"] = arguments["package"]
    repository = arguments.get("repository")
    if isinstance(repository, str) and repository in REPOSITORIES | {"CRAN", "Bioconductor"}:
        request["repository"] = repository
    for field in ("package_version", "version", "r_version", "bioc_version"):
        value = arguments.get(field)
        if (
            isinstance(value, str)
            and len(value) <= 40
            and re.fullmatch(r"[0-9]+(?:\.[0-9A-Za-z-]+)*|release|devel", value)
        ):
            request[field] = value
    function = arguments.get("function")
    if (
        isinstance(function, str)
        and len(function) <= 64
        and _FUNCTION.fullmatch(function)
        and _SECRET_TEXT.search(function) is None
    ):
        request["function"] = function
    query = next(
        (
            arguments[name]
            for name in ("query", "search", "search_query", "text")
            if name in arguments
        ),
        None,
    )
    if query is not None:
        try:
            query_bytes = len(query.encode("utf-8")) if isinstance(query, str) else None
        except UnicodeError:
            query_bytes = None
        if (
            isinstance(query, str)
            and query_bytes is not None
            and query_bytes <= _MAX_DISCOVERY_QUERY_BYTES
            and _SECRET_TEXT.search(query) is None
        ):
            request["query"] = query
        else:
            request["status"] = "partially_projected"
            request["query_redacted"] = True
            if query_bytes is not None:
                request["query_length_bytes"] = query_bytes
    for field in ("offset", "limit"):
        value = arguments.get(field)
        if type(value) is int and 0 <= value <= 10_000:
            request[field] = value
    if "snapshot" in arguments:
        request["snapshot_present"] = arguments["snapshot"] is not None

    response_data = getattr(result, "structuredContent", None)
    response_data = response_data if isinstance(response_data, dict) else {}
    response: dict[str, Any] = {"status": "projected"}
    for field in ("offset", "next_offset"):
        value = response_data.get(field)
        if value is None and field in response_data:
            response[field] = None
        elif type(value) is int and 0 <= value <= 10_000_000:
            response[field] = value
    for field in ("aliases", "available_aliases", "closest_aliases"):
        values = response_data.get(field)
        if not isinstance(values, list):
            continue
        aliases = []
        for item in values[: _MAX_DISCOVERY_ALIASES * 4]:
            if isinstance(item, dict):
                if item.get("kind") != "alias":
                    continue
                item = item.get("name")
            if (
                isinstance(item, str)
                and len(item) <= 64
                and _FUNCTION.fullmatch(item)
                and _SECRET_TEXT.search(item) is None
                and item not in aliases
            ):
                aliases.append(item)
            if len(aliases) >= _MAX_DISCOVERY_ALIASES:
                break
        response[field] = aliases

    return {"discovery_request": request, "discovery_response": response}


def error_codes(structured: dict | None) -> list[str]:
    """Top-level error.code plus errors[].error.code, in order and without duplicates."""
    if not structured:
        return []
    candidates = [structured.get("error")]
    errors = structured.get("errors")
    if isinstance(errors, list):
        candidates.extend(item.get("error") for item in errors[:32] if isinstance(item, dict))
    codes: list[str] = []
    for error in candidates:
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            if code not in codes:
                codes.append(code)
    return codes[:8]
