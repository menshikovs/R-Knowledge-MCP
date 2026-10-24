import importlib.util
import json
import ssl
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("r01a_offline_guard")

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "codex_managed_agents", ROOT / "benchmarks/codex_r/exploratory/managed_agents.py"
)
assert SPEC is not None and SPEC.loader is not None
managed_agents = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(managed_agents)

MAX_API_RESPONSE_BYTES = managed_agents.MAX_API_RESPONSE_BYTES
ManagedAgentsClient = managed_agents.ManagedAgentsClient
ManagedAgentsError = managed_agents.ManagedAgentsError
build_agent_config = managed_agents.build_agent_config
validate_environment_record = managed_agents.validate_environment_record


def context(**overrides):
    value = {
        "trial_id": "R01-A",
        "condition": "A",
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "expected_tools": [],
    }
    value.update(overrides)
    return value


def session_record(remote_url="https://api.openai.com/v1/agents/api"):
    return {
        "id": "sess_test123",
        "agent": {
            "model": "gpt-6-luna",
            "reasoning": {"effort": "medium"},
            "tools": [],
        },
        "environment": {
            "id": "env_test123",
            "type": "self_hosted",
            "remote_url": remote_url,
        },
    }


def test_condition_a_session_config_is_exact_model_medium_and_zero_mcp():
    assert build_agent_config(context(), spend_control_limit_cents=275) == {
        "agent": {
            "model": "gpt-6-luna",
            "reasoning": {"effort": "medium"},
            "multi_agent": {"enabled": False},
            "tools": [],
        },
        "environment": {"type": "self_hosted", "workspace_directory": "/candidate"},
        "spend_control": {"limit": 275},
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"trial_id": "R01-B", "condition": "B"},
        {"condition": "C"},
        {"model": "gpt-6-astra"},
        {"reasoning_effort": "high"},
        {"expected_tools": ["search_packages"]},
    ],
)
def test_unimplemented_rows_and_model_settings_are_rejected(changes):
    with pytest.raises(ManagedAgentsError):
        build_agent_config(context(**changes), spend_control_limit_cents=275)


@pytest.mark.parametrize("limit", [None, 0, -1, 1.5, True, "275", float("nan"), float("inf")])
def test_invalid_session_spend_limits_are_rejected_before_transport(limit):
    requests = []
    client = ManagedAgentsClient(
        "synthetic-app-secret",
        transport=httpx.MockTransport(lambda request: requests.append(request)),
    )
    try:
        with pytest.raises(ManagedAgentsError, match="spend_control.limit"):
            client.create_session(context(), spend_control_limit_cents=limit)
        assert requests == []
        assert client.session_creation_attempted is False
    finally:
        client.close()


def test_missing_spend_limit_is_rejected_before_transport():
    requests = []
    client = ManagedAgentsClient(
        "synthetic-app-secret",
        transport=httpx.MockTransport(lambda request: requests.append(request)),
    )
    try:
        with pytest.raises(ManagedAgentsError, match="spend_control.limit"):
            client.create_session(context())
        assert requests == []
    finally:
        client.close()


@pytest.mark.parametrize("method", ["POST", "post", "pOsT"])
def test_raw_session_route_cannot_bypass_spend_limit_validation(method):
    requests = []
    client = ManagedAgentsClient(
        "synthetic-app-secret",
        transport=httpx.MockTransport(lambda request: requests.append(request)),
    )
    try:
        with pytest.raises(ManagedAgentsError, match="approved spend_control.limit"):
            client._request_json(method, "/v1/agents/sessions", body={"agent": {}})
        assert requests == []
    finally:
        client.close()


def test_managed_agents_mock_uses_fixed_routes_and_keeps_app_key_controller_side():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-app-secret"
        if request.method == "POST" and request.url.path == "/v1/agents/sessions":
            body = json.loads(request.content)
            assert body["agent"]["model"] == "gpt-6-luna"
            assert body["agent"]["reasoning"]["effort"] == "medium"
            assert body["agent"]["tools"] == []
            assert body["spend_control"] == {"limit": 275}
            assert "input" not in body  # no turn starts before executor readiness
            assert "OPENAI_API_KEY" not in request.content.decode()
            return httpx.Response(201, json=session_record())
        if request.method == "POST" and request.url.path.endswith("/events"):
            return httpx.Response(202, json={"accepted": True})
        if request.method == "DELETE":
            return httpx.Response(
                200, json={"id": "sess_test123", "deleted": True, "object": "agent.session.deleted"}
            )
        raise AssertionError(f"unexpected API route: {request.method} {request.url}")

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(handler))
    try:
        environment = client.create_session(context(), spend_control_limit_cents=275)
        assert environment == {
            "session_id": "sess_test123",
            "environment_id": "env_test123",
            "remote_url": "https://api.openai.com/v1/agents/api",
            "resolved_agent": {
                "model": "gpt-6-luna",
                "reasoning_effort": "medium",
                "tools": [],
                "verified_from_session_response": True,
            },
        }
        assert client.submit_task("sess_test123", "offline synthetic fixture task") == {
            "accepted": True
        }
        assert client.cancel_turn("sess_test123") == {"accepted": True}
        assert client.delete_session("sess_test123")["deleted"] is True
    finally:
        client.close()
    assert [request.url.path for request in requests] == [
        "/v1/agents/sessions",
        "/v1/agents/sessions/sess_test123/events",
        "/v1/agents/sessions/sess_test123/events",
        "/v1/agents/sessions/sess_test123",
    ]
    assert all(request.url.host == "api.openai.com" for request in requests)


