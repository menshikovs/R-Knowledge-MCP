"""Reviewed executor URL policy and data-only confidentiality helpers.

No networking, subprocess operations or URL normalization occur here.
"""

import re
from urllib.parse import parse_qsl, unquote, urlsplit

OFFICIAL_EXECUTOR_HOSTS = frozenset({"api.openai.com"})
SENSITIVE_KEY = re.compile(
    r"(?i)(api.?key|access.?token|refresh.?token|authorization|bearer|token|secret|password|"
    r"signature|sig|credential|remote.?url|signed.?url|websocket.?url)"
)
URL_TEXT = re.compile(r"(?i)(?:https?|wss?)://[^\s\"'<>]+")
BEARER_TEXT = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
TOKEN_TEXT = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
ASSIGNED_SECRET = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|"
    r"bearer|secret|password|signature|sig|token|credential|x-amz-security-token)\b"
    r"\s*[:=]\s*)[^\s,;]+"
)
URL_USERINFO = re.compile(r"(?i)https?://[^/@\s]+:[^/@\s]+@")
MAX_SANITIZE_DEPTH = 64
MAX_SANITIZE_NODES = 250_000
MAX_SANITIZE_TEXT = 2 << 20
MAX_SANITIZE_OUTPUT = 64 << 20


class SanitizationError(ValueError):
    """Reference data cannot be represented safely after sanitization."""


class ExecutorURLValidationError(ValueError):
    def __init__(self, reason_code: str):
        super().__init__("Executor remote URL failed reviewed policy")
        self.reason_code = reason_code


def validate_executor_remote_url(value: str) -> str:
    """Return the exact input string or a safe error code, never a parsed URL."""

    def reject(code):
        raise ExecutorURLValidationError(code)

    if not isinstance(value, str) or not value or len(value) > 8192:
        reject("remote_url_missing")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        reject("remote_url_invalid_characters")
    if "#" in value:
        reject("remote_url_fragment_forbidden")
    if "\\" in value or re.search(r"%(?![0-9A-Fa-f]{2})", value):
        reject("remote_url_path_not_permitted")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        reject("remote_url_port_invalid")
    if parsed.scheme.lower() != "https":
        reject("remote_url_scheme_not_https")
    if parsed.hostname not in OFFICIAL_EXECUTOR_HOSTS:
        reject("remote_url_hostname_not_allowlisted")
    if port not in (None, 443):
        reject("remote_url_port_not_permitted")
    if parsed.username is not None or parsed.password is not None:
        reject("remote_url_credentials_forbidden")
    if parsed.netloc.endswith(":"):
        reject("remote_url_port_invalid")
    try:
        query = parse_qsl(parsed.query, keep_blank_values=True, errors="strict")
        decoded = unquote(parsed.path, errors="strict")
        decoded_query = unquote(parsed.query, errors="strict")
    except UnicodeError:
        reject("remote_url_path_not_permitted")
    if any(
        key.casefold()
        in {
            "api_key",
            "apikey",
            "access_token",
            "auth",
            "authorization",
            "bearer",
            "credential",
            "password",
            "secret",
            "sig",
            "signature",
            "token",
        }
        for key, _ in query
    ):
        reject("remote_url_credentials_forbidden")
    # Reject nested escaping rather than allowing a second decoder to reinterpret paths.
    if (
        not (parsed.path == "/v1/agents/api" or parsed.path.startswith("/v1/agents/api/"))
        or any(part in {".", ".."} for part in decoded.split("/"))
        or "%" in decoded
        or any(
            char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F
            for char in decoded + decoded_query
        )
        or "\\" in decoded + decoded_query
    ):
        reject("remote_url_path_not_permitted")
    return value


def _sanitize_text(value, secrets, *, redact_urls):
    if len(value) > MAX_SANITIZE_TEXT:
        raise SanitizationError("Reference text exceeds the sanitizer limit")
    original_length = len(value)
    for secret in secrets:
        value = value.replace(secret, "[REDACTED]")
    if redact_urls:
        value = URL_TEXT.sub("[REDACTED]", value)
    else:
        value = URL_USERINFO.sub("[REDACTED]@", value)
    value = BEARER_TEXT.sub("Bearer [REDACTED]", value)
    value = TOKEN_TEXT.sub("[REDACTED]", value)
    value = ASSIGNED_SECRET.sub(lambda match: match.group(1) + "[REDACTED]", value)
    if len(value) > min(MAX_SANITIZE_TEXT, max(32, original_length * 2)):
        raise SanitizationError("Sanitized reference text exceeds the expansion limit")
    return value


