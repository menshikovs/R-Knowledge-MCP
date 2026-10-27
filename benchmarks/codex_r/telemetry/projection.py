"""Safe benchmark-only MCP request/response projections (schema 2.1).

This module projects a closed set of identifiers, measurements and bounded safe discovery
queries. It never returns arbitrary arguments, result text, documentation, source code, schemas,
or exception text.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_VERSION = "2.1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"2.0", SCHEMA_VERSION})
MAX_QUERY_BYTES = 8192
MAX_URLS = 16
MAX_ALIASES = 30
MAX_LINE_BYTES = 32 << 10
MAX_FILE_BYTES = 8 << 20
MAX_RECORDS = 5000
OFFICIAL_HOSTS = frozenset(
    {
        "cran.r-project.org",
        "stat.ethz.ch",
        "bioconductor.org",
        "docs.posit.co",
        "docs.rstudio.com",
    }
)
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9.]{0,99}\Z")
FUNCTION = re.compile(r"[A-Za-z0-9._:<>$@%&*+/=!?|^~-]{1,64}\Z")
VERSION = re.compile(r"[0-9]+(?:\.[0-9A-Za-z-]+)*\Z")
SNAKE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
FINGERPRINT = re.compile(r"[0-9a-f]{32}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")
SECRET_TEXT = re.compile(
    r"sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|"
    r"(?:OPENAI_(?:EXECUTOR_)?API_KEY|CODEX_API_KEY|api_key|password|secret|authorization)"
    r"[\"']?\s*[=:]\s*[\"']?[^\s,;]+|"
    r"https?://[^/:\s]+:[^/@\s]+@|[?&](?:token|api_key|access_token|key)=[^&\s]+",
    re.IGNORECASE,
)
SECRET_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "token",
        "password",
        "secret",
        "credentials",
    }
)
REQUEST_FIELDS = frozenset(
    {
        "package",
        "repository",
        "r_version",
        "bioc_version",
        "package_version",
        "version",
        "function",
        "section",
        "offset",
        "limit",
        "snapshot_present",
    }
)
TEXT_QUERY_FIELDS = frozenset({"query", "search", "search_query", "text"})
REQUEST_PROJECTION_KEYS = frozenset(
    {
        "status",
        "unknown_argument_count",
        "query_present",
        "query_length_bytes",
        "query_line_count",
        "query_word_count",
        "query_fingerprint",
        "query_projection_status",
        "query_text",
        "request_bytes",
        *REQUEST_FIELDS,
    }
)
RESPONSE_PROJECTION_KEYS = frozenset(
    {
        "status",
        "is_error",
        "error_codes",
        "package",
        "version",
        "requested_version",
        "r_version",
        "bioc_version",
        "repository",
        "verification_status",
        "compatibility_status",
        "partial",
        "checked_at",
        "available_aliases",
        "closest_aliases",
        "aliases",
        "source_urls",
        "truncated",
        "output_truncated",
        "page_truncated",
        "next_offset",
        "offset",
        "alias_count",
        "source_count",
        "structured_bytes",
        "useful_bytes",
        "response_bytes",
        "text_content_bytes",
        "duration_ms",
        "secret_or_complex_payload_detected",
    }
)


def _safe_string(value, pattern, limit):
    return (
        value
        if isinstance(value, str)
        and len(value) <= limit
        and pattern.fullmatch(value)
        and SECRET_TEXT.search(value) is None
        else None
    )


def _walk_for_secrets(value, *, depth=0, budget=None):
    if budget is None:
        budget = [512]
    budget[0] -= 1
    if budget[0] < 0 or depth > 8:
        return True
    if isinstance(value, dict):
        for index, (key, item) in enumerate(value.items()):
            if index >= 256:
                return True
            if not isinstance(key, str) or key.casefold() in SECRET_KEYS:
                return True
            if _walk_for_secrets(item, depth=depth + 1, budget=budget):
                return True
    elif isinstance(value, list):
        return any(_walk_for_secrets(item, depth=depth + 1, budget=budget) for item in value[:256])
    elif isinstance(value, str):
        return len(value) > (1 << 20) or SECRET_TEXT.search(value) is not None
    return False


def _size_bytes(value, *, max_nodes=10000, max_depth=12, max_bytes=4 << 20):
    """Bounded UTF-8 JSON byte count; returns None for oversized or unsupported values."""
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise OverflowError
        if item is None:
            return 4
        if item is True:
            return 4
        if item is False:
            return 5
        if type(item) in (int, float):
            if type(item) is float and not math.isfinite(item):
                raise ValueError
            return len(json.dumps(item, separators=(",", ":")))
        if isinstance(item, str):
            if len(item) > 4 << 20:
                raise OverflowError
            return len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if isinstance(item, list):
            return (
                2
                + max(0, len(item) - 1)
                + sum(visit(child, depth + 1) for child in item[:max_nodes])
            )
        if isinstance(item, dict):
            total = 2 + max(0, len(item) - 1)
            for index, (key, child) in enumerate(item.items()):
                if index >= max_nodes:
                    raise OverflowError
                if not isinstance(key, str):
                    raise ValueError
                total += len(json.dumps(key, ensure_ascii=False).encode("utf-8")) + 1
                total += visit(child, depth + 1)
                if total > max_bytes:
                    raise OverflowError
            return total
        raise ValueError

    try:
        size = visit(value, 0)
        return size if size <= max_bytes else None
    except (OverflowError, ValueError, TypeError):
        return None


def _query_shape(text, salt):
    raw = text.encode("utf-8", errors="strict")
    shape = {
        "query_present": True,
        "query_length_bytes": len(raw),
        "query_line_count": text.count("\n") + 1,
        "query_word_count": len(re.findall(r"[^\W_]+", text, re.UNICODE)),
    }
    if len(raw) > MAX_QUERY_BYTES or SECRET_TEXT.search(text):
        shape["query_fingerprint"] = None
        shape["query_projection_status"] = "redacted"
    else:
        shape["query_text"] = text
        shape["query_fingerprint"] = hmac.new(salt, raw, hashlib.sha256).hexdigest()[:32]
        shape["query_projection_status"] = "projected"
    return shape


def _project_request(arguments, *, salt=None):
    if salt is None:
        salt = secrets.token_bytes(32)
    if not isinstance(arguments, dict):
        return {"status": "unavailable", "unknown_argument_count": None}
    projected = {"status": "projected", "unknown_argument_count": 0}
    query = None
    unknown = 0
    for index, (key, value) in enumerate(arguments.items()):
        if index >= 256:
            projected["status"] = "partially_projected"
            break
        if not isinstance(key, str):
            projected["status"] = "partially_projected"
            unknown += 1
            continue
        normalized = key.casefold()
        if normalized == "snapshot":
            if value is None or isinstance(value, str) and len(value) <= 4096:
                projected["snapshot_present"] = bool(value)
            else:
                projected["status"] = "partially_projected"
                unknown += 1
            continue
        if normalized in TEXT_QUERY_FIELDS:
            query = value if isinstance(value, str) else None
            if query is not None:
                raw = query.encode("utf-8", errors="strict")
                if len(raw) > MAX_QUERY_BYTES or SECRET_TEXT.search(query):
                    projected.update(
                        query_present=True,
                        query_length_bytes=len(raw),
                        query_line_count=query.count("\n") + 1,
                        query_word_count=len(re.findall(r"[^\W_]+", query, re.UNICODE)),
                        query_fingerprint=None,
                        query_projection_status="redacted",
                    )
                else:
                    projected.update(_query_shape(query, salt))
            else:
                projected["status"] = "partially_projected"
            continue
        if normalized in SECRET_KEYS or _walk_for_secrets(value):
            projected["status"] = "partially_projected"
            unknown += 1
            continue
        if normalized not in REQUEST_FIELDS:
            unknown += 1
            projected["status"] = "partially_projected"
            continue
        if normalized in {"package", "section"}:
            clean = _safe_string(value, PACKAGE, 100)
        elif normalized == "function":
            clean = _safe_string(value, FUNCTION, 64)
        elif normalized == "repository":
            clean = (
                value
                if isinstance(value, str)
                and value in {"cran", "bioconductor", "all", "CRAN", "Bioconductor"}
                else None
            )
        elif normalized == "snapshot_present":
            clean = value if type(value) is bool else None
        elif normalized in {"version", "package_version", "r_version", "bioc_version"}:
            clean = _safe_string(value, VERSION, 40)
        else:
            clean = value if type(value) is int and 0 <= value <= 10000 else None
        if clean is None:
            unknown += 1
            projected["status"] = "partially_projected"
        else:
            projected[normalized] = clean
    if len(arguments) > 256:
        unknown += len(arguments) - 256
        projected["status"] = "partially_projected"
    projected["unknown_argument_count"] = unknown
    projected["request_bytes"] = _size_bytes(arguments)
    if projected.get("query_fingerprint") is None and query is not None:
        projected["status"] = "partially_projected"
    return projected


def project_request(arguments, *, salt=None):
    """Never let malformed external values escape the measurement boundary."""
    try:
        return _project_request(arguments, salt=salt)
    except Exception:
        return {"status": "failed", "unknown_argument_count": None}


def _codes(value):
    codes = []
    if not isinstance(value, dict):
        return codes
    candidates = []
    error = value.get("error")
    if isinstance(error, dict):
        candidates.append(error.get("code"))
    candidates.append(value.get("code"))
    errors = value.get("errors")
    if isinstance(errors, list):
        for item in errors[:16]:
            if isinstance(item, dict):
                nested = item.get("error")
                candidates.append(
                    nested.get("code") if isinstance(nested, dict) else item.get("code")
                )
    for code in candidates:
        if isinstance(code, str) and SNAKE.fullmatch(code) and code not in codes:
            codes.append(code)
    return codes[:8]


def _safe_official_url(value):
    if not isinstance(value, str) or len(value) > 512 or SECRET_TEXT.search(value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or parts.hostname not in OFFICIAL_HOSTS
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not parts.path.startswith("/")
    ):
        return None
    try:
        if parts.port is not None:
            return None
    except ValueError:
        return None
    return value


def _aliases(value, cap):
    if not isinstance(value, list):
        return None
    aliases = []
    for item in value[: cap * 4]:
        if isinstance(item, dict):
            if item.get("kind") != "alias":
                continue
            item = item.get("name")
        alias = _safe_string(item, FUNCTION, 64)
        if alias is not None and alias not in aliases:
            aliases.append(alias)
        if len(aliases) == cap:
            break
    return aliases


def _extract_payload(result):
    if not isinstance(result, dict):
        return None
    structured = result.get("structuredContent", result.get("structured_content"))
    return structured if isinstance(structured, dict) else None


def _project_response(result, *, duration_ms=None):
    if not isinstance(result, dict):
        return {"status": "unavailable"}
    structured = _extract_payload(result)
    if structured is None:
        structured = result
    if _walk_for_secrets(structured):
        # Keep only structural sizes/status; discard every field value that could carry a secret.
        return {
            "status": "partially_projected",
            "secret_or_complex_payload_detected": True,
            "is_error": result.get("isError") if type(result.get("isError")) is bool else None,
            "structured_bytes": _size_bytes(
                result.get("structuredContent", result.get("structured_content"))
            ),
            "text_content_bytes": _content_bytes(result.get("content")),
            "duration_ms": _bounded_number(duration_ms),
        }
    projected = {
        "status": "projected",
        "is_error": result.get("isError") if type(result.get("isError")) is bool else None,
    }
    codes = _codes(structured)
    if codes:
        projected["error_codes"] = codes
    for field in ("package", "version", "requested_version", "r_version", "bioc_version"):
        value = structured.get(field)
        if field == "version" and structured.get("package_version") is not None:
            value = structured["package_version"]
        clean = _safe_string(
            value,
            PACKAGE if field == "package" else VERSION,
            100 if field == "package" else 40,
        )
        if clean is not None:
            projected[field] = clean
    repository = structured.get("repository")
    if isinstance(repository, str) and repository in {
        "cran",
        "bioconductor",
        "all",
        "CRAN",
        "Bioconductor",
    }:
        projected["repository"] = repository
    for field in ("verification_status", "compatibility_status", "status"):
        value = structured.get(field)
        if isinstance(value, str) and SNAKE.fullmatch(value):
            projected[field] = value
    for field in ("checked_at", "retrieved_at", "source_checked_at", "timestamp_utc"):
        value = structured.get(field)
        if isinstance(value, str) and TIMESTAMP.fullmatch(value):
            projected["checked_at"] = value
            break
    for field in ("available_aliases", "closest_aliases", "aliases"):
        value = _aliases(structured.get(field), MAX_ALIASES)
        if value is not None:
            projected[field] = value
    urls = []
    for field in ("sources", "source_urls", "documentation_urls"):
        value = structured.get(field)
        if isinstance(value, list):
            for item in value[:MAX_URLS]:
                url = item.get("url") if isinstance(item, dict) else item
                safe_url = _safe_official_url(url)
                if safe_url and safe_url not in urls:
                    urls.append(safe_url)
    if urls:
        projected["source_urls"] = urls[:MAX_URLS]
    for field in ("truncated", "output_truncated", "page_truncated"):
        value = structured.get(field)
        if type(value) is bool:
            projected[field] = value
    truncation = structured.get("output_truncation")
    if isinstance(truncation, dict) and type(truncation.get("truncated")) is bool:
        projected["output_truncated"] = truncation["truncated"]
    for field in ("next_offset", "offset", "alias_count", "source_count"):
        value = structured.get(field)
        if field == "next_offset" and value is None and field in structured:
            projected[field] = None
        elif type(value) is int and 0 <= value <= 10_000_000:
            projected[field] = value
    for field in ("structured_bytes", "useful_bytes", "response_bytes"):
        value = structured.get(field)
        clean = _bounded_number(value, integer=True)
        if clean is not None:
            projected[field] = clean
    projected["structured_bytes"] = projected.get(
        "structured_bytes",
        _size_bytes(result.get("structuredContent", result.get("structured_content"))),
    )
    projected["text_content_bytes"] = _content_bytes(result.get("content"))
    projected["response_bytes"] = _size_bytes(result)
    projected["duration_ms"] = _bounded_number(duration_ms)
    return projected


def project_response(result, *, duration_ms=None):
    """Return a closed failure marker if any untrusted payload resists projection."""
    try:
        return _project_response(result, duration_ms=duration_ms)
    except Exception:
        return {"status": "failed"}


def _bounded_number(value, *, integer=False):
    if type(value) not in (int, float) or value < 0 or not math.isfinite(value):
        return None
    if integer and type(value) is not int:
        return None
    return round(value, 3) if type(value) is float else value


def _content_bytes(content):
    if not isinstance(content, list):
        return None
    total = 0
    for item in content[:128]:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            if len(item["text"]) > 4 << 20:
                return None
            total += len(item["text"].encode("utf-8"))
            if total > 4 << 20:
                return None
    return total


def new_salt():
    return secrets.token_bytes(32)


def new_client_state():
    return {"salt": new_salt(), "pending": {}, "completed": [], "next_call_number": 0}


def observe_client_item(state, item, *, added):
    """Capture a bounded projection before the raw stream event is discarded."""
    if not isinstance(item, dict):
        return
    item_id = item.get("id")
    item_id = (
        item_id
        if isinstance(item_id, str)
        and ID.fullmatch(item_id)
        and SECRET_TEXT.search(item_id) is None
        else None
    )
    tool = item.get("name") or item.get("tool") or item.get("tool_name")
    if not isinstance(tool, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,63}", tool):
        return
    key = item_id or f"anonymous-{state['next_call_number']}"
    if added:
        state["next_call_number"] += 1
        key = item_id or f"anonymous-{state['next_call_number']}"
        state["pending"][key] = {
            "client_call_number": state["next_call_number"],
            "client_item_id": item_id,
            "tool": tool,
            "request_projection": project_request(item.get("arguments"), salt=state["salt"]),
            "started_monotonic": time.monotonic(),
        }
        return
    pending = state["pending"].pop(key, None)
    if pending is None:
        state["next_call_number"] += 1
        pending = {
            "client_call_number": state["next_call_number"],
            "client_item_id": item_id,
            "tool": tool,
            "request_projection": project_request(item.get("arguments"), salt=state["salt"]),
            "started_monotonic": None,
        }
    result = item.get("result", item.get("output"))
    duration = (
        max(0.0, (time.monotonic() - pending["started_monotonic"]) * 1000)
        if pending["started_monotonic"] is not None
        else None
    )
    state["completed"].append(
        {
            **{
                key: pending[key]
                for key in ("client_call_number", "client_item_id", "tool", "request_projection")
            },
            "response_projection": project_response(result, duration_ms=duration),
            "duration_ms": _bounded_number(duration),
        }
    )


def finalize_client_state(state):
    """Mark calls without a terminal client event as unresolved without inventing a result."""
    for pending in state["pending"].values():
        duration = (
            max(0.0, (time.monotonic() - pending["started_monotonic"]) * 1000)
            if pending["started_monotonic"] is not None
            else None
        )
        state["completed"].append(
            {
                **{
                    key: pending[key]
                    for key in (
                        "client_call_number",
                        "client_item_id",
                        "tool",
                        "request_projection",
                    )
                },
                "response_projection": {"status": "unavailable"},
                "duration_ms": _bounded_number(duration),
            }
        )
    state["pending"].clear()
    state["completed"].sort(key=lambda call: call["client_call_number"])
    return state["completed"]


def correlate(client_calls, server_calls):
    """Link by observed order only; never label an ordinal guess as a confirmed identifier."""
    comparable = len(client_calls) == len(server_calls) and all(
        client.get("tool") == server.get("tool_name")
        for client, server in zip(client_calls, server_calls, strict=False)
    )
    rows = []
    linked_server_numbers = set()
    for index, client in enumerate(client_calls):
        server = server_calls[index] if comparable else None
        if server is not None:
            linked_server_numbers.add(server.get("call_number"))
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_type": "mcp.call.observed",
                "source": "agent_stream",
                "client_call_number": index + 1,
                "client_item_id": client.get("client_item_id"),
                "server_call_number": server.get("call_number") if server else None,
                "tool": client.get("tool"),
                "correlation_quality": "inferred_ordinal" if server else "unmatched_client",
                "request_projection": client.get("request_projection"),
                "response_projection": client.get("response_projection"),
                "duration_ms": client.get("duration_ms"),
                "client_protocol_call_id": None,
                "server_protocol_call_id": (
                    server.get("server_protocol_call_id") if server else None
                ),
            }
        )
    for server in server_calls:
        if server.get("call_number") in linked_server_numbers:
            continue
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_type": "mcp.call.observed",
                "source": "mcp_server",
                "client_call_number": None,
                "client_item_id": None,
                "server_call_number": server.get("call_number"),
                "tool": server.get("tool_name"),
                "correlation_quality": "unmatched_server",
                "request_projection": server.get("discovery_request_projection")
                or {"status": "unavailable"},
                "response_projection": {
                    **_server_response(server),
                    **(
                        {
                            field: value
                            for field, value in server["discovery_response_projection"].items()
                            if field
                            in {
                                "aliases",
                                "available_aliases",
                                "closest_aliases",
                                "offset",
                                "next_offset",
                            }
                        }
                        if isinstance(server.get("discovery_response_projection"), dict)
                        else {}
                    ),
                },
                "duration_ms": _bounded_number(server.get("duration_ms")),
                "client_protocol_call_id": None,
                "server_protocol_call_id": server.get("server_protocol_call_id"),
            }
        )
    return rows


def _server_response(server):
    result = {"status": "projected", "is_error": server.get("status") == "error"}
    for field in (
        "package",
        "repository",
        "verification_status",
        "error_codes",
        "source_count",
        "partial",
        "output_truncated",
        "page_truncated",
        "response_bytes",
    ):
        if field in server:
            result[field] = server[field]
    return result


def _valid_scalar_tree(value, *, depth=0, string_limit=1024):
    if depth > 8:
        return False
    if value is None or type(value) in (bool, int, float):
        return not isinstance(value, float) or math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= string_limit
    if isinstance(value, list):
        return len(value) <= 128 and all(
            _valid_scalar_tree(v, depth=depth + 1, string_limit=string_limit) for v in value
        )
    if isinstance(value, dict):
        return len(value) <= 128 and all(
            isinstance(k, str)
            and len(k) <= 80
            and _valid_scalar_tree(
                v,
                depth=depth + 1,
                string_limit=MAX_QUERY_BYTES if k == "query_text" else string_limit,
            )
            for k, v in value.items()
        )
    return False


def validate_record(record):
    """Closed, bounded validator for one projection JSONL row."""
    expected = {
        "schema_version",
        "event_type",
        "source",
        "client_call_number",
        "client_item_id",
        "server_call_number",
        "tool",
        "correlation_quality",
        "request_projection",
        "response_projection",
        "duration_ms",
        "client_protocol_call_id",
        "server_protocol_call_id",
    }
    if not isinstance(record, dict) or set(record) != expected:
        return False
    if (
        record["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS
        or record["event_type"] != "mcp.call.observed"
        or record["source"] not in {"agent_stream", "mcp_server"}
        or record["correlation_quality"]
        not in {"confirmed", "inferred_ordinal", "unmatched_client", "unmatched_server"}
        or not isinstance(record["tool"], str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,63}", record["tool"])
    ):
        return False
    if record["client_item_id"] is not None and (
        not ID.fullmatch(record["client_item_id"]) or SECRET_TEXT.search(record["client_item_id"])
    ):
        return False
    for name in ("client_protocol_call_id", "server_protocol_call_id"):
        if record[name] is not None and (
            not ID.fullmatch(record[name]) or SECRET_TEXT.search(record[name])
        ):
            return False
    for name in ("client_call_number", "server_call_number"):
        if record[name] is not None and (type(record[name]) is not int or record[name] < 1):
            return False
    if record["duration_ms"] is not None and _bounded_number(record["duration_ms"]) is None:
        return False
    request = record["request_projection"]
    response = record["response_projection"]
    if (
        not isinstance(request, dict)
        or not set(request) <= REQUEST_PROJECTION_KEYS
        or not isinstance(response, dict)
        or not set(response) <= RESPONSE_PROJECTION_KEYS
        or not _valid_scalar_tree(request)
        or not _valid_scalar_tree(response)
    ):
        return False
    if not isinstance(request.get("status"), str) or request["status"] not in {
        "projected",
        "partially_projected",
        "unavailable",
        "failed",
    }:
        return False
    if not isinstance(response.get("status"), str) or response["status"] not in {
        "projected",
        "partially_projected",
        "unavailable",
        "failed",
    }:
        return False
    if "partial" in response and type(response["partial"]) is not bool:
        return False
    if record["correlation_quality"] == "confirmed" and (
        not record["client_protocol_call_id"]
        or record["client_protocol_call_id"] != record["server_protocol_call_id"]
    ):
        return False
    if record["correlation_quality"] == "inferred_ordinal" and record["server_call_number"] is None:
        return False
    if (
        record["correlation_quality"] == "unmatched_client"
        and record["server_call_number"] is not None
    ):
        return False
    if (
        record["correlation_quality"] == "unmatched_server"
        and record["client_call_number"] is not None
    ):
        return False
    if any(
        not _safe_string(request.get(field), pattern, limit) == request.get(field)
        for field, pattern, limit in (
            ("package", PACKAGE, 100),
            ("function", FUNCTION, 64),
            ("section", PACKAGE, 100),
            ("version", VERSION, 40),
            ("package_version", VERSION, 40),
            ("r_version", VERSION, 40),
            ("bioc_version", VERSION, 40),
        )
        if field in request
    ):
        return False
    if (
        "query_fingerprint" in request
        and request["query_fingerprint"] is not None
        and not FINGERPRINT.fullmatch(request["query_fingerprint"])
    ):
        return False
    if "query_text" in request:
        if record["schema_version"] == "2.0":
            return False
        query_text = request["query_text"]
        if (
            not isinstance(query_text, str)
            or SECRET_TEXT.search(query_text)
            or request.get("query_projection_status") != "projected"
        ):
            return False
        try:
            if len(query_text.encode("utf-8")) > MAX_QUERY_BYTES:
                return False
        except UnicodeError:
            return False
    if "snapshot_present" in request and type(request["snapshot_present"]) is not bool:
        return False
    for field in ("source_urls",):
        if field in response and (
            not isinstance(response[field], list)
            or len(response[field]) > MAX_URLS
            or any(_safe_official_url(url) != url for url in response[field])
        ):
            return False
    for field in ("available_aliases", "closest_aliases", "aliases"):
        if field in response and (
            not isinstance(response[field], list)
            or len(response[field]) > MAX_ALIASES
            or any(_safe_string(alias, FUNCTION, 64) != alias for alias in response[field])
        ):
            return False
    if (
        "next_offset" in response
        and response["next_offset"] is not None
        and (type(response["next_offset"]) is not int or response["next_offset"] < 0)
    ):
        return False
    if record["schema_version"] == "2.0" and response.get("next_offset", 0) is None:
        return False
    return True


def summarize(rows):
    """Keep adoption, response evidence and efficiency as separate metric families."""
    clients = [row for row in rows if row["source"] == "agent_stream"]
    servers = [row for row in rows if row["source"] == "mcp_server"]
    responses = [row["response_projection"] for row in clients]
    known_errors = [item["is_error"] for item in responses if type(item.get("is_error")) is bool]
    verified = [item for item in responses if item.get("verification_status") is not None]
    durations = [row["duration_ms"] for row in clients if row.get("duration_ms") is not None]
    response_bytes = [
        item["response_bytes"] for item in responses if item.get("response_bytes") is not None
    ]
    correlation = {}
    for row in rows:
        key = row["correlation_quality"]
        correlation[key] = correlation.get(key, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "adoption": {"client_calls_observed": len(clients), "server_calls_observed": len(servers)},
        "tool_effectiveness": {
            "client_success_calls": sum(value is False for value in known_errors),
            "client_error_calls": sum(value is True for value in known_errors),
            "client_outcome_observations": len(known_errors),
            "verified_source_calls": sum(
                item.get("verification_status") == "verified" and item.get("source_count", 0) > 0
                for item in verified
            ),
            "verification_status_observations": len(verified),
            "verified_source_rate": (
                sum(
                    item.get("verification_status") == "verified"
                    and item.get("source_count", 0) > 0
                    for item in verified
                )
                / len(verified)
                if verified
                else None
            ),
        },
        "efficiency": {
            "client_call_duration_ms_total": round(sum(durations), 3) if durations else None,
            "duration_observations": len(durations),
            "response_bytes_total": sum(response_bytes) if response_bytes else None,
            "response_bytes_observations": len(response_bytes),
            "result_token_estimate_total": (
                sum((size + 3) // 4 for size in response_bytes) if response_bytes else None
            ),
            "result_token_estimate_method": (
                "ceil(observed serialized response bytes / 4); estimate, not API usage"
            ),
        },
        "correlation_quality": correlation,
    }


def append_jsonl(path, rows):
    """Append bounded validated rows; caller already has projected values only."""
    path = Path(path)
    if not rows:
        return 0
    encoded = []
    for row in rows:
        if not validate_record(row):
            raise ValueError("invalid_projection_record")
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        payload = line.encode("utf-8")
        if len(payload) > MAX_LINE_BYTES:
            raise ValueError("projection_record_too_large")
        encoded.append(payload)
    current_size = path.stat().st_size if path.exists() else 0
    current_records = 0
    if path.exists():
        with path.open("rb") as stream:
            for _ in stream:
                current_records += 1
                if current_records > MAX_RECORDS:
                    break
    if (
        current_size + sum(map(len, encoded)) > MAX_FILE_BYTES
        or current_records + len(encoded) > MAX_RECORDS
    ):
        raise ValueError("projection_file_limit")
    with path.open("ab") as stream:
        for line in encoded:
            stream.write(line)
    return len(encoded)