def test_client_is_limited_to_one_session_and_one_task_submission():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST" and request.url.path == "/v1/agents/sessions":
            return httpx.Response(201, json=session_record())
        if request.method == "POST" and request.url.path.endswith("/events"):
            return httpx.Response(202, json={"accepted": True})
        raise AssertionError(f"unexpected request {request.method} {request.url.path}")

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(handler))
    try:
        client.create_session(context(), spend_control_limit_cents=275)
        with pytest.raises(ManagedAgentsError, match="one session creation attempt"):
            client.create_session(context(), spend_control_limit_cents=275)
        client.submit_task("sess_test123", "synthetic task", idempotency_key="one-task-key-12345")
        with pytest.raises(ManagedAgentsError, match="already attempted"):
            client.submit_task(
                "sess_test123", "must not be retried", idempotency_key="second-task-key-1234"
            )
    finally:
        client.close()
    assert [request.method for request in requests] == ["POST", "POST"]


def test_invalid_created_session_is_deleted_before_any_task_can_be_submitted():
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/v1/agents/sessions":
            record = session_record()
            record["agent"]["model"] = "other-model"
            return httpx.Response(201, json=record)
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "sess_test123", "deleted": True})
        raise AssertionError("unexpected task or API request")

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ManagedAgentsError, match="Resolved session model") as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert client.session_creation_uncertain is False
        assert client.session_creation_response_received is True
        assert client.session_deletion_verified is True
        assert client.session_state == "deleted"
        assert raised.value.diagnostics["session_deleted_verified"] is True
        assert requests == [
            ("POST", "/v1/agents/sessions"),
            ("DELETE", "/v1/agents/sessions/sess_test123"),
        ]
    finally:
        client.close()


def test_created_session_with_invalid_url_is_deleted_and_failure_is_redacted():
    requests = []

    def handler(request):
        requests.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                201,
                json=session_record("https://attacker.invalid/route?signature=must-not-log"),
            )
        return httpx.Response(200, json={"id": "sess_test123", "deleted": True})

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ManagedAgentsError) as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert requests == ["POST", "DELETE"]
        assert client.session_creation_http_status == 201
        assert client.session_deletion_verified is True
        assert client.session_state == "deleted"
        assert raised.value.diagnostics["http_status"] == 201
        assert raised.value.diagnostics["reason_code"] == "remote_url_hostname_not_allowlisted"
        assert raised.value.diagnostics["session_deleted_verified"] is True
        assert "attacker.invalid" not in str(raised.value.diagnostics)
        assert "must-not-log" not in str(raised.value.diagnostics)
    finally:
        client.close()


def test_created_session_with_invalid_url_and_unconfirmed_delete_is_unknown():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(201, json=session_record("https://evil.invalid/route"))
        return httpx.Response(503, json={"error": "private body"})

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ManagedAgentsError) as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert client.session_deletion_verified is False
        assert client.session_creation_uncertain is True
        assert client.session_state == "unknown"
        assert raised.value.diagnostics["session_deleted_verified"] is False
        assert raised.value.diagnostics["session_state"] == "unknown"
        assert "private body" not in str(raised.value.diagnostics)
    finally:
        client.close()


def test_created_session_without_usable_id_keeps_deletion_state_unknown():
    response = session_record()
    response["id"] = "invalid session id"
    client = ManagedAgentsClient(
        "synthetic-app-secret",
        transport=httpx.MockTransport(lambda _request: httpx.Response(201, json=response)),
    )
    try:
        with pytest.raises(ManagedAgentsError) as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert client.session_creation_response_received is True
        assert client.session_state == "unknown"
        assert client.session_deletion_verified is None
        assert raised.value.diagnostics["session_deleted_verified"] is None
        assert raised.value.diagnostics["cleanup_reason_code"] == "session_id_unavailable"
    finally:
        client.close()


