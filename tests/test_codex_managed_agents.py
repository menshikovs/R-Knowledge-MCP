import importlib.util
import json
import ssl
from pathlib import Path

import httpx
import pytest

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
    assert build_agent_config(context()) == {
        "agent": {
            "model": "gpt-6-luna",
            "reasoning": {"effort": "medium"},
            "multi_agent": {"enabled": False},
            "tools": [],
        },
        "environment": {"type": "self_hosted", "workspace_directory": "/candidate"},
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
        build_agent_config(context(**changes))


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
        environment = client.create_session(context())
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
        client.create_session(context())
        with pytest.raises(ManagedAgentsError, match="one session creation attempt"):
            client.create_session(context())
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
        with pytest.raises(ManagedAgentsError, match="Resolved session model"):
            client.create_session(context())
        assert client.session_creation_uncertain is False
        assert requests == [
            ("POST", "/v1/agents/sessions"),
            ("DELETE", "/v1/agents/sessions/sess_test123"),
        ]
    finally:
        client.close()


def test_ambiguous_session_creation_failure_is_marked_uncertain_without_retry():
    client = ManagedAgentsClient(
        "synthetic-app-secret",
        transport=httpx.MockTransport(lambda _request: httpx.Response(502)),
    )
    try:
        with pytest.raises(ManagedAgentsError):
            client.create_session(context())
        assert client.session_creation_uncertain is True
        with pytest.raises(ManagedAgentsError, match="one session creation attempt"):
            client.create_session(context())
    finally:
        client.close()


@pytest.mark.parametrize("status", [400, 401, 403, 404])
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
            client.create_session(context())
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
            client.create_session(context())
        assert raised.value.diagnostics["category"] == "network_error"
        assert raised.value.diagnostics["http_status"] is None
        assert "synthetic-secret" not in str(raised.value)
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
            client.create_session(context())
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
            client.create_session(context())
        assert raised.value.diagnostics["operation"] == "create_session"
        assert raised.value.diagnostics["category"] == category
        assert raised.value.diagnostics["http_status"] == 200
    finally:
        client.close()


@pytest.mark.parametrize(
    "remote_url",
    [
        "http://api.openai.com/v1/agents/api",
        "https://evil.example/v1/agents/api",
        "https://api.openai.com.attacker.example/v1/agents/api",
        "https://user:pass@api.openai.com/v1/agents/api",
    ],
)
def test_executor_remote_url_cannot_select_an_arbitrary_host(remote_url):
    with pytest.raises(ManagedAgentsError):
        validate_environment_record(session_record(remote_url))


def test_executor_remote_url_is_passed_through_without_rewriting():
    signed = "https://api.openai.com/v1/agents/api?route=opaque-server-token"
    assert validate_environment_record(session_record(signed))["remote_url"] == signed


def test_managed_agents_reject_redirects_and_oversized_responses():
    redirect = httpx.MockTransport(
        lambda request: httpx.Response(307, headers={"Location": "https://evil.example"})
    )
    client = ManagedAgentsClient("synthetic-app-secret", transport=redirect)
    with pytest.raises(ManagedAgentsError, match="redirects"):
        client.create_session(context())
    client.close()

    oversized = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * (MAX_API_RESPONSE_BYTES + 1))
    )
    client = ManagedAgentsClient("synthetic-app-secret", transport=oversized)
    with pytest.raises(ManagedAgentsError, match="size limit"):
        client.create_session(context())
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
