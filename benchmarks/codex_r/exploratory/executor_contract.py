"""Reviewed executor URL policy and data-only confidentiality helpers.

No networking, subprocess operations or URL normalization occur here.
"""

import re
from urllib.parse import parse_qsl, unquote, urlsplit

OFFICIAL_EXECUTOR_HOSTS = frozenset({"api.openai.com"})
SENSITIVE_KEY = re.compile(
    r"(?i)(api.?key|access.?token|refresh.?token|authorization|token|secret|password|"
    r"remote.?url|signed.?url|websocket.?url)"
)
URL_TEXT = re.compile(r"(?i)(?:https?|wss?)://[^\s\"'<>]+")


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


def sanitize_reference_data(value, *, secrets=()):
    """Scrub known exact secrets and URLs even inside ordinary nested output text."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if SENSITIVE_KEY.search(str(key))
            else sanitize_reference_data(item, secrets=secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_reference_data(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        for secret in sorted(
            (s for s in secrets if isinstance(s, str) and s), key=len, reverse=True
        ):
            value = value.replace(secret, "[REDACTED]")
        return URL_TEXT.sub("[REDACTED]", value)
    return value


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