def test_ambiguous_session_creation_failure_is_marked_uncertain_without_retry():
    client = ManagedAgentsClient(
        "synthetic-app-secret",
        transport=httpx.MockTransport(lambda _request: httpx.Response(502)),
    )
    try:
        with pytest.raises(ManagedAgentsError):
            client.create_session(context(), spend_control_limit_cents=275)
        assert client.session_creation_uncertain is True
        with pytest.raises(ManagedAgentsError, match="one session creation attempt"):
            client.create_session(context(), spend_control_limit_cents=275)
    finally:
        client.close()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
def test_session_creation_http_rejection_has_safe_structured_diagnostics(status):
    def handler(request):
        return httpx.Response(
            status,
            json={"error": "synthetic body must not be logged", "api_key": "secret-value"},
            request=request,
        )

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ManagedAgentsError) as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert raised.value.diagnostics == {
            "operation": "create_session",
            "category": "http_rejection",
            "http_status": status,
            "reason": f"Managed Agents API rejected the request with HTTP {status}",
        }
        assert "synthetic body" not in str(raised.value)
        assert client.session_creation_attempted is True
        assert client.session_creation_uncertain is True
    finally:
        client.close()


def test_transport_and_tls_failures_have_distinct_safe_diagnostics():
    def network_failure(request):
        raise httpx.ConnectError("Authorization: Bearer synthetic-secret", request=request)

    client = ManagedAgentsClient(
        "synthetic-app-secret", transport=httpx.MockTransport(network_failure)
    )
    try:
        with pytest.raises(ManagedAgentsError) as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert raised.value.diagnostics["category"] == "network_error"
        assert raised.value.diagnostics["http_status"] is None
        assert "synthetic-secret" not in str(raised.value)
    finally:
        client.close()


def test_partial_success_response_is_uncertain_and_never_retried():
    requests = []

    class PartialResponse(httpx.SyncByteStream):
        def __init__(self, request):
            self.request = request

        def __iter__(self):
            yield b'{"id":"sess_synthetic",'
            raise httpx.ReadError("synthetic response tail secret", request=self.request)

        def close(self):
            return None

    def handler(request):
        requests.append(request)
        return httpx.Response(201, stream=PartialResponse(request))

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ManagedAgentsError) as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert raised.value.diagnostics["category"] == "network_error"
        assert raised.value.diagnostics["http_status"] is None
        assert "response tail secret" not in str(raised.value)
        assert client.session_creation_response_received is True
        assert client.session_creation_http_status == 201
        assert client.session_creation_uncertain is True
        assert client.session_state == "unknown"
        assert len(requests) == 1
        with pytest.raises(ManagedAgentsError, match="one session creation attempt"):
            client.create_session(context(), spend_control_limit_cents=275)
        assert len(requests) == 1
    finally:
        client.close()

    def tls_failure(request):
        try:
            raise ssl.SSLError("synthetic certificate detail")
        except ssl.SSLError as cause:
            raise httpx.ConnectError("TLS transport failed", request=request) from cause

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(tls_failure))
    try:
        with pytest.raises(ManagedAgentsError) as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert raised.value.diagnostics["category"] == "tls_error"
        assert "certificate detail" not in str(raised.value)
    finally:
        client.close()


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (httpx.Response(200, content=b"not-json"), "invalid_json"),
        (httpx.Response(200, json=["not", "an object"]), "response_schema_validation"),
        (httpx.Response(200, json={"id": "invalid-schema"}), "response_schema_validation"),
    ],
)
def test_session_creation_payload_failures_have_safe_diagnostics(response, category):
    def handler(request):
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "invalid-schema", "deleted": True})
        return response

    client = ManagedAgentsClient(
        "synthetic-app-secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ManagedAgentsError) as raised:
            client.create_session(context(), spend_control_limit_cents=275)
        assert raised.value.diagnostics["operation"] == "create_session"
        assert raised.value.diagnostics["category"] == category
        assert raised.value.diagnostics["http_status"] == 200
    finally:
        client.close()


@pytest.mark.parametrize(
    ("remote_url", "reason_code"),
    [
        ("http://api.openai.com/v1/agents/api", "remote_url_scheme_not_https"),
        ("https://evil.example/v1/agents/api", "remote_url_hostname_not_allowlisted"),
        (
            "https://api.openai.com.attacker.example/v1/agents/api",
            "remote_url_hostname_not_allowlisted",
        ),
        (
            "https://user:pass@api.openai.com/v1/agents/api",
            "remote_url_credentials_forbidden",
        ),
        (
            "https://api.openai.com/v1/agents/api?access_token=secret",
            "remote_url_credentials_forbidden",
        ),
        ("https://api.openai.com:444/v1/agents/api", "remote_url_port_not_permitted"),
        ("https://api.openai.com/v1/other", "remote_url_path_not_permitted"),
        ("https://api.openai.com/v1/agents/api#", "remote_url_fragment_forbidden"),
        (
            "https://api.openai.com/v1/agents/api/%2e%2e/private",
            "remote_url_path_not_permitted",
        ),
    ],
)
def test_executor_remote_url_rejections_have_safe_component_diagnostics(remote_url, reason_code):
    with pytest.raises(ManagedAgentsError) as raised:
        validate_environment_record(session_record(remote_url))
    assert raised.value.diagnostics["reason_code"] == reason_code
    assert raised.value.diagnostics["field"] == "environment.remote_url"
    assert remote_url not in str(raised.value.diagnostics)


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://api.openai.com/v1/agents/api",
        "https://api.openai.com:443/v1/agents/api/",
        "https://api.openai.com/v1/agents/api/connect/session",
        "https://api.openai.com/v1/agents/api?route=opaque-server-token",
    ],
)
def test_documented_executor_url_variants_are_passed_through_exactly(remote_url):
    assert validate_environment_record(session_record(remote_url))["remote_url"] == remote_url


