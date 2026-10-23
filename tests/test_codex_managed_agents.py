import json

import httpx
import pytest

from benchmarks.codex_r.exploratory.managed_agents import (
    MAX_API_RESPONSE_BYTES,
    ManagedAgentsClient,
    ManagedAgentsError,
    build_agent_config,
    validate_environment_record,
)


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
        "agent": {"model": "gpt-6-luna", "reasoning": {"effort": "medium"}},
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


@pytest.mark.parametrize(
    "remote_url",
    [
        "http://api.openai.com/v1/agents/api",
        "https://evil.example/v1/agents/api",
        "https://api.openai.com.attacker.example/v1/agents/api",
        "https://api.openai.com/v1/agents/api?redirect=https://evil.example",
        "https://user:pass@api.openai.com/v1/agents/api",
    ],
)
def test_executor_remote_url_cannot_select_an_arbitrary_host(remote_url):
    with pytest.raises(ManagedAgentsError):
        validate_environment_record(session_record(remote_url))


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
        "type": "agent.session.turn.completed",
        "turn": {"subagent_id": None},
        "access_token": "synthetic-app-secret",
        "output_text": "redact synthetic-app-secret from this fixture",
    }

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=("data: " + json.dumps(payload) + "\n\n").encode(),
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
    assert events[0]["type"] == "agent.session.turn.completed"
    assert events[0]["access_token"] == "[REDACTED]"
    assert "synthetic-app-secret" not in json.dumps(events)