def sanitize_reference_data(value, *, secrets=(), redact_urls=True):
    """Boundedly scrub keys and values; reject unsafe types and key collisions."""
    if not isinstance(secrets, (tuple, list, set, frozenset)):
        raise SanitizationError("Configured secrets must be a bounded sequence")
    secret_set = set()
    try:
        for item in secrets:
            if item is None:
                continue
            if not isinstance(item, str) or len(item) > MAX_SANITIZE_TEXT:
                raise SanitizationError("Configured secret exceeds sanitizer limits")
            if item:
                secret_set.add(item)
                if len(secret_set) > 16:
                    raise SanitizationError("Too many configured secrets for sanitization")
    except TypeError as exc:
        raise SanitizationError("Configured secrets are not safely iterable") from exc
    secret_values = tuple(sorted(secret_set, key=len, reverse=True))
    seen_nodes = 0
    active = set()
    output_size = 0

    def visit(item, depth):
        nonlocal seen_nodes, output_size
        seen_nodes += 1
        if seen_nodes > MAX_SANITIZE_NODES or depth > MAX_SANITIZE_DEPTH:
            raise SanitizationError("Reference structure exceeds sanitizer limits")
        if isinstance(item, str):
            result = _sanitize_text(item, secret_values, redact_urls=redact_urls)
            output_size += len(result.encode("utf-8"))
            if output_size > MAX_SANITIZE_OUTPUT:
                raise SanitizationError("Sanitized reference output exceeds its limit")
            return result
        if isinstance(item, dict):
            identity = id(item)
            if identity in active:
                raise SanitizationError("Cyclic reference structures are forbidden")
            active.add(identity)
            result = {}
            try:
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise SanitizationError("Reference object keys must be strings")
                    safe_key = _sanitize_text(key, secret_values, redact_urls=redact_urls)
                    output_size += len(safe_key.encode("utf-8"))
                    if output_size > MAX_SANITIZE_OUTPUT:
                        raise SanitizationError("Sanitized reference output exceeds its limit")
                    if safe_key in result:
                        raise SanitizationError("Sanitization produced a duplicate object key")
                    if SENSITIVE_KEY.search(key):
                        safe_value = "[REDACTED]"
                    else:
                        safe_value = visit(child, depth + 1)
                    result[safe_key] = safe_value
            finally:
                active.remove(identity)
            return result
        if isinstance(item, list):
            identity = id(item)
            if identity in active:
                raise SanitizationError("Cyclic reference structures are forbidden")
            active.add(identity)
            try:
                return [visit(child, depth + 1) for child in item]
            finally:
                active.remove(identity)
        if item is None or type(item) in {bool, int, float}:
            return item
        raise SanitizationError("Reference value type is not safely representable")

    return visit(value, 0)


RUNTIME_CODES = frozenset(
    {
        "runtime_policy_rejected",
        "remote_url_rejected",
        "cli_nonzero",
        "executable_unavailable",
        "command_os_error",
        "command_timeout",
        "output_limit",
        "invalid_inspection",
        "invalid_container_id",
        "executor_exited",
        "executor_not_running",
        "cleanup_unverified",
        "docker_daemon_unavailable",
        "image_unavailable",
        "mount_or_workspace_failure",
    }
)
RUNTIME_OPERATIONS = frozenset(
    {
        "validate_topology",
        "validate_environment",
        "validate_remote_url",
        "validate_workspace",
        "verify_image",
        "build_container_args",
        "create_container",
        "inspect_policy",
        "inspect_network",
        "inspect_environment",
        "start_container",
        "verify_process",
        "cleanup",
    }
)


def project_runtime_diagnostics(value):
    """Closed vocabulary: arbitrary exception values cannot enter the audit."""

    def choice(name, allowed, default=None):
        item = value.get(name)
        return item if isinstance(item, str) and item in allowed else default

    return {
        "operation": "start_executor",
        "category": "docker_runtime",
        "reason": "Docker executor operation failed",
        "reason_code": choice("reason_code", RUNTIME_CODES, "runtime_policy_rejected"),
        "sub_operation": choice("sub_operation", RUNTIME_OPERATIONS),
        "exception_category": choice(
            "exception_category", {"validation", "subprocess", "timeout", "runtime"}, "runtime"
        ),
        "docker_http_status": None,
        "docker_cli_exit_code": (
            value.get("docker_cli_exit_code")
            if type(value.get("docker_cli_exit_code")) is int
            else None
        ),
        "container_exit_code": (
            value.get("container_exit_code")
            if type(value.get("container_exit_code")) is int
            else None
        ),
        "container_startup_state": choice(
            "container_startup_state", {"created", "running", "exited", "dead"}
        ),
        "timeout_classification": (
            "docker_command_deadline"
            if value.get("timeout_classification") == "docker_command_deadline"
            else None
        ),
        "secondary_cleanup_failure": (
            "cleanup_unverified"
            if value.get("secondary_cleanup_failure") == "cleanup_unverified"
            else None
        ),
    }