@pytest.mark.parametrize(
    ("record_change", "reason_code", "field"),
    [
        ({"id": "invalid session"}, "session_id_invalid", "id"),
        (
            {"environment": {"id": "env_test123", "type": "openai_hosted"}},
            "environment_type_invalid",
            "environment.type",
        ),
        (
            {
                "environment": {
                    "id": "invalid env",
                    "type": "self_hosted",
                    "remote_url": "https://api.openai.com/v1/agents/api",
                }
            },
            "environment_id_invalid",
            "environment.id",
        ),
    ],
)
def test_session_and_environment_identity_validation_is_specific(record_change, reason_code, field):
    record = session_record()
    record.update(record_change)
    with pytest.raises(ManagedAgentsError) as raised:
        validate_environment_record(record)
    assert raised.value.diagnostics["reason_code"] == reason_code
    assert raised.value.diagnostics["field"] == field


def test_managed_agents_reject_redirects_and_oversized_responses():
    redirect = httpx.MockTransport(
        lambda request: httpx.Response(307, headers={"Location": "https://evil.example"})
    )
    client = ManagedAgentsClient("synthetic-app-secret", transport=redirect)
    with pytest.raises(ManagedAgentsError, match="redirects"):
        client.create_session(context(), spend_control_limit_cents=275)
    client.close()

    oversized = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * (MAX_API_RESPONSE_BYTES + 1))
    )
    client = ManagedAgentsClient("synthetic-app-secret", transport=oversized)
    with pytest.raises(ManagedAgentsError, match="size limit"):
        client.create_session(context(), spend_control_limit_cents=275)
    client.close()


def test_sse_subscription_precedes_submission_and_redacts_credentials():
    requests = []
    payload = {
        "type": "agent.session.environment.connected",
        "remote_url": "https://api.openai.com/v1/agents/api?secret=signed-value",
    }
    completed = {
        "type": "agent.session.turn.completed",
        "turn": {
            "subagent_id": None,
            "usage": {"input_tokens": 12, "output_tokens": 4},
        },
        "access_token": "synthetic-app-secret",
        "output_text": "redact synthetic-app-secret from this fixture",
    }

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    "data: " + json.dumps(payload) + "\n\ndata: " + json.dumps(completed) + "\n\n"
                ).encode(),
            )
        assert request.method == "POST"
        assert request.headers["idempotency-key"] == "trial-message-key-0001"
        assert json.loads(request.content)["events"][0]["type"] == "agent.session.input.message"
        return httpx.Response(202, json={"accepted": True})

    client = ManagedAgentsClient("synthetic-app-secret", transport=httpx.MockTransport(handler))
    try:
        events = list(
            client.send_and_stream(
                "sess_test123",
                "synthetic task",
                idempotency_key="trial-message-key-0001",
            )
        )
    finally:
        client.close()
    assert [request.method for request in requests] == ["GET", "POST"]
    assert dict(requests[0].url.params) == {"stream": "true"}
    assert events[0]["type"] == "agent.session.environment.connected"
    assert events[0]["remote_url"] == "[REDACTED]"
    assert events[1]["type"] == "agent.session.turn.completed"
    assert events[1]["access_token"] == "[REDACTED]"
    assert "synthetic-app-secret" not in json.dumps(events)
    assert "signed-value" not in json.dumps(events)
