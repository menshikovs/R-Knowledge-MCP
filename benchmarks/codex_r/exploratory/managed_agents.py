"""Strict, non-network-default helpers for the documented Managed Agents API.

No function in this module creates a session unless explicitly called. The
current pilot launch gate stays blocked until the Docker egress path and actual
account/model access are independently verified.
"""

from __future__ import annotations

import json
import re
import ssl
import time
import uuid
from collections.abc import Callable
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx

MAX_API_RESPONSE_BYTES = 1 << 20
MAX_EVENT_BYTES = 1 << 20
MAX_EVENT_COUNT = 10000
MAX_EVENT_LOG_BYTES = 32 << 20
API_ORIGIN = "https://api.openai.com"
OFFICIAL_EXECUTOR_HOSTS = {"api.openai.com"}
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class ManagedAgentsError(RuntimeError):
    """The API response or session environment did not match the pinned protocol."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "managed_agents_error",
        http_status: int | None = None,
        operation: str | None = None,
    ):
        super().__init__(message)
        self.diagnostics = {
            "operation": operation,
            "category": category,
            "http_status": http_status,
            "reason": message,
        }


def build_agent_config(context: dict, *, gateway_url: str | None = None) -> dict:
    """Return the exact session config for a preregistered A/B/C condition."""
    expected = {
        "trial_id",
        "condition",
        "model",
        "reasoning_effort",
        "expected_tools",
    }
    if not isinstance(context, dict) or not expected <= context.keys():
        raise ManagedAgentsError("Trial context does not meet the session contract")
    if context["trial_id"] != "R01-A" or context["condition"] != "A":
        raise ManagedAgentsError("Only R01-A is currently eligible for runtime configuration")
    if context["model"] != "gpt-6-luna" or context["reasoning_effort"] != "medium":
        raise ManagedAgentsError("Model and reasoning must match the fixed pilot protocol")
    if context["expected_tools"] != [] or gateway_url is not None:
        raise ManagedAgentsError("Condition A must have no MCP tools and no gateway route")
    return {
        "agent": {
            "model": "gpt-6-luna",
            "reasoning": {"effort": "medium"},
            "multi_agent": {"enabled": False},
            "tools": [],
        },
        "environment": {"type": "self_hosted", "workspace_directory": "/candidate"},
    }


def _schema_error(reason_code: str, field: str) -> ManagedAgentsError:
    """Build safe schema diagnostics; never include upstream values."""
    error = ManagedAgentsError(
        "Managed Agents session response failed validation",
        category="response_schema_validation",
        operation="create_session",
    )
    error.diagnostics.update(reason_code=reason_code, field=field)
    return error


def validate_environment_record(record: dict) -> dict:
    """Validate the documented self-hosted response without rewriting its URL."""
    if not isinstance(record, dict) or not SESSION_ID.fullmatch(str(record.get("id", ""))):
        raise _schema_error("session_id_invalid", "id")
    environment = record.get("environment")
    if not isinstance(environment, dict) or environment.get("type") != "self_hosted":
        raise _schema_error("environment_type_invalid", "environment.type")
    env_id = environment.get("id")
    if not isinstance(env_id, str) or not SESSION_ID.fullmatch(env_id):
        raise _schema_error("environment_id_invalid", "environment.id")
    remote_url = environment.get("remote_url")
    reason_code = None
    field = "environment.remote_url"
    if not isinstance(remote_url, str) or not remote_url:
        reason_code = "remote_url_missing"
    elif any(ord(char) < 0x20 or ord(char) == 0x7F for char in remote_url):
        reason_code = "remote_url_invalid_characters"
    elif "#" in remote_url:
        reason_code = "remote_url_fragment_forbidden"
    else:
        try:
            parsed = urlsplit(remote_url)
            port = parsed.port
        except ValueError:
            parsed = None
            port = None
            reason_code = "remote_url_port_invalid"
        if parsed is not None and reason_code is None:
            if parsed.scheme.lower() != "https":
                reason_code = "remote_url_scheme_not_https"
            elif parsed.hostname not in OFFICIAL_EXECUTOR_HOSTS:
                reason_code = "remote_url_hostname_not_allowlisted"
            elif port not in (None, 443):
                reason_code = "remote_url_port_not_permitted"
            elif parsed.username is not None or parsed.password is not None:
                reason_code = "remote_url_credentials_forbidden"
            elif any(
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
                for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
            ):
                reason_code = "remote_url_credentials_forbidden"
            elif parsed.fragment:
                reason_code = "remote_url_fragment_forbidden"
            elif parsed.netloc.endswith(":"):
                reason_code = "remote_url_port_invalid"
            else:
                # The API reference models remote_url as an opaque string and
                # instructs clients to pass it unchanged. Keep it on the
                # documented API endpoint namespace while accepting trailing
                # slash/subpath variants that the fixed-path check rejected.
                path = parsed.path
                decoded_path = unquote(path)
                path_parts = decoded_path.split("/")
                if (
                    not path.startswith("/v1/agents/api")
                    or not (path == "/v1/agents/api" or path.startswith("/v1/agents/api/"))
                    or any(part in {".", ".."} for part in path_parts)
                    or "\\" in decoded_path
                    or re.search(r"%(?![0-9A-Fa-f]{2})", path)
                    or any(char.isspace() for char in path)
                ):
                    reason_code = "remote_url_path_not_permitted"
    if reason_code:
        raise _schema_error(reason_code, field)
    return {
        "session_id": record["id"],
        "environment_id": env_id,
        # The returned URL may carry server-issued routing material. Validate
        # its origin/path, then pass the exact string to exec-server unchanged.
        "remote_url": remote_url,
    }


class ManagedAgentsClient:
    """Small HTTPX client for fixed Agents API routes; never logs auth or bodies."""

    def __init__(
        self,
        application_api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15,
    ):
        if not isinstance(application_api_key, str) or not application_api_key.strip():
            raise ManagedAgentsError("A controller-side application key is required")
        if timeout <= 0 or timeout > 30:
            raise ManagedAgentsError("API timeout must be between 0 and 30 seconds")
        self._key = application_api_key
        self._client = httpx.Client(
            base_url=API_ORIGIN,
            headers={
                "Authorization": f"Bearer {application_api_key}",
                "OpenAI-Beta": "agents=v1",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._session_creation_attempted = False
        self.session_creation_attempted = False
        self.session_creation_uncertain = False
        self.session_creation_response_received = False
        self.session_creation_http_status: int | None = None
        self.session_id_for_cleanup: str | None = None
        self.session_deletion_verified: bool | None = None
        self.session_state = "not_created"
        self.task_submission_attempted = False
        self.task_submission_uncertain = False
        self._submitted_sessions: set[str] = set()
        self._last_response_status: int | None = None

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        operation: str | None = None,
    ) -> dict:
        if not path.startswith("/v1/agents/") or ".." in path or "?" in path or "#" in path:
            raise ManagedAgentsError("Refused a non-protocol API route")
        self._last_response_status = None
        try:
            with self._client.stream(method, path, json=body, headers=headers) as response:
                self._last_response_status = response.status_code
                if response.is_redirect:
                    raise ManagedAgentsError(
                        "Managed Agents API redirects are not accepted",
                        category="http_rejection",
                        http_status=response.status_code,
                        operation=operation,
                    )
                if not response.is_success:
                    raise ManagedAgentsError(
                        f"Managed Agents API rejected the request with HTTP {response.status_code}",
                        category="http_rejection",
                        http_status=response.status_code,
                        operation=operation,
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > MAX_API_RESPONSE_BYTES:
                        raise ManagedAgentsError(
                            "Managed Agents API response exceeded the size limit",
                            category="response_limit",
                            http_status=response.status_code,
                            operation=operation,
                        )
                    content.extend(chunk)
        except ManagedAgentsError:
            raise
        except httpx.HTTPError as exc:
            cause = exc
            tls_error = False
            while cause is not None:
                if isinstance(cause, ssl.SSLError):
                    tls_error = True
                    break
                cause = cause.__cause__
            raise ManagedAgentsError(
                "Managed Agents API TLS connection failed"
                if tls_error
                else "Managed Agents API transport failed",
                category="tls_error" if tls_error else "network_error",
                operation=operation,
            ) from exc
        try:
            value = json.loads(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ManagedAgentsError(
                "Managed Agents API returned invalid JSON",
                category="invalid_json",
                http_status=self._last_response_status,
                operation=operation,
            ) from exc
        if not isinstance(value, dict):
            raise ManagedAgentsError(
                "Managed Agents API returned a non-object JSON value",
                category="response_schema_validation",
                http_status=self._last_response_status,
                operation=operation,
            )
        return value

    def create_session(self, context: dict, *, gateway_url: str | None = None) -> dict:
        if self._session_creation_attempted:
            raise ManagedAgentsError("This client is restricted to one session creation attempt")
        config = build_agent_config(context, gateway_url=gateway_url)
        self._session_creation_attempted = True
        self.session_creation_attempted = True
        self.session_creation_uncertain = True
        # No initial input: the session executor must be connected before a turn starts.
        try:
            record = self._request_json(
                "POST", "/v1/agents/sessions", body=config, operation="create_session"
            )
        except ManagedAgentsError:
            status = self._last_response_status
            if status is not None and 200 <= status < 300:
                self.session_creation_response_received = True
                self.session_creation_http_status = status
            self.session_state = "unknown" if self.session_creation_uncertain else "not_created"
            raise
        self.session_creation_response_received = True
        self.session_creation_http_status = self._last_response_status
        self.session_state = "created_unvalidated"
        session_id = record.get("id") if isinstance(record, dict) else None
        if isinstance(session_id, str) and SESSION_ID.fullmatch(session_id):
            self.session_id_for_cleanup = session_id
        try:
            checked = validate_environment_record(record)
            agent = record.get("agent")
            if not isinstance(agent, dict) or agent.get("model") != "gpt-6-luna":
                raise ManagedAgentsError(
                    "Resolved session model differs from the fixed pilot model"
                )
            reasoning = agent.get("reasoning")
            if not isinstance(reasoning, dict) or reasoning.get("effort") != "medium":
                raise ManagedAgentsError("Resolved session reasoning differs from the fixed effort")
            if agent.get("tools") != []:
                raise ManagedAgentsError(
                    "Effective session tools are not verified as empty for R01-A"
                )
        except ManagedAgentsError as exc:
            exc.diagnostics.update(
                operation="create_session",
                http_status=exc.diagnostics.get("http_status") or self._last_response_status,
                category=(
                    exc.diagnostics.get("category")
                    if exc.diagnostics.get("category") != "managed_agents_error"
                    else "response_schema_validation"
                ),
            )
            exc.diagnostics.setdefault(
                "session_state", "created_unaddressable" if session_id is None else "created"
            )
            if isinstance(session_id, str) and SESSION_ID.fullmatch(session_id):
                try:
                    self.delete_session(session_id)
                except ManagedAgentsError as cleanup_error:
                    self.session_deletion_verified = False
                    self.session_state = "unknown"
                    exc.diagnostics.update(
                        session_deleted_verified=False,
                        session_state="unknown",
                        cleanup_reason_code="session_delete_not_confirmed",
                    )
                    raise exc from cleanup_error
                self.session_deletion_verified = True
                self.session_creation_uncertain = False
                self.session_state = "deleted"
                exc.diagnostics.update(
                    session_deleted_verified=True,
                    session_state="deleted_after_validation_failure",
                )
            else:
                self.session_deletion_verified = None
                self.session_state = "unknown"
                exc.diagnostics.update(
                    session_deleted_verified=None,
                    session_state="unknown",
                    cleanup_reason_code="session_id_unavailable",
                )
            raise exc
        self.session_creation_uncertain = False
        self.session_state = "created"
        checked["resolved_agent"] = {
            "model": agent["model"],
            "reasoning_effort": reasoning["effort"],
            "tools": [],
            "verified_from_session_response": True,
        }
        return checked

    def submit_task(
        self, session_id: str, task: str, *, idempotency_key: str | None = None
    ) -> dict:
        if not SESSION_ID.fullmatch(session_id) or not isinstance(task, str) or not task.strip():
            raise ManagedAgentsError("Session or task input is invalid")
        if session_id in self._submitted_sessions:
            raise ManagedAgentsError("A task submission was already attempted for this session")
        if len(task.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ManagedAgentsError("Task input exceeded the event size limit")
        key = idempotency_key or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
            raise ManagedAgentsError("Idempotency key is invalid")
        self._submitted_sessions.add(session_id)
        self.task_submission_attempted = True
        self.task_submission_uncertain = True
        result = self._request_json(
            "POST",
            f"/v1/agents/sessions/{session_id}/events",
            headers={"Idempotency-Key": key},
            body={
                "events": [
                    {
                        "type": "agent.session.input.message",
                        "input": [
                            {
                                "role": "user",
                                "content": [{"type": "input_text", "text": task}],
                            }
                        ],
                    }
                ]
            },
        )
        self.task_submission_uncertain = False
        return result

    def send_and_stream(
        self,
        session_id: str,
        task: str,
        *,
        deadline_seconds: float = 900,
        idempotency_key: str | None = None,
        on_stream_ready: Callable[[], None] | None = None,
        on_environment_connected: Callable[[], None] | None = None,
        on_task_submitted: Callable[[], None] | None = None,
    ):
        """Subscribe before task submission and yield bounded, sanitized SSE events."""
        if not SESSION_ID.fullmatch(session_id) or not isinstance(task, str) or not task.strip():
            raise ManagedAgentsError("Session or task input is invalid")
        if not 0 < deadline_seconds <= 900:
            raise ManagedAgentsError("Managed Agents turn deadline must be at most 900 seconds")
        if len(task.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ManagedAgentsError("Task input exceeded the event size limit")
        key = idempotency_key or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
            raise ManagedAgentsError("Idempotency key is invalid")
        path = f"/v1/agents/sessions/{session_id}/events"
        deadline = time.monotonic() + deadline_seconds
        seen = 0
        logged_bytes = 0
        pending: list[str] = []
        pending_bytes = 0
        terminal = False
        try:
            with self._client.stream(
                "GET",
                path,
                params={"stream": "true"},
                headers={"Accept": "text/event-stream"},
                timeout=httpx.Timeout(
                    connect=15,
                    read=deadline_seconds,
                    write=15,
                    pool=15,
                ),
            ) as stream:
                if stream.is_redirect:
                    raise ManagedAgentsError("Managed Agents event stream redirected")
                if not stream.is_success:
                    raise ManagedAgentsError(
                        f"Managed Agents event stream returned HTTP {stream.status_code}"
                    )
                if "text/event-stream" not in stream.headers.get("content-type", "").lower():
                    raise ManagedAgentsError("Managed Agents returned a non-SSE event stream")
                if on_stream_ready is not None:
                    on_stream_ready()
                submitted = False
                for line in stream.iter_lines():
                    if time.monotonic() > deadline:
                        raise ManagedAgentsError("Managed Agents turn exceeded its deadline")
                    if line.startswith("data:"):
                        data = line[5:].lstrip()
                        pending.append(data)
                        byte_count = len(data.encode("utf-8"))
                        pending_bytes += byte_count
                        logged_bytes += byte_count
                        if pending_bytes > MAX_EVENT_BYTES or logged_bytes > MAX_EVENT_LOG_BYTES:
                            raise ManagedAgentsError("Managed Agents event stream exceeded limits")
                    elif not line and pending:
                        data = "\n".join(pending)
                        pending.clear()
                        pending_bytes = 0
                        if data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError as exc:
                            raise ManagedAgentsError(
                                "Managed Agents emitted invalid SSE JSON"
                            ) from exc
                        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                            raise ManagedAgentsError(
                                "Managed Agents emitted an invalid event object"
                            )
                        seen += 1
                        if seen > MAX_EVENT_COUNT:
                            raise ManagedAgentsError(
                                "Managed Agents event count exceeded its limit"
                            )
                        event = self._sanitize_event(event)
                        yield event
                        if event["type"] == "agent.session.environment.connected" and not submitted:
                            if on_environment_connected is not None:
                                on_environment_connected()
                            self.submit_task(session_id, task, idempotency_key=key)
                            submitted = True
                            if on_task_submitted is not None:
                                on_task_submitted()
                        if (
                            event["type"]
                            in {
                                "agent.session.environment.failed",
                                "agent.session.failed",
                                "error",
                            }
                            and not submitted
                        ):
                            terminal = True
                            raise ManagedAgentsError(
                                "Managed Agents environment failed before executor readiness"
                            )
                        if event["type"] in {
                            "agent.session.turn.completed",
                            "agent.session.turn.failed",
                            "agent.session.turn.cancelled",
                            "agent.session.failed",
                            "agent.session.environment.failed",
                            "error",
                        }:
                            terminal = True
                            return
                if pending:
                    raise ManagedAgentsError("Managed Agents stream ended mid-event")
        except httpx.HTTPError as exc:
            raise ManagedAgentsError("Managed Agents event stream failed") from exc
        if not terminal:
            raise ManagedAgentsError("Managed Agents stream closed before a terminal event")
        if not submitted:
            raise ManagedAgentsError("Executor did not connect before the task deadline")

    def _sanitize_event(self, event: dict) -> dict:
        def visit(value, key=""):
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if any(
                marker in normalized
                for marker in (
                    "apikey",
                    "authorization",
                    "token",
                    "secret",
                    "password",
                    "remoteurl",
                    "websocketurl",
                    "signedurl",
                )
            ):
                return "[REDACTED]"
            if isinstance(value, dict):
                return {str(k): visit(v, str(k)) for k, v in value.items()}
            if isinstance(value, list):
                return [visit(item, key) for item in value]
            if isinstance(value, str):
                return value.replace(self._key, "[REDACTED]")
            return value

        return visit(event)

    def cancel_turn(self, session_id: str) -> dict:
        if not SESSION_ID.fullmatch(session_id):
            raise ManagedAgentsError("Session identity is invalid")
        return self._request_json(
            "POST",
            f"/v1/agents/sessions/{session_id}/events",
            body={"events": [{"type": "agent.session.input.cancel"}]},
        )

    def delete_session(self, session_id: str) -> dict:
        if not SESSION_ID.fullmatch(session_id):
            raise ManagedAgentsError("Session identity is invalid")
        result = self._request_json("DELETE", f"/v1/agents/sessions/{session_id}")
        if result.get("id") != session_id or result.get("deleted") is not True:
            raise ManagedAgentsError("Managed Agents session deletion was not confirmed")
        return result

    def close(self) -> None:
        self._client.close()
