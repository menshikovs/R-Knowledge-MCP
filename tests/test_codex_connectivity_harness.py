"""Synthetic-only regressions for the zero-task connectivity harness."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "codex_connectivity_harness",
    ROOT / "benchmarks/codex_r/exploratory/connectivity_harness.py",
)
assert SPEC is not None and SPEC.loader is not None
harness_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness_module)

ConnectivityError = harness_module.ConnectivityError
ConnectivityHarness = harness_module.ConnectivityHarness
StagingAgentsClient = harness_module.StagingAgentsClient
StagingJournal = harness_module.StagingJournal
StagingLease = harness_module.StagingLease
DockerExecutorAdapter = harness_module.DockerExecutorAdapter
SpendControlApproval = harness_module.SpendControlApproval
IssuedStagingCapability = harness_module.IssuedStagingCapability
OfflineStagingAuthorizationStore = harness_module.OfflineStagingAuthorizationStore

APP_KEY = "synthetic-application-secret-do-not-persist"
ENV_KEY = "synthetic-environment-secret-do-not-persist"
SESSION_ID = "sess_synthetic123"
ENVIRONMENT_ID = "env_synthetic123"
REMOTE_URL = "https://api.openai.com/v1/agents/api?route=synthetic-signed-route"
AGENT = {"model": "synthetic-connectivity-model", "tools": []}
SYNTHETIC_SPEND_APPROVAL = SpendControlApproval(
    limit=1250,
    approval_reference="synthetic-only-approval",
    billing_owner_acknowledged=True,
)
SESSION_CREATE_HTTP_FAILURES = (
    (400, "session_create_http_400", "not_created", True),
    (401, "session_create_http_401", "not_created", True),
    (403, "session_create_http_403", "not_created", True),
    (404, "session_create_http_404", "not_created", True),
    (422, "session_create_http_422", "not_created", True),
    (409, "session_create_http_other_4xx_409", "not_created", True),
    (408, "session_create_http_408", "unknown", False),
    (429, "session_create_http_429", "unknown", False),
    (500, "session_create_http_5xx_500", "unknown", False),
)
AUTHORIZATION_TEST_NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
AUTHORIZATION_TEST_COMMIT = "a" * 40
AUTHORIZATION_TEST_BINDING = harness_module.StagingAuthorizationBinding(
    "F09-synthetic-attempt", "c" * 64, "d" * 64, 200
)


def _unverified_staging_claims(**overrides):
    claims = {
        "schema_version": 2,
        "authorization_id": "synthetic-auth-001",
        "issuer_id": "synthetic-staging-approver",
        "project_name": "rkmcp-staging",
        "project_id": "synthetic-staging-project-id",
        "source_commit": AUTHORIZATION_TEST_COMMIT,
        "issued_at": "2026-10-23T12:00:00Z",
        "session_count": 1,
        "task_count": 0,
        "task_submission_allowed": False,
        "responses_inference_allowed": False,
        "spend_control_limit_cents": 200,
        "expires_at": "2026-10-23T12:05:00Z",
        "billing_owner_id": "synthetic-billing-owner",
        "billing_owner_approval_reference": "synthetic-billing-approval",
        "billing_owner_acknowledged": True,
        "billing_risk_acknowledged": True,
        "attempt_id": AUTHORIZATION_TEST_BINDING.attempt_id,
        "configuration_sha256": AUTHORIZATION_TEST_BINDING.configuration_sha256,
        "credential_scope_sha256": AUTHORIZATION_TEST_BINDING.credential_scope_sha256,
    }
    claims.update(overrides)
    return claims


def _staging_issue_claims(**overrides):
    claims = _unverified_staging_claims(**overrides)
    for field in ("schema_version", "authorization_id", "issuer_id", "issued_at"):
        claims.pop(field)
    return claims


def _authorization_store(root, role_state):
    return OfflineStagingAuthorizationStore(
        root,
        synthetic=True,
        issuer_role="synthetic-issuer",
        runtime_role="synthetic-runtime",
        current_role=lambda: role_state["value"],
    )


def _issue_offline_capability(store, **changes):
    return store.issue(
        _staging_issue_claims(**changes),
        expected_project_id="synthetic-staging-project-id",
        expected_source_commit=AUTHORIZATION_TEST_COMMIT,
        expected_binding=AUTHORIZATION_TEST_BINDING,
        now_utc=AUTHORIZATION_TEST_NOW,
    )


def _event(kind, environment_id=ENVIRONMENT_ID):
    return {"type": kind, "data": {"environment_id": environment_id}}


def _sse(events):
    return b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeExecutor:
    def __init__(
        self, *, clock=None, start_advance=0, stop=True, start_exception=None, timeline=None
    ):
        self.clock = clock
        self.start_advance = start_advance
        self.stop_result = stop
        self.starts = 0
        self.stops = []
        self.key_seen = None
        self.start_exception = start_exception
        self.timeline = timeline

    def start(self, session, *, environment_key, timeout):
        self.starts += 1
        if self.timeline is not None:
            self.timeline.append("executor_start")
        self.key_seen = environment_key
        assert session["remote_url"] == REMOTE_URL
        assert timeout > 0
        if self.start_exception is not None:
            raise self.start_exception
        if self.clock is not None:
            self.clock.advance(self.start_advance)
        return "synthetic-container-id"

    def stop_verified(self, container_id, *, timeout):
        self.stops.append((container_id, timeout))
        if self.timeline is not None:
            self.timeline.append("executor_stop")
        return self.stop_result


class FakeAPI:
    def __init__(self, events, *, create_exception=None, delete=True):
        self.events = events
        self._key = APP_KEY
        self.synthetic = True
        self.create_exception = create_exception
        self.delete_result = delete
        self.created = 0
        self.deleted = []
        self.closed = False

    def create_session(self, agent_config, *, timeout):
        self.created += 1
        assert timeout > 0
        assert agent_config == AGENT
        if self.create_exception:
            raise self.create_exception
        return {
            "session_id": SESSION_ID,
            "environment_id": ENVIRONMENT_ID,
            "remote_url": REMOTE_URL,
        }

    def open_event_stream(self, session_id, *, timeout):
        assert session_id == SESSION_ID
        assert timeout > 0
        return iter(self.events)

    @staticmethod
    def iter_events(response):
        return response

    @staticmethod
    def close_event_stream(_response):
        pass

    def delete_session(self, session_id, *, timeout=None):
        if timeout is not None:
            assert timeout > 0
        self.deleted.append(session_id)
        return self.delete_result

    def close(self):
        self.closed = True


def _make(
    tmp_path,
    api,
    executor,
    *,
    clock=None,
    journal_write=None,
    journal_fsync=None,
    create_seconds=10,
    connect_seconds=10,
    cleanup_seconds=5,
    synthetic_authorization=None,
):
    lease = StagingLease(tmp_path, synthetic=True)
    journal_args = {"synthetic": True}
    if journal_write is not None:
        journal_args["write"] = journal_write
    if journal_fsync is not None:
        journal_args["fsync"] = journal_fsync
    journal = StagingJournal(tmp_path, **journal_args)
    client = api if isinstance(api, FakeAPI) else api
    return (
        ConnectivityHarness(
            client=client,
            executor=executor,
            journal=journal,
            lease=lease,
            agent_config=AGENT,
            environment_key=ENV_KEY,
            clock=clock or FakeClock(),
            create_seconds=create_seconds,
            connect_seconds=connect_seconds,
            cleanup_seconds=cleanup_seconds,
            wall_clock=lambda: "2030-01-01T00:00:00+00:00",
            synthetic_authorization=synthetic_authorization,
        ),
        lease,
        journal,
    )


def _saved_audit(lease):
    audit_paths = list(lease.root.glob("run-*/connectivity-audit.json"))
    assert len(audit_paths) == 1
    return json.loads(audit_paths[0].read_text())


def _http_client(
    tmp_path,
    events,
    *,
    calls=None,
    timeline=None,
    create_status=200,
    create_error_body=None,
    delete_status=200,
    spend_approval=SYNTHETIC_SPEND_APPROVAL,
    project_id="synthetic-staging-project",
    on_request=None,
):
    calls = calls if calls is not None else []
    event_bytes = _sse(events)

    def handler(request):
        if on_request is not None:
            on_request(request)
        calls.append(request)
        if timeline is not None:
            timeline.append(f"http:{request.method}")
        if request.method == "POST" and request.url.path == "/v1/agents/sessions":
            body = json.loads(request.content)
            assert set(body) == {"agent", "environment", "spend_control"}
            assert "input" not in body and "events" not in body
            assert body["agent"]["model"] == AGENT["model"]
            assert body["agent"]["tools"] == []
            assert body["environment"]["type"] == "self_hosted"
            assert body["spend_control"] == {"limit": spend_approval.limit}
            if create_error_body is not None:
                return httpx.Response(
                    create_status,
                    headers={"content-type": "application/json", "x-synthetic-secret": ENV_KEY},
                    content=create_error_body,
                )
            return httpx.Response(
                create_status,
                json={
                    "id": SESSION_ID,
                    "environment": {
                        "id": ENVIRONMENT_ID,
                        "type": "self_hosted",
                        "remote_url": REMOTE_URL,
                    },
                },
            )
        if request.method == "GET" and request.url.path.endswith("/events"):
            assert request.url.path == f"/v1/agents/sessions/{SESSION_ID}/events"
            assert request.url.query == b""
            assert request.headers["accept"] == "text/event-stream"
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=event_bytes,
            )
        if request.method == "DELETE":
            return httpx.Response(
                delete_status,
                json={"id": SESSION_ID, "deleted": True},
            )
        return httpx.Response(404)

    client = StagingAgentsClient(
        APP_KEY,
        project_id=project_id,
        spend_control_approval=spend_approval,
        transport=httpx.MockTransport(handler),
        synthetic=True,
    )
    return client, calls


def test_public_surface_cannot_submit_tasks_or_responses_and_create_has_no_input(tmp_path):
    api, calls = _http_client(tmp_path, [_event("agent.session.environment.connected")])
    executor = FakeExecutor()
    harness, _, _ = _make(tmp_path, api, executor)

    assert not hasattr(api, "submit_task")
    assert not hasattr(api, "send_and_stream")
    assert not hasattr(harness, "submit_task")
    assert not hasattr(harness, "responses")
    audit = harness.run()

    assert audit["connected_observed"] is True
    assert audit["task_submission_count"] == audit["responses_calls"] == 0
    assert [call.method for call in calls] == ["POST", "GET", "DELETE"]
    assert calls[1].url.path == f"/v1/agents/sessions/{SESSION_ID}/events"
    assert calls[1].url.query == b""
    assert calls[1].headers["accept"] == "text/event-stream"
    assert executor.starts == 1
    assert executor.stops[0][0] == "synthetic-container-id"


@pytest.mark.parametrize(
    "approval",
    [
        None,
        SpendControlApproval(None, "synthetic-approval", True),
        SpendControlApproval(0, "synthetic-approval", True),
        SpendControlApproval(-1, "synthetic-approval", True),
        SpendControlApproval(1.0, "synthetic-approval", True),
        SpendControlApproval(1.5, "synthetic-approval", True),
        SpendControlApproval("1250", "synthetic-approval", True),
        SpendControlApproval("12.5", "synthetic-approval", True),
        SpendControlApproval(False, "synthetic-approval", True),
        SpendControlApproval(float("nan"), "synthetic-approval", True),
        SpendControlApproval(float("inf"), "synthetic-approval", True),
        SpendControlApproval(True, "synthetic-approval", True),
        SpendControlApproval(1.0, "", True),
        SpendControlApproval(1.0, "synthetic-approval", False),
    ],
)
def test_missing_or_invalid_spend_control_fails_before_transport(tmp_path, approval):
    calls = []
    api, _ = _http_client(tmp_path, [], calls=calls, spend_approval=approval)

    with pytest.raises(ConnectivityError) as raised:
        api.create_session(AGENT)

    assert raised.value.code in {
        "spend_control_approval_required",
        "spend_control_approval_invalid",
    }
    assert calls == []


def test_nested_environment_connected_event_is_projected_and_accepted(tmp_path):
    event = {
        "type": "agent.session.environment.connected",
        "data": {"environment": {"id": ENVIRONMENT_ID}, "credential": APP_KEY},
        "ignored_secret_field": ENV_KEY,
    }
    api, _ = _http_client(tmp_path, [event])
    executor = FakeExecutor()
    harness, _, _ = _make(tmp_path, api, executor)

    audit = harness.run()

    assert audit["connected_observed"] is True
    assert audit["cleanup_verified"] is True
    assert executor.starts == 1
    assert APP_KEY not in json.dumps(audit)
    assert ENV_KEY not in json.dumps(audit)


@pytest.mark.parametrize(
    ("events", "connected", "failure"),
    [
        (
            [
                _event("agent.session.environment.pending"),
                _event("agent.session.environment.connected"),
            ],
            True,
            None,
        ),
        ([_event("agent.session.environment.failed")], False, "remote_connection_failed"),
        (
            [_event("agent.session.environment.connected", "env_wrong")],
            False,
            "connected_environment_mismatch",
        ),
        ([_event("agent.session.environment.pending")], False, "deadline_expired"),
        ([{"type": "unknown.remote.event"}], False, "unexpected_event_type"),
    ],
)
def test_sse_states_are_fail_closed_and_always_delete_known_session(
    tmp_path, events, connected, failure
):
    timeline = []
    api, calls = _http_client(tmp_path, events, timeline=timeline)
    executor = FakeExecutor(timeline=timeline)
    harness, lease, _ = _make(tmp_path, api, executor)

    result = harness.run()

    assert result["connected_observed"] is connected
    assert result["failure_code"] == failure
    assert result["session_deletion_verified"] is True
    assert result["cleanup_verified"] is True
    assert [call.method for call in calls] == ["POST", "GET", "DELETE"]
    assert timeline.index("executor_stop") < timeline.index("http:DELETE")
    assert not lease.lock_path.exists()
    assert executor.stops


def test_late_connected_event_is_not_accepted(tmp_path):
    clock = FakeClock()
    api, calls = _http_client(tmp_path, [_event("agent.session.environment.connected")])
    iter_events = api.iter_events

    def late_events(response):
        for event in iter_events(response):
            clock.advance(2)
            yield event

    api.iter_events = late_events
    executor = FakeExecutor(stop=False)
    harness, lease, _ = _make(tmp_path, api, executor, clock=clock, connect_seconds=1)

    with pytest.raises(ConnectivityError):
        harness.run()

    audit = _saved_audit(lease)
    assert audit["connected_observed"] is False
    assert audit["failure_code"] == "deadline_expired"
    assert audit["cleanup_verified"] is False
    assert lease.lock_path.exists()
    assert [call.method for call in calls] == ["POST", "GET", "DELETE"]
    assert audit["task_submission_count"] == audit["responses_calls"] == 0


def test_connected_event_past_real_deadline_is_not_accepted(tmp_path, monkeypatch):
    class MonotonicClock:
        value = 1000.0

        def __call__(self):
            return self.value

    monotonic = MonotonicClock()
    monkeypatch.setattr(harness_module.time, "monotonic", monotonic)
    timeline = []
    api, requests = _http_client(
        tmp_path,
        [_event("agent.session.environment.connected")],
        timeline=timeline,
    )
    iter_events = api.iter_events
    event_delivered = False

    def tracked_events(response):
        nonlocal event_delivered
        for event in iter_events(response):
            timeline.append("sse:connected_delivered")
            event_delivered = True
            yield event

    api.iter_events = tracked_events
    executor = FakeExecutor(stop=False, timeline=timeline)
    harness, lease, _ = _make(tmp_path, api, executor, clock=FakeClock(), connect_seconds=1)
    bounded_call = harness_module._bounded_call
    deadline_crossed = False
    bounded_cleanup_calls = []

    def expire_after_event_delivery(callback, **kwargs):
        nonlocal deadline_crossed
        if deadline_crossed:
            timeline.append("bounded_cleanup")
            bounded_cleanup_calls.append(
                {
                    "clock": kwargs["clock"],
                    "deadline": kwargs["deadline"],
                    "real_deadline": monotonic.value
                    + max(0, kwargs["deadline"] - kwargs["clock"]()),
                }
            )
        result = bounded_call(callback, **kwargs)
        if event_delivered and not deadline_crossed:
            monotonic.value += 2
            deadline_crossed = True
            timeline.append("connect_deadline_expired")
        return result

    monkeypatch.setattr(harness_module, "_bounded_call", expire_after_event_delivery)

    with pytest.raises(ConnectivityError):
        harness.run()

    audit = _saved_audit(lease)
    assert audit["connected_observed"] is False
    assert audit["failure_code"] == "deadline_expired"
    assert audit["cleanup_verified"] is False
    assert lease.lock_path.exists()
    deadline_index = timeline.index("connect_deadline_expired")
    assert timeline[:deadline_index] == [
        "http:POST",
        "http:GET",
        "executor_start",
        "sse:connected_delivered",
    ]
    assert timeline[deadline_index + 1 :] == [
        "bounded_cleanup",
        "executor_stop",
        "bounded_cleanup",
        "http:DELETE",
    ]
    creation_requests = [request for request in requests if request.method == "POST"]
    assert len(creation_requests) == 1
    assert creation_requests[0].url.path == "/v1/agents/sessions"
    assert [request.method for request in requests] == ["POST", "GET", "DELETE"]
    assert requests[-1].url.path == f"/v1/agents/sessions/{SESSION_ID}"
    assert "http:POST" not in timeline[deadline_index + 1 :]
    assert audit["task_submission_count"] == audit["responses_calls"] == 0
    assert len(bounded_cleanup_calls) == 2
    assert all(call["clock"] is harness.clock for call in bounded_cleanup_calls)
    assert all(call["deadline"] <= harness._cleanup_deadline for call in bounded_cleanup_calls)
    assert all(
        call["real_deadline"] <= harness._cleanup_real_deadline for call in bounded_cleanup_calls
    )


def test_duplicate_pending_events_do_not_repeat_executor_start(tmp_path):
    api, _ = _http_client(
        tmp_path,
        [
            _event("agent.session.environment.pending"),
            _event("agent.session.environment.pending"),
            _event("agent.session.environment.connected"),
        ],
    )
    executor = FakeExecutor()
    harness, _, _ = _make(tmp_path, api, executor)

    audit = harness.run()

    assert audit["connected_observed"] is True
    assert executor.starts == 1
    assert audit["task_submission_count"] == 0


def test_duplicate_connected_event_does_not_repeat_any_side_effect(tmp_path):
    api, _ = _http_client(
        tmp_path,
        [
            _event("agent.session.environment.connected"),
            _event("agent.session.environment.connected"),
        ],
    )
    executor = FakeExecutor()
    harness, _, _ = _make(tmp_path, api, executor)

    audit = harness.run()

    assert audit["connected_observed"] is True
    assert executor.starts == 1
    assert audit["task_submission_count"] == audit["responses_calls"] == 0


def test_malformed_and_truncated_sse_fail_without_exposing_payload():
    for lines, code in (
        (['data: {"type":', ""], "event_json_invalid"),
        (['data: {"type":"agent.session.environment.connected"}'], "stream_truncated"),
    ):
        with pytest.raises(ConnectivityError) as raised:
            list(StagingAgentsClient._decode_events(lines))
        assert raised.value.code == code
        assert "type" not in str(raised.value)


def test_blocked_boundary_is_bounded_even_if_injected_clock_stalls():
    release = threading.Event()
    started = time.monotonic()

    def blocked_operation():
        release.wait(1)
        return "late"

    try:
        with pytest.raises(TimeoutError):
            harness_module._bounded_call(
                blocked_operation,
                deadline=100.02,
                clock=lambda: 100.0,
            )
        assert time.monotonic() - started < 0.5
    finally:
        release.set()


def test_ambiguous_create_timeout_is_not_retried_and_retains_lease(tmp_path):
    failure = ConnectivityError("https_transport_failed", uncertain=True)
    api = FakeAPI([], create_exception=failure)
    executor = FakeExecutor()
    harness, lease, _ = _make(tmp_path, api, executor)

    with pytest.raises(ConnectivityError, match="connectivity check failed"):
        harness.run()

    assert api.created == 1
    assert api.deleted == []
    assert executor.starts == 0
    assert lease.lock_path.exists()
    audit = _saved_audit(lease)
    assert audit["state"] == "cleanup_unverified"
    assert audit["session_creation_outcome"] == "unknown"


def test_create_rejection_is_distinct_from_ambiguous_creation(tmp_path):
    failure = ConnectivityError("http_rejected", uncertain=False)
    api = FakeAPI([], create_exception=failure)
    executor = FakeExecutor()
    harness, lease, _ = _make(tmp_path, api, executor)

    audit = harness.run()

    assert audit["session_creation_outcome"] == "not_created"
    assert audit["session_deletion_not_required"] is True
    assert audit["cleanup_verified"] is True
    assert not lease.lock_path.exists()


@pytest.mark.parametrize(
    ("status", "expected_code", "expected_outcome"),
    [(status, code, outcome) for status, code, outcome, _ in SESSION_CREATE_HTTP_FAILURES],
)
def test_staging_client_classifies_create_http_status_without_server_text(
    status, expected_code, expected_outcome
):
    hostile_response = json.dumps(
        {
            "error": {
                "message": f"unreviewed server text {APP_KEY}",
                "access_token": ENV_KEY,
                "authorization": f"Bearer {APP_KEY}",
                "url": "https://provider.invalid/path?signature=synthetic-signed-secret",
            }
        }
    ).encode()
    api, calls = _http_client(
        Path("."), [], create_status=status, create_error_body=hostile_response
    )
    try:
        with pytest.raises(ConnectivityError) as rejected:
            api.create_session(AGENT)
    finally:
        api.close()

    assert rejected.value.code == expected_code
    assert rejected.value.uncertain is (expected_outcome == "unknown")
    assert str(rejected.value) == "Managed Agents connectivity check failed"
    assert [request.method for request in calls] == ["POST"]
    assert json.loads(calls[0].content) == {
        "agent": AGENT,
        "environment": {"type": "self_hosted", "workspace_directory": "/workspace"},
        "spend_control": {"limit": SYNTHETIC_SPEND_APPROVAL.limit},
    }
    for secret in (APP_KEY, ENV_KEY, "unreviewed server text", "synthetic-signed-secret"):
        assert secret not in str(rejected.value)


@pytest.mark.parametrize(
    ("status", "expected_code", "expected_outcome", "expected_cleanup"),
    SESSION_CREATE_HTTP_FAILURES,
)
def test_session_create_http_rejections_are_bounded_and_preserve_cleanup_semantics(
    tmp_path, capsys, status, expected_code, expected_outcome, expected_cleanup
):
    hostile_response = json.dumps(
        {
            "error": {
                "message": f"unreviewed server text {APP_KEY}",
                "access_token": ENV_KEY,
                "authorization": f"Bearer {APP_KEY}",
                "url": "https://provider.invalid/path?signature=synthetic-signed-secret",
            }
        }
    ).encode()
    harness, lease, journal, plan, calls = _authorized_rehearsal(
        tmp_path,
        create_status=status,
        create_error_body=hostile_response,
    )

    if expected_cleanup:
        result = harness.run()
    else:
        with pytest.raises(ConnectivityError) as raised:
            harness.run()
        assert raised.value.code == "session_create_uncertain"
        assert str(raised.value) == "Managed Agents connectivity check failed"
        result = _saved_audit(lease)

    assert result["failure_code"] == expected_code
    assert result["session_creation_outcome"] == expected_outcome
    assert result["cleanup_verified"] is expected_cleanup
    assert result["session_deletion_not_required"] is expected_cleanup
    assert result["session_deletion_verified"] is False
    assert result["executor_start_attempted"] is False
    assert harness.executor.starts == 0
    assert result["task_submission_count"] == result["responses_calls"] == 0
    assert [request.method for request in calls] == ["POST"]
    assert lease.lock_path.exists() is (not expected_cleanup)

    claimed = list(plan.store.consumed_root.glob("*.claimed"))
    consumed = list(plan.store.consumed_root.glob("*.consumed"))
    assert len(claimed) == len(consumed) == 1
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    consume_outcome = next(
        row
        for row in rows
        if row["operation"] == "authorization_consume" and row["event"] == "outcome"
    )
    create_intent = next(
        row for row in rows if row["operation"] == "session_create" and row["event"] == "intent"
    )
    create_outcome = next(
        row for row in rows if row["operation"] == "session_create" and row["event"] == "outcome"
    )
    assert consume_outcome["seq"] < create_intent["seq"]
    assert create_outcome["code"] == expected_code

    evidence = json.dumps({"audit": result, "journal": rows}, sort_keys=True)
    captured = capsys.readouterr()
    for secret in (
        APP_KEY,
        ENV_KEY,
        "unreviewed server text",
        "synthetic-signed-secret",
        "provider.invalid",
        "access_token",
        '"authorization":',
    ):
        assert secret not in evidence
        assert secret not in captured.out
        assert secret not in captured.err


def test_unverified_executor_stop_or_session_delete_prevents_clean_release(tmp_path):
    api, _ = _http_client(tmp_path, [_event("agent.session.environment.connected")])
    executor = FakeExecutor(stop=False)
    harness, lease, _ = _make(tmp_path, api, executor)

    with pytest.raises(ConnectivityError):
        harness.run()

    assert lease.lock_path.exists()
    audit = _saved_audit(lease)
    assert audit["executor_termination_verified"] is False
    assert audit["cleanup_verified"] is False


def test_unverified_session_deletion_prevents_clean_release(tmp_path):
    api = FakeAPI([_event("agent.session.environment.connected")], delete=False)
    executor = FakeExecutor()
    harness, lease, _ = _make(tmp_path, api, executor)

    with pytest.raises(ConnectivityError):
        harness.run()

    assert executor.stops
    assert api.deleted == [SESSION_ID]
    assert lease.lock_path.exists()
    audit = _saved_audit(lease)
    assert audit["session_deletion_verified"] is False
    assert audit["cleanup_verified"] is False


def test_failed_journal_intent_blocks_session_creation_and_keeps_lease(tmp_path):
    def fail_write(_fd, _data):
        raise OSError("synthetic fsync boundary failure")

    api = FakeAPI([])
    harness, lease, journal = _make(tmp_path, api, FakeExecutor(), journal_write=fail_write)

    with pytest.raises(ConnectivityError):
        harness.run()

    assert api.created == 0
    assert lease.lock_path.exists()
    assert journal.failed is True
    assert not list(lease.root.glob("run-*/connectivity-audit.json"))


def test_saved_audit_redacts_credentials_ids_remote_url_and_exception_text(tmp_path):
    event = _event("agent.session.environment.connected")
    event["data"].update(
        {
            "authorization": APP_KEY,
            "credential": ENV_KEY,
            "private_url": REMOTE_URL,
            "exception": "synthetic raw exception material",
        }
    )
    api, _ = _http_client(tmp_path, [event])
    executor = FakeExecutor()
    harness, lease, _ = _make(tmp_path, api, executor)

    audit = harness.run()
    saved = next(lease.root.glob("run-*/connectivity-audit.json")).read_text()
    saved_audit = json.loads(saved)

    for forbidden in (
        APP_KEY,
        ENV_KEY,
        SESSION_ID,
        ENVIRONMENT_ID,
        REMOTE_URL,
        "synthetic raw exception material",
    ):
        assert forbidden not in saved
        assert forbidden not in json.dumps(audit)
    assert audit["session_id_sha256"]
    assert audit["environment_id_sha256"]
    assert audit["remote_endpoint_omitted"] is True
    assert type(audit["remote_endpoint_omitted"]) is bool
    assert type(audit["connected_observed"]) is bool
    assert type(audit["executor_termination_verified"]) is bool
    assert type(audit["session_deletion_verified"]) is bool
    assert type(audit["cleanup_verified"]) is bool
    assert saved_audit["remote_endpoint_omitted"] is True
    assert type(saved_audit["remote_endpoint_omitted"]) is bool
    assert type(saved_audit["cleanup_verified"]) is bool


def test_fixed_https_proxy_and_redirect_contract(monkeypatch):
    captured = {}
    original_client = httpx.Client

    class FakeHTTPClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self):
            pass

    monkeypatch.setattr(harness_module.httpx, "Client", FakeHTTPClient)
    client = StagingAgentsClient(
        APP_KEY,
        project_id="synthetic-staging-project",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        synthetic=True,
    )
    assert captured["base_url"] == "https://api.openai.com"
    assert captured["verify"] is True
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False
    client.close()
    monkeypatch.setattr(harness_module.httpx, "Client", original_client)

    redirects, calls = _http_client(Path("."), [], create_status=302)
    with pytest.raises(ConnectivityError) as raised:
        redirects.create_session(AGENT)
    assert raised.value.code == "redirect_rejected"
    assert raised.value.uncertain is True
    assert len(calls) == 1


def test_fixed_route_client_rejects_task_and_responses_paths_before_transport(tmp_path):
    api, calls = _http_client(tmp_path, [])

    with pytest.raises(ConnectivityError) as task_route:
        api._json("POST", f"/v1/agents/sessions/{SESSION_ID}/events")
    with pytest.raises(ConnectivityError) as responses_route:
        api._json("POST", "/v1/responses")
    with pytest.raises(ConnectivityError) as noncanonical_stream_route:
        api._json("GET", f"/v1/agents/sessions/{SESSION_ID}/events?stream=true")

    assert (
        task_route.value.code
        == responses_route.value.code
        == noncanonical_stream_route.value.code
        == "route_rejected"
    )
    assert calls == []

    with pytest.raises(ConnectivityError) as task_body:
        api._json(
            "POST",
            "/v1/agents/sessions",
            body={
                "agent": AGENT,
                "environment": {"type": "self_hosted", "workspace_directory": "/workspace"},
                "input": "synthetic task must not be sent",
            },
        )
    assert task_body.value.code == "create_body_rejected"
    assert calls == []


def test_lease_release_is_authorized_by_a_durable_journal_outcome(tmp_path):
    api, _ = _http_client(tmp_path, [_event("agent.session.environment.connected")])
    harness, lease, journal = _make(tmp_path, api, FakeExecutor())
    release = lease.release

    def checked_release():
        records = [json.loads(line) for line in journal.path.read_text().splitlines()]
        assert records[-1]["operation"] == "lease_release"
        assert records[-1]["event"] == "outcome"
        assert records[-1]["code"] == "release_authorized"
        release()

    lease.release = checked_release
    audit = harness.run()

    assert audit["cleanup_verified"] is True
    assert not lease.lock_path.exists()


def test_journal_fsync_failure_blocks_session_creation_and_retains_lease(tmp_path):
    def fail_fsync(_fd):
        raise OSError("synthetic private detail")

    api = FakeAPI([])
    harness, lease, journal = _make(tmp_path, api, FakeExecutor(), journal_fsync=fail_fsync)

    with pytest.raises(ConnectivityError):
        harness.run()

    assert api.created == 0
    assert journal.failed is True
    assert lease.lock_path.exists()
    assert not list(lease.root.glob("run-*/connectivity-audit.json"))


def test_release_failure_keeps_durable_audit_and_retains_lease(tmp_path):
    api, _ = _http_client(tmp_path, [_event("agent.session.environment.connected")])
    harness, lease, journal = _make(tmp_path, api, FakeExecutor())

    def fail_release():
        assert list(lease.root.glob("run-*/connectivity-audit.json"))
        raise OSError("synthetic release failure detail")

    lease.release = fail_release
    with pytest.raises(ConnectivityError):
        harness.run()

    assert lease.lock_path.exists()
    assert journal.pending == {}


def test_release_sync_failure_before_unlink_blocks_other_acquisition(tmp_path, monkeypatch):
    lease = StagingLease(tmp_path, synthetic=True)
    lease.acquire()
    original_sync = harness_module._fsync_directory
    failed = False

    def fail_pending_sync(path, *, required):
        nonlocal failed
        if path == lease.root and not failed:
            failed = True
            raise OSError("synthetic pre-unlink directory sync failure")
        return original_sync(path, required=required)

    monkeypatch.setattr(harness_module, "_fsync_directory", fail_pending_sync)
    with pytest.raises(harness_module.DurabilityError):
        lease.release()

    assert lease.lock_path.exists()
    contender = StagingLease(tmp_path, synthetic=True)
    with pytest.raises(harness_module.DurabilityError, match="reconciliation"):
        contender.acquire()


def test_release_sync_failure_after_unlink_requires_process_restart_reconciliation(
    tmp_path, monkeypatch
):
    lease = StagingLease(tmp_path, synthetic=True)
    lease.acquire()
    original_sync = harness_module._fsync_directory
    root_syncs = 0

    def fail_after_unlink_sync(path, *, required):
        nonlocal root_syncs
        if path == lease.root:
            root_syncs += 1
            if root_syncs == 2:
                raise OSError("synthetic post-unlink directory sync failure")
        return original_sync(path, required=required)

    monkeypatch.setattr(harness_module, "_fsync_directory", fail_after_unlink_sync)
    with pytest.raises(harness_module.DurabilityError, match="unresolved"):
        lease.release()

    assert not lease.lock_path.exists()
    assert len(list(lease.root.glob("release-*.pending"))) == 1
    assert not list(lease.root.glob("release-*.complete"))

    # A new lease object models a later process after the interrupted release.
    restarted = StagingLease(tmp_path, synthetic=True)
    with pytest.raises(harness_module.DurabilityError, match="reconciliation"):
        restarted.acquire()

    journal = StagingJournal(tmp_path, synthetic=True)
    before = journal.path.read_bytes()
    report = harness_module.inspect_staging_journal(journal.path)
    assert report["lease_release_state"] == "unresolved"
    assert report["recovery_authorized"] is False
    assert report["cleanup_complete"] is False
    assert journal.path.read_bytes() == before
    journal.close()

    unscoped = harness_module.inspect_staging_journal(tmp_path / "unscoped.jsonl")
    assert unscoped["lease_release_state"] == "unknown"
    with pytest.raises(harness_module.DurabilityError, match="reconciliation"):
        restarted.acquire()


def test_competing_lease_acquisition_cannot_race_release(tmp_path, monkeypatch):
    lease = StagingLease(tmp_path, synthetic=True)
    lease.acquire()
    original_sync = harness_module._fsync_directory
    pending_sync_started = threading.Event()
    resume_release = threading.Event()
    release_errors = []
    blocked = False

    def pause_pending_sync(path, *, required):
        nonlocal blocked
        if path == lease.root and not blocked:
            blocked = True
            pending_sync_started.set()
            if not resume_release.wait(2):
                raise OSError("synthetic release barrier timed out")
        return original_sync(path, required=required)

    monkeypatch.setattr(harness_module, "_fsync_directory", pause_pending_sync)

    def release_lease():
        try:
            lease.release()
        except Exception as exc:
            release_errors.append(type(exc))

    releaser = threading.Thread(target=release_lease)
    releaser.start()
    assert pending_sync_started.wait(1)
    contender = StagingLease(tmp_path, synthetic=True)
    with pytest.raises(harness_module.DurabilityError, match="in progress"):
        contender.acquire()
    resume_release.set()
    releaser.join(2)

    assert not releaser.is_alive()
    assert release_errors == []
    assert not lease.lock_path.exists()
    contender.acquire()
    assert lease.lock_path.exists()
    contender.release()
    assert not lease.lock_path.exists()


def test_independent_processes_cannot_hold_the_same_lease(tmp_path):
    module_directory = ROOT / "benchmarks/codex_r/exploratory"
    ready = tmp_path / "process-one-ready"
    release = tmp_path / "process-one-release"
    holder_code = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import connectivity_harness as h
root, ready, release = map(Path, sys.argv[2:5])
lease = h.StagingLease(root, synthetic=True)
lease.acquire()
ready.write_text('ready', encoding='ascii')
deadline = time.monotonic() + 8
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not release.exists():
    raise SystemExit(8)
lease.release()
"""
    contender_code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import connectivity_harness as h
lease = h.StagingLease(Path(sys.argv[2]), synthetic=True)
try:
    lease.acquire()
except h.DurabilityError:
    print('blocked')
    raise SystemExit(0)
lease.release()
print('unexpectedly-acquired')
raise SystemExit(9)
"""
    holder = None
    try:
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                holder_code,
                str(module_directory),
                str(tmp_path),
                str(ready),
                str(release),
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and holder.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "lease holder subprocess did not acquire in time"
        contender = subprocess.run(
            [sys.executable, "-c", contender_code, str(module_directory), str(tmp_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert contender.returncode == 0, contender.stderr
        assert contender.stdout.strip() == "blocked"
        assert holder.poll() is None
    finally:
        try:
            release.touch(exist_ok=True)
        finally:
            if holder is not None:
                try:
                    holder.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    holder.terminate()
                    try:
                        holder.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        holder.kill()
                        holder.wait(timeout=2)

    assert holder is not None and holder.returncode == 0


def test_fresh_process_rejects_lease_after_process_exits_mid_release(tmp_path):
    module_directory = ROOT / "benchmarks/codex_r/exploratory"
    interrupted_release_code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import connectivity_harness as h
root = Path(sys.argv[2])
lease = h.StagingLease(root, synthetic=True)
lease.acquire()
original_sync = h._fsync_directory
root_syncs = 0
def fail_after_unlink(path, *, required):
    global root_syncs
    if path == lease.root:
        root_syncs += 1
        if root_syncs == 2:
            raise OSError('synthetic post-unlink directory sync failure')
    return original_sync(path, required=required)
h._fsync_directory = fail_after_unlink
try:
    lease.release()
except h.DurabilityError:
    print('release-unresolved')
    raise SystemExit(0)
raise SystemExit(10)
"""
    acquire_code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import connectivity_harness as h
lease = h.StagingLease(Path(sys.argv[2]), synthetic=True)
try:
    lease.acquire()
except h.DurabilityError:
    print('blocked')
    raise SystemExit(0)
lease.release()
print('unexpectedly-acquired')
raise SystemExit(11)
"""
    interrupted = subprocess.run(
        [sys.executable, "-c", interrupted_release_code, str(module_directory), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert interrupted.returncode == 0, interrupted.stderr
    assert interrupted.stdout.strip() == "release-unresolved"

    lease_root = tmp_path / harness_module.JOURNAL_DIRNAME
    assert not (lease_root / "active.lock").exists()
    assert len(list(lease_root.glob("release-*.pending"))) == 1
    assert not list(lease_root.glob("release-*.complete"))

    fresh_process = subprocess.run(
        [sys.executable, "-c", acquire_code, str(module_directory), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert fresh_process.returncode == 0, fresh_process.stderr
    assert fresh_process.stdout.strip() == "blocked"


def test_lease_gate_and_release_markers_keep_private_modes(tmp_path):
    lease = StagingLease(tmp_path, synthetic=True)
    lease.acquire()
    lease.release()

    if os.name != "nt":
        assert stat.S_IMODE(lease.root.stat().st_mode) == 0o700
        private_files = [lease.root / "lease.gate", *lease.root.glob("release-*")]
        assert private_files
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in private_files)


def test_agent_configuration_rejects_input_tools_and_unreviewed_fields():
    for config in (
        {"model": "synthetic-model", "input": "synthetic task"},
        {"model": "synthetic-model", "tools": [{"type": "function"}]},
        {"model": "synthetic-model", "instructions": "unreviewed"},
    ):
        with pytest.raises(ValueError):
            StagingAgentsClient._validate_agent_config(config)


def test_malformed_runtime_start_result_is_cleaned_by_bounded_stop():
    class Topology:
        cleaned = 0

        def start(self):
            return {"proxy_internal_ip": "172.20.0.2"}

        def cleanup(self):
            self.cleaned += 1
            return True

    class Runtime:
        stopped = []

        def start_managed_executor(self, *_args, **_kwargs):
            return {"executor_registered": True, "container_id": "a" * 64}

        def stop_managed_executor(self, container_id):
            self.stopped.append(container_id)
            return True

    topology = Topology()
    runtime = Runtime()
    adapter = DockerExecutorAdapter(runtime, topology, Path("."), "172.20.0.1")

    with pytest.raises(ConnectivityError):
        adapter.start(
            {"environment_id": ENVIRONMENT_ID, "remote_url": REMOTE_URL},
            environment_key=ENV_KEY,
            timeout=1,
        )

    assert adapter.stop_verified(None, timeout=1) is True
    assert runtime.stopped == ["a" * 64]
    assert topology.cleaned == 1


@pytest.mark.parametrize("transport", [None, httpx.MockTransport(lambda r: httpx.Response(200))])
def test_live_client_fails_closed_without_verified_project_scope(monkeypatch, transport):
    monkeypatch.setenv(harness_module.PROJECT_CONFIRMATION_ENV, "staging-project")
    with pytest.raises(ValueError):
        StagingAgentsClient(APP_KEY, project_id="staging-project", transport=transport)


def test_live_project_missing_or_mismatched(monkeypatch):
    for project in ("", "different-project"):
        monkeypatch.setenv(harness_module.PROJECT_CONFIRMATION_ENV, project)
        with pytest.raises(ValueError):
            StagingAgentsClient(APP_KEY, project_id="staging-project")


def test_self_declared_spend_approval_cannot_unlock_live_client(monkeypatch):
    monkeypatch.setenv(harness_module.PROJECT_CONFIRMATION_ENV, "staging-project")
    client_constructions = []

    def unexpected_http_client(*args, **kwargs):
        client_constructions.append((args, kwargs))
        raise AssertionError("live HTTP client construction must remain blocked")

    monkeypatch.setattr(harness_module.httpx, "Client", unexpected_http_client)
    approval = SpendControlApproval(
        limit=200,
        approval_reference="operator-entered-reference",
        billing_owner_acknowledged=True,
    )

    for _attempt in range(2):
        with pytest.raises(
            ValueError, match="Live F09 client requires the solo-operator authorization entry point"
        ):
            StagingAgentsClient(
                APP_KEY,
                project_id="staging-project",
                spend_control_approval=approval,
            )

    assert client_constructions == []


def test_staging_authorization_claims_are_not_provider_verified_authority():
    claims = _unverified_staging_claims()
    parsed = harness_module.parse_unverified_staging_authorization_claims(
        claims,
        expected_project_id="synthetic-staging-project-id",
        expected_source_commit=AUTHORIZATION_TEST_COMMIT,
        expected_binding=AUTHORIZATION_TEST_BINDING,
        now_utc=AUTHORIZATION_TEST_NOW,
    )

    assert parsed["project_id"] == "synthetic-staging-project-id"
    assert parsed["source_commit"] == AUTHORIZATION_TEST_COMMIT
    assert parsed["session_count"] == 1
    assert parsed["task_count"] == 0
    assert parsed["spend_control_limit_cents"] == 200
    with pytest.raises(ConnectivityError) as raised:
        harness_module.require_trusted_staging_authorization(
            claims,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
        )
    assert raised.value.code == "staging_authorization_issuer_unavailable"


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"schema_version": True}, id="boolean-schema-version"),
        pytest.param({"schema_version": 1}, id="legacy-unbound-record"),
        pytest.param({"attempt_id": "R01-A/attempt-1"}, id="historical-r01a"),
        pytest.param({"attempt_id": "F09-different-attempt"}, id="attempt-mismatch"),
        pytest.param({"configuration_sha256": "e" * 64}, id="configuration-mismatch"),
        pytest.param({"credential_scope_sha256": "e" * 64}, id="credential-scope-mismatch"),
        pytest.param({"billing_risk_acknowledged": False}, id="billing-risk-unacknowledged"),
        pytest.param({"project_name": "other-project"}, id="project-name"),
        pytest.param({"project_id": "other-project-id"}, id="project-id"),
        pytest.param({"source_commit": "b" * 40}, id="source-commit"),
        pytest.param({"session_count": True}, id="boolean-session-count"),
        pytest.param({"session_count": 2}, id="multiple-sessions"),
        pytest.param({"task_count": False}, id="boolean-task-count"),
        pytest.param({"task_count": 1}, id="task-count"),
        pytest.param({"task_submission_allowed": True}, id="task-submission"),
        pytest.param({"responses_inference_allowed": True}, id="responses-inference"),
        pytest.param({"spend_control_limit_cents": True}, id="boolean-limit"),
        pytest.param({"spend_control_limit_cents": None}, id="null-limit"),
        pytest.param({"spend_control_limit_cents": 0}, id="zero-limit"),
        pytest.param({"spend_control_limit_cents": -1}, id="negative-limit"),
        pytest.param({"spend_control_limit_cents": "200"}, id="string-limit"),
        pytest.param({"spend_control_limit_cents": 199}, id="unapproved-limit"),
        pytest.param({"spend_control_limit_cents": float("nan")}, id="nan-limit"),
        pytest.param({"spend_control_limit_cents": float("inf")}, id="infinite-limit"),
        pytest.param({"spend_control_limit_cents": 200.0}, id="fractional-limit"),
        pytest.param({"spend_control_limit_cents": 201}, id="limit-mismatch"),
        pytest.param({"expires_at": "2026-10-23T11:59:59Z"}, id="expired"),
        pytest.param({"expires_at": "not-an-iso-time"}, id="malformed-expiration"),
        pytest.param({"issuer_id": ""}, id="missing-issuer"),
        pytest.param({"billing_owner_id": ""}, id="missing-billing-owner"),
        pytest.param({"billing_owner_approval_reference": ""}, id="billing-approval"),
        pytest.param({"approved": True}, id="self-declared-approved-field"),
    ],
)
def test_unverified_staging_claims_reject_mismatch_and_unsafe_scope(changes):
    claims = _unverified_staging_claims(**changes)
    with pytest.raises(ConnectivityError) as raised:
        harness_module.parse_unverified_staging_authorization_claims(
            claims,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
        )
    assert raised.value.code == "staging_authorization_claims_invalid"


def test_unverified_staging_claims_require_expiration_and_exact_source_pin():
    claims = _unverified_staging_claims()
    claims.pop("expires_at")
    with pytest.raises(ConnectivityError) as raised:
        harness_module.parse_unverified_staging_authorization_claims(
            claims,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
        )
    assert raised.value.code == "staging_authorization_claims_invalid"

    claims = _unverified_staging_claims()
    with pytest.raises(ConnectivityError) as raised:
        harness_module.parse_unverified_staging_authorization_claims(
            claims,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit="2ae58b0",
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
        )
    assert raised.value.code == "staging_authorization_claims_invalid"


def test_unverified_staging_authorization_rejected_on_replay_and_after_restart():
    claims = _unverified_staging_claims()
    verify = harness_module.require_trusted_staging_authorization
    for _attempt in range(2):
        with pytest.raises(ConnectivityError) as raised:
            verify(
                claims,
                expected_project_id="synthetic-staging-project-id",
                expected_source_commit=AUTHORIZATION_TEST_COMMIT,
                expected_binding=AUTHORIZATION_TEST_BINDING,
                now_utc=AUTHORIZATION_TEST_NOW,
            )
        assert raised.value.code == "staging_authorization_issuer_unavailable"

    # A fresh verifier in a new interpreter still rejects the same unsigned claims.
    child_code = r"""
import importlib.util
import json
import sys
from datetime import UTC, datetime

spec = importlib.util.spec_from_file_location("staging_auth_review", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
claims = json.loads(sys.stdin.read())
try:
    module.require_trusted_staging_authorization(
        claims,
        expected_project_id="synthetic-staging-project-id",
        expected_source_commit="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        expected_binding=module.StagingAuthorizationBinding(
            "F09-synthetic-attempt", "c" * 64, "d" * 64, 200),
        now_utc=datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
    )
except module.ConnectivityError as error:
    if error.code != "staging_authorization_issuer_unavailable":
        raise SystemExit(3)
else:
    raise SystemExit(2)
print("rejected")
"""
    child_environment = {"PATH": os.defpath}
    if os.name == "nt" and os.environ.get("SystemRoot"):
        child_environment["SystemRoot"] = os.environ["SystemRoot"]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            child_code,
            str(Path(harness_module.__file__).resolve()),
        ],
        input=json.dumps(claims),
        text=True,
        capture_output=True,
        timeout=5,
        env=child_environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "rejected"


def test_concurrent_unverified_staging_authorizations_all_fail_closed():
    claims = _unverified_staging_claims()

    def attempt(_index):
        try:
            harness_module.require_trusted_staging_authorization(
                claims,
                expected_project_id="synthetic-staging-project-id",
                expected_source_commit=AUTHORIZATION_TEST_COMMIT,
                expected_binding=AUTHORIZATION_TEST_BINDING,
                now_utc=AUTHORIZATION_TEST_NOW,
            )
        except ConnectivityError as error:
            return error.code
        return "unexpectedly_authorized"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(16)))

    assert results == ["staging_authorization_issuer_unavailable"] * 16


def test_offline_capability_store_cannot_enter_non_synthetic_mode():
    with pytest.raises(harness_module.DurabilityError):
        OfflineStagingAuthorizationStore(
            Path("C:/unopened-f09-authorization-store"),
            synthetic=False,
            issuer_role="issuer",
            runtime_role="runtime",
            current_role=lambda: "runtime",
        )


def test_offline_capability_store_consumes_once_and_keeps_only_digest(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "external-state", role)
    capability = _issue_offline_capability(store)
    record_path = store.issued_root / f"{capability.authorization_id}.json"
    record_bytes = record_path.read_bytes()
    token = capability._value

    assert store.root.name == harness_module.STAGING_AUTHORIZATION_STORE_DIRNAME
    assert token not in record_bytes
    assert token.hex().encode() not in record_bytes
    assert hashlib.sha256(token).hexdigest().encode() in record_bytes
    assert token.hex() not in repr(capability)

    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "journal-first", synthetic=True)
    parsed = store.consume(
        capability,
        expected_project_id="synthetic-staging-project-id",
        expected_source_commit=AUTHORIZATION_TEST_COMMIT,
        expected_binding=AUTHORIZATION_TEST_BINDING,
        now_utc=AUTHORIZATION_TEST_NOW,
        journal=journal,
    )
    assert parsed["session_count"] == 1
    assert parsed["task_count"] == 0
    assert parsed["spend_control_limit_cents"] == 200
    marker = store.consumed_root / f"{capability.authorization_id}.consumed"
    marker_bytes = marker.read_bytes()
    assert token not in marker_bytes
    assert token.hex().encode() not in marker_bytes
    assert journal.pending == {}
    journal_bytes = journal.path.read_bytes()
    assert token not in journal_bytes
    assert token.hex().encode() not in journal_bytes
    assert b'"operation":"authorization_consume"' in journal_bytes
    journal.close()

    restarted = _authorization_store(tmp_path / "external-state", role)
    replay_journal = StagingJournal(tmp_path / "journal-replay", synthetic=True)
    with pytest.raises(ConnectivityError) as raised:
        restarted.consume(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=replay_journal,
        )
    assert raised.value.code == "staging_authorization_replayed"
    # Replay is now rejected by the retained attempt claim before a new intent.
    assert replay_journal.pending == {}
    replay_journal.close()


@pytest.mark.parametrize(
    "changes, expected_project, expected_commit",
    [
        ({}, "different-project-id", AUTHORIZATION_TEST_COMMIT),
        ({}, "synthetic-staging-project-id", "b" * 40),
        (
            {"billing_owner_acknowledged": False},
            "synthetic-staging-project-id",
            AUTHORIZATION_TEST_COMMIT,
        ),
        ({"approved": True}, "synthetic-staging-project-id", AUTHORIZATION_TEST_COMMIT),
    ],
)
def test_offline_capability_store_rejects_scope_mismatch_and_forged_claims(
    tmp_path, changes, expected_project, expected_commit
):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "external-state", role)
    if "approved" in changes or "billing_owner_acknowledged" in changes:
        claims = _staging_issue_claims()
        claims.update(changes)
        with pytest.raises(ConnectivityError) as raised:
            store.issue(
                claims,
                expected_project_id="synthetic-staging-project-id",
                expected_source_commit=AUTHORIZATION_TEST_COMMIT,
                expected_binding=AUTHORIZATION_TEST_BINDING,
                now_utc=AUTHORIZATION_TEST_NOW,
            )
        assert raised.value.code == "staging_authorization_claims_invalid"
        assert list(store.issued_root.iterdir()) == []
        return

    capability = _issue_offline_capability(store, **changes)
    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "journal", synthetic=True)
    with pytest.raises(ConnectivityError) as raised:
        store.consume(
            capability,
            expected_project_id=expected_project,
            expected_source_commit=expected_commit,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=journal,
        )
    assert raised.value.code == "staging_authorization_claims_invalid"
    assert list(store.consumed_root.iterdir()) == []
    journal.close()


def test_offline_capability_store_rejects_tampering_and_wrong_capability(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "tampered-state", role)
    capability = _issue_offline_capability(store)
    record_path = store.issued_root / f"{capability.authorization_id}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["claims"]["project_id"] = "forged-project-id"
    record_path.write_bytes(store._canonical_bytes(record))

    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "tampered-journal", synthetic=True)
    with pytest.raises(ConnectivityError) as raised:
        store.consume(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=journal,
        )
    assert raised.value.code == "staging_authorization_claims_invalid"
    assert list(store.consumed_root.iterdir()) == []
    journal.close()

    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "wrong-capability-state", role)
    capability = _issue_offline_capability(store)
    wrong = IssuedStagingCapability(capability.authorization_id, b"x" * 32)
    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "wrong-capability-journal", synthetic=True)
    with pytest.raises(ConnectivityError) as raised:
        store.consume(
            wrong,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=journal,
        )
    assert raised.value.code == "staging_authorization_capability_invalid"
    assert list(store.consumed_root.iterdir()) == []
    journal.close()


def test_offline_capability_store_enforces_expiry_and_short_window(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "expiry-state", role)
    capability = _issue_offline_capability(store)
    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "expiry-journal", synthetic=True)
    with pytest.raises(ConnectivityError) as raised:
        store.consume(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW + timedelta(minutes=6),
            journal=journal,
        )
    assert raised.value.code == "staging_authorization_claims_invalid"
    assert list(store.consumed_root.iterdir()) == []
    journal.close()

    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "long-window-state", role)
    with pytest.raises(ConnectivityError) as raised:
        _issue_offline_capability(
            store,
            expires_at="2026-10-23T12:16:00Z",
        )
    assert raised.value.code == "staging_authorization_claims_invalid"
    assert list(store.issued_root.iterdir()) == []


def test_offline_capability_store_rejects_role_escalation_and_same_identity(tmp_path):
    role = {"value": "synthetic-runtime"}
    store = _authorization_store(tmp_path / "role-state", role)
    with pytest.raises(ConnectivityError) as raised:
        _issue_offline_capability(store)
    assert raised.value.code == "staging_authorization_issuer_identity_mismatch"
    assert list(store.issued_root.iterdir()) == []

    with pytest.raises(harness_module.DurabilityError):
        OfflineStagingAuthorizationStore(
            tmp_path / "same-role-state",
            synthetic=True,
            issuer_role="same-role",
            runtime_role="same-role",
            current_role=lambda: "same-role",
        )
    with pytest.raises(harness_module.DurabilityError):
        OfflineStagingAuthorizationStore(
            tmp_path / "non-synthetic-state",
            synthetic=False,
            issuer_role="issuer",
            runtime_role="runtime",
            current_role=lambda: "runtime",
        )


def test_offline_capability_store_fsync_failures_never_return_consumption(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "intent-failure-state", role)
    capability = _issue_offline_capability(store)
    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "intent-failure-journal", synthetic=True)

    def fail_journal_fsync(_descriptor):
        raise OSError("synthetic journal fsync failure")

    journal._fsync = fail_journal_fsync
    with pytest.raises(harness_module.DurabilityError):
        store.consume(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=journal,
        )
    # Consumption-start evidence survives even when the journal intent fails.
    assert list(store.consumed_root.glob("*.claimed"))
    assert list(store.consumed_root.glob("*.consumed")) == []
    journal.close()

    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "marker-failure-state", role)
    capability = _issue_offline_capability(store)
    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "marker-failure-journal", synthetic=True)

    def fail_marker_fsync(_descriptor):
        raise OSError("synthetic consumed-marker fsync failure")

    store._fsync = fail_marker_fsync
    with pytest.raises(ConnectivityError) as raised:
        store.consume(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=journal,
        )
    assert raised.value.code == "staging_authorization_durability_uncertain"
    assert list(store.consumed_root.iterdir())
    journal.close()

    store._fsync = os.fsync
    retry_journal = StagingJournal(tmp_path / "marker-retry-journal", synthetic=True)
    with pytest.raises(ConnectivityError) as replay:
        store.consume(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=retry_journal,
        )
    assert replay.value.code == "staging_authorization_replayed"
    retry_journal.close()


def test_offline_capability_store_directory_fsync_failure_burns_capability(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "directory-failure-state", role)
    capability = _issue_offline_capability(store)
    role["value"] = "synthetic-runtime"
    store._sync_directory = lambda _path: (_ for _ in ()).throw(OSError("injected fsync"))
    journal = StagingJournal(tmp_path / "directory-failure-journal", synthetic=True)
    with pytest.raises(ConnectivityError) as raised:
        store.consume(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=journal,
        )
    assert raised.value.code == "staging_authorization_durability_uncertain"
    assert list(store.consumed_root.iterdir())
    journal.close()


def test_offline_capability_store_journal_outcome_failure_keeps_consumed_marker(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "outcome-failure-state", role)
    capability = _issue_offline_capability(store)
    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "outcome-failure-journal", synthetic=True)
    fsync_calls = 0

    def fail_outcome_fsync(descriptor):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("synthetic outcome fsync failure")
        os.fsync(descriptor)

    journal._fsync = fail_outcome_fsync
    with pytest.raises(harness_module.DurabilityError):
        store.consume(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
            journal=journal,
        )
    assert fsync_calls == 2
    assert (store.consumed_root / f"{capability.authorization_id}.consumed").exists()
    journal.close()


def test_offline_capability_store_subprocess_consumption_is_single_use(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "process-state", role)
    capability = _issue_offline_capability(store)
    start_path = tmp_path / "release-processes"
    ready_root = tmp_path / "ready"
    ready_root.mkdir()
    child_code = r"""
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location("f09_auth_child", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
data = json.load(sys.stdin)
store = module.OfflineStagingAuthorizationStore(
    Path(data["root"]), synthetic=True, issuer_role="synthetic-issuer",
    runtime_role="synthetic-runtime", current_role=lambda: "synthetic-runtime",
)
journal = module.StagingJournal(Path(data["journal"]), synthetic=True)
Path(data["ready"]).write_text("ready", encoding="ascii")
deadline = time.monotonic() + 5
while not Path(data["start"]).exists():
    if time.monotonic() > deadline:
        raise SystemExit(4)
    time.sleep(0.005)
capability = module.IssuedStagingCapability(data["authorization_id"], bytes.fromhex(data["token"]))
try:
    store.consume(capability, expected_project_id="synthetic-staging-project-id",
        expected_source_commit="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        expected_binding=module.StagingAuthorizationBinding(
            "F09-synthetic-attempt", "c" * 64, "d" * 64, 200),
        now_utc=datetime(2026, 10, 23, 12, 0, tzinfo=UTC), journal=journal)
except module.ConnectivityError as error:
    print("rejected:" + error.code)
else:
    print("consumed")
finally:
    journal.close()
"""
    data = {
        "root": str(tmp_path / "process-state"),
        "authorization_id": capability.authorization_id,
        "token": capability._value.hex(),
        "start": str(start_path),
    }
    executable = [
        sys.executable,
        "-c",
        child_code,
        str(Path(harness_module.__file__).resolve()),
    ]
    environment = {"PATH": os.defpath}
    if os.name == "nt" and os.environ.get("SystemRoot"):
        environment["SystemRoot"] = os.environ["SystemRoot"]
    processes = []
    results = []
    try:
        for index in range(2):
            child_data = dict(data)
            child_data["journal"] = str(tmp_path / f"process-journal-{index}")
            child_data["ready"] = str(ready_root / str(index))
            process = subprocess.Popen(
                executable,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            assert process.stdin is not None
            process.stdin.write(json.dumps(child_data))
            process.stdin.close()
            process.stdin = None
            processes.append(process)
        deadline = time.monotonic() + 5
        while len(list(ready_root.iterdir())) != 2:
            if time.monotonic() > deadline:
                pytest.fail("authorization consumers did not reach the start barrier")
            time.sleep(0.01)
        start_path.touch()
        for process in processes:
            stdout, stderr = process.communicate(timeout=8)
            assert process.returncode == 0, stderr
            results.append(stdout.strip())
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    assert sorted(results) == [
        "consumed",
        "rejected:staging_authorization_replayed",
    ]
    restart_data = dict(data)
    restart_data["journal"] = str(tmp_path / "process-journal-restart")
    restart_data["ready"] = str(ready_root / "restart")
    restarted = subprocess.run(
        executable,
        input=json.dumps(restart_data),
        text=True,
        capture_output=True,
        timeout=8,
        env=environment,
        check=False,
    )
    assert restarted.returncode == 0, restarted.stderr
    assert restarted.stdout.strip() == "rejected:staging_authorization_replayed"


def test_worker_result_after_timeout_is_disposed_exactly_once():
    started = threading.Event()
    finish = threading.Event()
    disposed = threading.Event()
    values = []

    def operation():
        started.set()
        finish.wait(1)
        return "synthetic-effect"

    def cleanup(value):
        values.append(value)
        disposed.set()

    with pytest.raises(TimeoutError):
        harness_module._bounded_call(
            operation, deadline=time.monotonic() + 0.03, clock=time.monotonic, late_cleanup=cleanup
        )
    assert started.is_set()
    finish.set()
    assert disposed.wait(1)
    assert values == ["synthetic-effect"]


def test_late_session_create_is_recorded_and_deleted_once(tmp_path):
    started = threading.Event()
    finish = threading.Event()

    class SlowCreateAPI(FakeAPI):
        def create_session(self, agent_config, *, timeout):
            self.created += 1
            started.set()
            assert timeout > 0
            finish.wait(2)
            return {
                "session_id": SESSION_ID,
                "environment_id": ENVIRONMENT_ID,
                "remote_url": REMOTE_URL,
            }

    api = SlowCreateAPI([])
    harness, lease, journal = _make(
        tmp_path, api, FakeExecutor(), create_seconds=0.03, cleanup_seconds=1
    )
    result = []
    errors = []

    def run_harness():
        try:
            result.append(harness.run())
        except Exception as exc:  # Safe test capture; no exception text is emitted.
            errors.append(type(exc))

    worker = threading.Thread(target=run_harness)
    worker.start()
    assert started.wait(1)
    time.sleep(0.05)
    finish.set()
    worker.join(2)

    assert not worker.is_alive()
    assert errors == []
    assert api.created == 1
    assert api.deleted == [SESSION_ID]
    assert result[0]["session_creation_outcome"] == "created_late"
    assert result[0]["session_deletion_verified"] is True
    assert result[0]["cleanup_verified"] is True
    entries = [json.loads(line) for line in journal.path.read_text().splitlines()]
    deletes = [entry for entry in entries if entry["operation"] == "session_delete"]
    assert len(deletes) == 2
    assert deletes[0]["event"] == "intent"
    assert deletes[0]["resource_sha256"] == harness_module._sha256(SESSION_ID)
    assert deletes[1]["event"] == "outcome"
    assert deletes[1]["code"] == "ok"
    assert not lease.lock_path.exists()


@pytest.mark.parametrize("release_after_budget", [False, True])
def test_late_executor_completion_uses_one_cleanup_budget(tmp_path, release_after_budget):
    started = threading.Event()
    finish = threading.Event()
    api = FakeAPI([_event("agent.session.environment.connected")])
    executor = FakeExecutor()
    stop_calls = []

    def start(_session, *, environment_key, timeout):
        started.set()
        finish.wait(2)
        return "synthetic-late-container-id"

    def stop(identity, *, timeout):
        stop_calls.append((identity, timeout))
        return True

    executor.start = start
    executor.stop_verified = stop
    cleanup_seconds = 0.03 if release_after_budget else 1
    harness, lease, journal = _make(
        tmp_path,
        api,
        executor,
        connect_seconds=0.03,
        cleanup_seconds=cleanup_seconds,
    )
    errors = []

    def run_harness():
        try:
            harness.run()
        except Exception as exc:
            errors.append(type(exc))

    worker = threading.Thread(target=run_harness)
    worker.start()
    assert started.wait(1)
    time.sleep(0.06)
    if release_after_budget:
        worker.join(1)
        assert not worker.is_alive()
        assert errors == [ConnectivityError]
        assert stop_calls == []
        assert lease.lock_path.exists()
    finish.set()
    worker.join(2)
    assert not worker.is_alive()
    if release_after_budget:
        deadline = time.monotonic() + 1
        while journal.fd is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert stop_calls == []
    else:
        assert errors == []
        assert stop_calls == [("synthetic-late-container-id", pytest.approx(1, abs=0.2))]
        assert not lease.lock_path.exists()
    entries = [json.loads(line) for line in journal.path.read_text().splitlines()]
    stop_entries = [entry for entry in entries if entry["operation"] == "executor_stop"]
    assert stop_entries[0]["event"] == "intent"
    assert stop_entries[0]["resource_sha256"] == harness_module._sha256(
        "synthetic-late-container-id"
    )
    assert stop_entries[1]["event"] == "outcome"
    assert stop_entries[1]["code"] == ("cleanup_deadline_expired" if release_after_budget else "ok")


def test_expired_worker_does_not_start_operation():
    calls = []
    with pytest.raises(TimeoutError):
        harness_module._bounded_call(lambda: calls.append("forbidden"), deadline=0, clock=lambda: 1)
    assert calls == []


def test_oversized_unterminated_sse_line_is_rejected_during_reception():
    chunks = (b"x" * 4096 for _ in range(1000))
    with pytest.raises(ConnectivityError) as raised:
        list(StagingAgentsClient._bounded_lines(chunks))
    assert raised.value.code == "stream_line_limit"


def test_stop_exception_still_attempts_topology_cleanup():
    calls = []

    class Runtime:
        def stop_managed_executor(self, _identity):
            calls.append("stop")
            raise RuntimeError("synthetic secret exception")

    class Topology:
        def cleanup(self):
            calls.append("topology")
            return True

    adapter = DockerExecutorAdapter(Runtime(), Topology(), Path("."), "172.20.0.1")
    assert adapter.stop_verified("a" * 64, timeout=1) is False
    assert calls == ["stop", "topology"]


def test_shared_cleanup_budget_blocks_delete_after_exhaustion(tmp_path):
    clock = FakeClock()
    api = FakeAPI(
        [{"type": "agent.session.environment.connected", "environment_id": ENVIRONMENT_ID}]
    )
    executor = FakeExecutor()

    def stop(_identity, *, timeout):
        clock.advance(6)
        return True

    executor.stop_verified = stop
    harness, lease, _ = _make(tmp_path, api, executor, clock=clock)
    with pytest.raises(ConnectivityError):
        harness.run()
    assert api.deleted == []
    assert lease.lock_path.exists()


def test_short_audit_write_retains_lease(tmp_path, monkeypatch):
    api = FakeAPI(
        [{"type": "agent.session.environment.connected", "environment_id": ENVIRONMENT_ID}]
    )
    harness, lease, _ = _make(tmp_path, api, FakeExecutor())
    original = harness_module.os.fdopen

    class ShortWriter:
        def __init__(self, fd, mode):
            self.output = original(fd, mode)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.output.close()

        def write(self, data):
            return self.output.write(data[:1])

    monkeypatch.setattr(harness_module.os, "fdopen", ShortWriter)
    with pytest.raises(ConnectivityError):
        harness.run()
    assert lease.lock_path.exists()


def test_journal_inspector_rejects_partial_tail_and_reports_pending(tmp_path):
    journal = StagingJournal(tmp_path, synthetic=True)
    journal.append("session_create", "intent")
    journal.close()
    report = harness_module.inspect_staging_journal(journal.path)
    assert report["integrity"] == "valid"
    assert report["pending_intents"] == [1]
    assert report["recovery_authorized"] is False
    assert report["synthetic"] is True
    original = journal.path.read_bytes()
    with journal.path.open("ab") as output:
        output.write(b"{partial")
    report = harness_module.inspect_staging_journal(journal.path)
    assert report["integrity"] == "corrupt"
    assert report["cleanup_complete"] is False
    assert report["recovery_authorized"] is False
    assert journal.path.read_bytes() == original + b"{partial"


def test_journal_inspector_rejects_wrong_types_and_inconsistent_pairs(tmp_path):
    malformed = {
        "schema_version": 1,
        "record_type": "managed_agents_connectivity_journal_not_benchmark_result",
        "synthetic": True,
        "seq": True,
        "operation": "session_create",
        "event": "intent",
        "intent_seq": None,
        "code": "ok",
        "resource_sha256": None,
        "previous_sha256": "0" * 64,
    }
    path = tmp_path / "malformed.jsonl"
    path.write_text(json.dumps(malformed, separators=(",", ":")) + "\n")
    before = path.read_bytes()
    report = harness_module.inspect_staging_journal(path)
    assert report["integrity"] == "corrupt"
    assert report["recovery_authorized"] is False
    assert path.read_bytes() == before

    journal = StagingJournal(tmp_path / "pair", synthetic=True)
    seq = journal.append("session_delete", "intent", resource_sha256="a" * 64)
    with pytest.raises(harness_module.DurabilityError):
        journal.append(
            "session_delete",
            "outcome",
            intent_seq=seq,
            code="ok",
            resource_sha256="b" * 64,
        )
    journal.close()
    report = harness_module.inspect_staging_journal(journal.path)
    assert report["integrity"] == "valid"
    assert report["pending_intents"] == [1]
    assert report["durable_release_authorization"] is False
    assert report["cleanup_complete"] is False

    duplicate = StagingJournal(tmp_path / "duplicate", synthetic=True)
    for _ in range(2):
        repeated = duplicate.append("session_create", "intent")
        duplicate.append("session_create", "outcome", intent_seq=repeated)
    duplicate.close()
    assert harness_module.inspect_staging_journal(duplicate.path)["integrity"] == "corrupt"

    reordered = StagingJournal(tmp_path / "reordered", synthetic=True)
    release = reordered.append("lease_release", "intent")
    reordered.append("lease_release", "outcome", intent_seq=release, code="release_authorized")
    reordered.close()
    report = harness_module.inspect_staging_journal(reordered.path)
    assert report["integrity"] == "corrupt"
    assert report["recovery_authorized"] is False


def test_late_topology_start_cannot_begin_executor_start():
    calls = []

    class Topology:
        def start(self):
            time.sleep(0.02)
            return {"proxy_internal_ip": "172.20.0.2"}

        def cleanup(self):
            calls.append("cleanup")
            return True

    class Runtime:
        def start_managed_executor(self, *_args, **_kwargs):
            calls.append("forbidden_start")

    adapter = DockerExecutorAdapter(Runtime(), Topology(), Path("."), "172.20.0.1")
    with pytest.raises(ConnectivityError):
        adapter.start({}, environment_key=ENV_KEY, timeout=0.001)
    assert adapter.stop_verified(None, timeout=1) is False
    assert calls == ["cleanup"]


def test_live_harness_rejects_missing_solo_operator_entry_point():
    from types import SimpleNamespace

    root = Path("synthetic-scope")
    concrete_client = object.__new__(StagingAgentsClient)
    concrete_client.synthetic = False
    concrete_client._live_capability = harness_module._LIVE_CLIENT_CAPABILITY
    with pytest.raises(
        ValueError, match="Live connectivity requires the F09 solo-operator entry point"
    ):
        ConnectivityHarness(
            client=concrete_client,
            executor=FakeExecutor(),
            journal=SimpleNamespace(synthetic=False, root=root / "run"),
            lease=SimpleNamespace(synthetic=False, root=root),
            agent_config=AGENT,
            environment_key=ENV_KEY,
        )


def test_live_harness_rejects_arbitrary_client_even_if_marked_live():
    from types import SimpleNamespace

    root = Path("synthetic-scope")
    with pytest.raises(ValueError, match="concrete reviewed client"):
        ConnectivityHarness(
            client=SimpleNamespace(synthetic=False),
            executor=object(),
            journal=SimpleNamespace(synthetic=False, root=root / "run"),
            lease=SimpleNamespace(synthetic=False, root=root),
            agent_config=AGENT,
            environment_key=ENV_KEY,
        )


@pytest.mark.parametrize("limit", ["event", "total"])
def test_chunk_sse_aggregate_limits(monkeypatch, limit):
    monkeypatch.setattr(harness_module, "MAX_SSE_EVENT_BYTES", 20 if limit == "event" else 1000)
    monkeypatch.setattr(harness_module, "MAX_SSE_TOTAL_BYTES", 20 if limit == "total" else 1000)
    with pytest.raises(ConnectivityError) as raised:
        list(StagingAgentsClient._bounded_lines([b"data: x\n" for _ in range(5)]))
    assert raised.value.code == "stream_" + limit + "_limit"


def _scope_attestation(**changes):
    return {
        "verification_method": "operator_dashboard_attestation",
        "organization_id": "org_synthetic",
        "project_id": "synthetic-staging-project-id",
        "owner_id": "synthetic-service-account",
        "application_key_resource_id": "synthetic-application-resource",
        "environment_key_label": "synthetic-environment-label",
        "operator_id": "synthetic-operator",
        "reviewer_id": "synthetic-reviewer",
        "application_permissions": ["api.agents.read", "api.agents.write"],
        "environment_permissions": ["api.agents.environments.connect"],
        "matching_organization_project_owner_confirmed": True,
        "reviewed_at": "2026-10-23T12:00:00Z",
        **changes,
    }


def _authorized_rehearsal(
    tmp_path,
    *,
    on_request=None,
    executor=None,
    create_status=200,
    create_error_body=None,
):
    attestation = _scope_attestation()
    binding = harness_module.StagingAuthorizationBinding(
        "F09-synthetic-bound-attempt",
        harness_module.connectivity_configuration_sha256(
            AGENT, create_seconds=10, connect_seconds=10, cleanup_seconds=5
        ),
        harness_module.unverified_credential_scope_sha256(
            attestation, expected_project_id=attestation["project_id"]
        ),
        200,
    )
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "authorization", role)
    capability = store.issue(
        _staging_issue_claims(
            attempt_id=binding.attempt_id,
            configuration_sha256=binding.configuration_sha256,
            credential_scope_sha256=binding.credential_scope_sha256,
        ),
        expected_project_id=attestation["project_id"],
        expected_source_commit=AUTHORIZATION_TEST_COMMIT,
        expected_binding=binding,
        now_utc=AUTHORIZATION_TEST_NOW,
    )
    role["value"] = "synthetic-runtime"
    plan = harness_module.SyntheticStagingAuthorization(
        store,
        capability,
        binding,
        project_id=attestation["project_id"],
        source_commit=AUTHORIZATION_TEST_COMMIT,
        attestation=attestation,
        now_utc=lambda: AUTHORIZATION_TEST_NOW,
    )
    api, calls = _http_client(
        tmp_path,
        [_event("agent.session.environment.connected")],
        project_id=attestation["project_id"],
        spend_approval=SpendControlApproval(200, "synthetic-billing-approval", True),
        on_request=on_request,
        create_status=create_status,
        create_error_body=create_error_body,
    )
    harness, lease, journal = _make(
        tmp_path / "lifecycle", api, executor or FakeExecutor(), synthetic_authorization=plan
    )
    return harness, lease, journal, plan, calls


def test_bound_authorization_has_no_default_or_inherited_spend_approval():
    claims = _unverified_staging_claims(spend_control_limit_cents=100)
    binding = harness_module.StagingAuthorizationBinding(
        AUTHORIZATION_TEST_BINDING.attempt_id, "c" * 64, "d" * 64, 100
    )
    parsed = harness_module.parse_unverified_staging_authorization_claims(
        claims,
        expected_project_id="synthetic-staging-project-id",
        expected_source_commit=AUTHORIZATION_TEST_COMMIT,
        expected_binding=binding,
        now_utc=AUTHORIZATION_TEST_NOW,
    )
    assert parsed["spend_control_limit_cents"] == 100
    assert parsed["billing_risk_acknowledged"] is True
    with pytest.raises(ConnectivityError):
        harness_module.parse_unverified_staging_authorization_claims(
            claims,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            now_utc=AUTHORIZATION_TEST_NOW,
        )
    with pytest.raises(AttributeError):
        binding.limit = 200


@pytest.mark.parametrize(
    "changes",
    [
        {"application_permissions": ["api.agents.read", "api.agents.write", "api.responses.write"]},
        {"application_permissions": ("api.agents.read", "api.agents.write")},
        {"application_permissions": ["api.agents.read", True]},
        {"environment_permissions": None},
        {"environment_permissions": ["api.agents.write"]},
        {"matching_organization_project_owner_confirmed": False},
        {"project_id": "different-project"},
        {"verification_method": "provider_verified"},
        {"application_key_resource_id": "sk-" + "x" * 60},
        {"environment_key_label": "https://example.invalid/?token=synthetic"},
    ],
)
def test_scope_attestation_rejects_unsafe_metadata_without_claiming_provider_verification(changes):
    with pytest.raises(ConnectivityError) as raised:
        harness_module.unverified_credential_scope_sha256(
            _scope_attestation(**changes), expected_project_id="synthetic-staging-project-id"
        )
    assert raised.value.code == "staging_credential_attestation_invalid"
    assert str(changes) not in str(raised.value)


def test_scope_and_configuration_digests_preserve_input_and_detect_parameter_changes():
    attestation = _scope_attestation()
    before = json.dumps(attestation, sort_keys=True)
    digest = harness_module.unverified_credential_scope_sha256(
        attestation, expected_project_id=attestation["project_id"]
    )
    assert len(digest) == 64
    assert json.dumps(attestation, sort_keys=True) == before
    first = harness_module.connectivity_configuration_sha256(
        AGENT, create_seconds=10, connect_seconds=10, cleanup_seconds=5
    )
    assert first != harness_module.connectivity_configuration_sha256(
        AGENT, create_seconds=10, connect_seconds=10, cleanup_seconds=4
    )
    with pytest.raises(ConnectivityError):
        harness_module.connectivity_configuration_sha256(
            AGENT, create_seconds=True, connect_seconds=10, cleanup_seconds=5
        )


def test_authorization_rehearsal_consumes_durably_before_the_only_session_post(tmp_path, capsys):
    observations = []

    def observe(request):
        if request.method == "POST":
            records = [json.loads(line) for line in journal.path.read_text().splitlines()]
            assert list(plan.store.consumed_root.glob("*.claimed"))
            assert (
                plan.store.consumed_root / f"{plan.capability.authorization_id}.consumed"
            ).exists()
            assert any(
                row["operation"] == "authorization_consume"
                and row["event"] == "outcome"
                and row["code"] == "consumed"
                for row in records
            )
            assert lease.acquired is True
            observations.append("durable_consumption_before_post")

    harness, lease, journal, plan, calls = _authorized_rehearsal(tmp_path, on_request=observe)
    audit = harness.run()
    assert observations == ["durable_consumption_before_post"]
    assert [request.method for request in calls] == ["POST", "GET", "DELETE"]
    assert audit["approval_consumption_durable"] is True
    assert audit["cleanup_verified"] is True
    assert audit["task_submission_count"] == audit["responses_calls"] == 0
    assert lease.acquired is False
    saved = _saved_audit(lease)
    assert saved["approval_consumption_durable"] is True
    assert saved["cleanup_verified"] is True
    evidence = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    captured = capsys.readouterr()
    for value in (APP_KEY, ENV_KEY, REMOTE_URL, plan.capability._value.hex()):
        assert value.encode() not in evidence
        assert value not in captured.out + captured.err


@pytest.mark.parametrize(
    "mismatch",
    ["attempt", "commit", "project", "configuration", "scope", "limit", "missing", "expired"],
)
def test_authorization_rehearsal_rejects_request_mismatch_before_lease_or_transport(
    tmp_path, mismatch
):
    harness, lease, _, plan, calls = _authorized_rehearsal(tmp_path)
    if mismatch == "attempt":
        plan.binding = harness_module.StagingAuthorizationBinding(
            "F09-other-attempt",
            plan.binding.configuration_sha256,
            plan.binding.credential_scope_sha256,
            200,
        )
    elif mismatch == "commit":
        plan.source_commit = "b" * 40
    elif mismatch == "project":
        plan.project_id = "other-project"
    elif mismatch == "configuration":
        harness.connect_seconds = 9
    elif mismatch == "scope":
        plan.attestation["owner_id"] = "other-owner"
    elif mismatch == "limit":
        harness.client._spend_control_approval = SpendControlApproval(
            100, "synthetic-billing-approval", True
        )
    elif mismatch == "missing":
        plan.capability = None
    else:
        plan.now_utc = lambda: AUTHORIZATION_TEST_NOW + timedelta(minutes=6)
    with pytest.raises(ConnectivityError):
        harness.run()
    assert calls == []
    assert not lease.lock_path.exists()
    assert not list(plan.store.consumed_root.iterdir())


def test_authorization_rehearsal_journal_failure_burns_attempt_and_retains_lease(tmp_path):
    harness, lease, journal, plan, calls = _authorized_rehearsal(tmp_path)
    journal._fsync = lambda _fd: (_ for _ in ()).throw(OSError("synthetic journal fault"))
    with pytest.raises(harness_module.DurabilityError):
        harness.run()
    assert calls == []
    assert lease.acquired and lease.lock_path.exists()
    assert list(plan.store.consumed_root.glob("*.claimed"))
    restarted = StagingJournal(tmp_path / "restarted-journal", synthetic=True)
    try:
        with pytest.raises(ConnectivityError) as raised:
            plan.consume(restarted)
        assert raised.value.code == "staging_authorization_replayed"
    finally:
        restarted.close()


@pytest.mark.parametrize("failure", ["ambiguous-create", "cleanup-unverified"])
def test_authorization_rehearsal_failure_never_reuses_approval_or_certifies_cleanup(
    tmp_path, failure
):
    harness, lease, _, plan, calls = _authorized_rehearsal(
        tmp_path,
        create_status=500 if failure == "ambiguous-create" else 200,
        executor=FakeExecutor(stop=failure != "cleanup-unverified"),
    )
    with pytest.raises(ConnectivityError):
        harness.run()
    assert len([request for request in calls if request.method == "POST"]) == 1
    assert lease.lock_path.exists()
    assert _saved_audit(lease)["cleanup_verified"] is False
    journal = StagingJournal(tmp_path / "second-journal", synthetic=True)
    try:
        with pytest.raises(ConnectivityError) as raised:
            plan.consume(journal)
        assert raised.value.code == "staging_authorization_replayed"
    finally:
        journal.close()


def test_failed_second_consumption_write_preserves_attempt_guard_and_prevents_reissue(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "store", role)
    capability = _issue_offline_capability(store)
    second_capability = _issue_offline_capability(store)
    role["value"] = "synthetic-runtime"
    journal = StagingJournal(tmp_path / "journal", synthetic=True)
    write_calls = 0

    def fail_final(descriptor, payload):
        nonlocal write_calls
        write_calls += 1
        if write_calls == 2:
            raise PermissionError("synthetic final marker denied")
        return os.write(descriptor, payload)

    store._write = fail_final
    try:
        with pytest.raises(ConnectivityError) as failure:
            store.consume(
                capability,
                expected_project_id="synthetic-staging-project-id",
                expected_source_commit=AUTHORIZATION_TEST_COMMIT,
                expected_binding=AUTHORIZATION_TEST_BINDING,
                now_utc=AUTHORIZATION_TEST_NOW,
                journal=journal,
            )
        assert failure.value.code == "staging_authorization_durability_uncertain"
        assert list(store.consumed_root.glob("*.claimed"))
        # O_EXCL creates the final marker before the injected write fails.
        # Keep that empty evidence, without a matching successful outcome.
        incomplete = store.consumed_root / f"{capability.authorization_id}.consumed"
        assert incomplete.exists() and incomplete.stat().st_size == 0
        assert journal.pending
        assert not any(
            record["operation"] == "authorization_consume" and record["event"] == "outcome"
            for record in map(json.loads, journal.path.read_text().splitlines())
        )
    finally:
        journal.close()
    store._write = os.write
    replay_journal = StagingJournal(tmp_path / "replay-journal", synthetic=True)
    try:
        with pytest.raises(ConnectivityError) as raised:
            store.consume(
                second_capability,
                expected_project_id="synthetic-staging-project-id",
                expected_source_commit=AUTHORIZATION_TEST_COMMIT,
                expected_binding=AUTHORIZATION_TEST_BINDING,
                now_utc=AUTHORIZATION_TEST_NOW,
                journal=replay_journal,
            )
        assert raised.value.code == "staging_authorization_replayed"
    finally:
        replay_journal.close()


@pytest.mark.skipif(os.name == "nt", reason="Linux replacement of an open file required")
def test_approval_record_replacement_during_read_is_rejected(tmp_path, monkeypatch):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "store", role)
    capability = _issue_offline_capability(store)
    path = store.issued_root / f"{capability.authorization_id}.json"
    role["value"] = "synthetic-runtime"
    read = harness_module.os.read

    def replace_record(descriptor, length):
        raw = read(descriptor, length)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(raw)
        replacement.replace(path)
        return raw

    monkeypatch.setattr(harness_module.os, "read", replace_record)
    with pytest.raises(ConnectivityError) as raised:
        store.validate(
            capability,
            expected_project_id="synthetic-staging-project-id",
            expected_source_commit=AUTHORIZATION_TEST_COMMIT,
            expected_binding=AUTHORIZATION_TEST_BINDING,
            now_utc=AUTHORIZATION_TEST_NOW,
        )
    assert raised.value.code == "staging_authorization_record_invalid"
    assert not list(store.consumed_root.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="Linux symlink and mode semantics required")
def test_approval_symlink_and_nonprivate_file_are_rejected(tmp_path):
    role = {"value": "synthetic-issuer"}
    store = _authorization_store(tmp_path / "store", role)
    capability = _issue_offline_capability(store)
    path = store.issued_root / f"{capability.authorization_id}.json"
    target = path.with_suffix(".original")
    path.rename(target)
    path.symlink_to(target)
    role["value"] = "synthetic-runtime"
    arguments = {
        "expected_project_id": "synthetic-staging-project-id",
        "expected_source_commit": AUTHORIZATION_TEST_COMMIT,
        "expected_binding": AUTHORIZATION_TEST_BINDING,
        "now_utc": AUTHORIZATION_TEST_NOW,
    }
    with pytest.raises(ConnectivityError):
        store.validate(capability, **arguments)
    path.unlink()  # Only this synthetic fixture's link; no recovery marker is removed.
    target.rename(path)
    path.chmod(0o644)
    with pytest.raises(ConnectivityError):
        store.validate(capability, **arguments)
    assert not list(store.consumed_root.iterdir())


def test_no_production_store_or_live_gate_can_be_unlocked_by_synthetic_roles():
    from types import SimpleNamespace

    # No filesystem operations or role callbacks can manufacture a trusted store.
    for root in (Path("/mnt/c/unopened-f09-store"), Path("/var/lib/unopened-f09-store")):
        with pytest.raises(harness_module.DurabilityError, match="OS boundary is unavailable"):
            OfflineStagingAuthorizationStore(
                root,
                synthetic=False,
                issuer_role="issuer",
                runtime_role="runtime",
                current_role=lambda: "issuer",
            )
    client = object.__new__(StagingAgentsClient)
    client.synthetic = False
    client._live_capability = harness_module._LIVE_CLIENT_CAPABILITY
    root = Path("unopened-synthetic-evidence")
    with pytest.raises(
        ValueError, match="Live connectivity requires the F09 solo-operator entry point"
    ):
        ConnectivityHarness(
            client=client,
            executor=object.__new__(DockerExecutorAdapter),
            journal=SimpleNamespace(synthetic=False, root=root / "run"),
            lease=SimpleNamespace(synthetic=False, root=root),
            agent_config=AGENT,
            environment_key=ENV_KEY,
        )


class _SoloTerminal(io.StringIO):
    """Synthetic terminal only; real mode rejects injected I/O boundaries."""

    def __init__(self, *, accept=True, tty=True):
        super().__init__()
        self.accept, self.tty = accept, tty
        self.confirmations = []

    def isatty(self):
        return self.tty

    def readline(self, *_args):
        expected = self.getvalue().splitlines()[-1].removeprefix("Type exactly: ")
        self.confirmations.append(expected)
        return (expected if self.accept else "no") + "\n"


def _solo_request(limit=137):
    return {
        "schema_version": 1,
        "source_commit": AUTHORIZATION_TEST_COMMIT,
        "project_id": "synthetic-staging-project-id",
        "agent": AGENT,
        "create_seconds": 10,
        "connect_seconds": 10,
        "cleanup_seconds": 5,
        "executor_image": "sha256:" + "e" * 64,
        "spend_limit_cents": limit,
        "billing_owner_id": "synthetic-operator",
        "credential_attestation": _scope_attestation(reviewer_id="synthetic-operator"),
    }


def _solo_store(tmp_path, *, accept=True, tty=True):
    state = tmp_path / "solo-state"
    state.mkdir(mode=0o700)
    terminal = _SoloTerminal(accept=accept, tty=tty)
    current = {"now": AUTHORIZATION_TEST_NOW, "source": "f" * 64}
    store = harness_module.SoloOperatorApprovalStore(
        state,
        synthetic=True,
        source_probe=lambda _commit: current["source"],
        now_utc=lambda: current["now"],
        terminal_input=terminal,
        terminal_output=terminal,
    )
    return store, terminal, current


def _solo_lifecycle(store, *, on_request=None, stop=True, create_status=200):
    lease = StagingLease(store.state_directory, synthetic=True)
    journal = StagingJournal(store.state_directory, synthetic=True)
    api, calls = _http_client(
        store.state_directory,
        [_event("agent.session.environment.connected")],
        project_id="synthetic-staging-project-id",
        spend_approval=store.spend_approval(),
        on_request=on_request,
        create_status=create_status,
    )
    controller = ConnectivityHarness(
        client=api,
        executor=FakeExecutor(stop=stop),
        lease=lease,
        journal=journal,
        agent_config=AGENT,
        environment_key=ENV_KEY,
        clock=FakeClock(),
        create_seconds=10,
        connect_seconds=10,
        cleanup_seconds=5,
        operator_authorization=harness_module.SoloOperatorAuthorization(store, lease),
    )
    return controller, lease, journal, calls


@pytest.mark.parametrize("amount", [1, 137, 201])
def test_solo_operator_explicit_amount_and_two_confirmations_without_default(tmp_path, amount):
    store, terminal, _ = _solo_store(tmp_path)
    summary = store.approve(_solo_request(amount), expires_in_seconds=120)
    assert summary["limit_usd_cents"] == amount
    assert summary["attempt_id"].startswith("F09-")
    assert terminal.confirmations == [
        f"APPROVE {summary['attempt_id']} {amount} CENTS ONE SESSION ZERO TASKS",
        harness_module.SOLO_CONFIRMATION,
    ]
    assert "not a billing ceiling" in terminal.getvalue()
    record = store.validate()
    assert record["synthetic"] is True
    assert record["record_type"] == harness_module.SOLO_APPROVAL_TYPE
    assert record["claims"]["session_count"] == 1
    assert record["claims"]["task_count"] == 0
    assert record["claims"]["responses_inference_allowed"] is False
    assert stat.S_IMODE((store.root / "approval.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    with pytest.raises(ConnectivityError, match="connectivity check failed"):
        store.approve(_solo_request(amount), expires_in_seconds=120)


@pytest.mark.parametrize(
    "amount", [None, True, False, 0, -1, 1.0, 1.5, "137", float("nan"), float("inf")]
)
def test_solo_operator_invalid_amount_rejected_before_confirmation(tmp_path, amount):
    store, terminal, _ = _solo_store(tmp_path)
    with pytest.raises(ConnectivityError):
        store.approve(_solo_request(amount), expires_in_seconds=120)
    assert terminal.confirmations == []
    assert not (store.root / "approval.json").exists()


@pytest.mark.parametrize("case", ["cancel", "not-tty", "bad-expiration", "missing-limit"])
def test_solo_operator_never_treats_piped_or_incomplete_input_as_approval(tmp_path, case):
    store, terminal, _ = _solo_store(tmp_path, accept=case != "cancel", tty=case != "not-tty")
    request = _solo_request()
    if case == "missing-limit":
        request.pop("spend_limit_cents")
    with pytest.raises(ConnectivityError):
        store.approve(request, expires_in_seconds=901 if case == "bad-expiration" else 120)
    assert not (store.root / "approval.json").exists()
    assert not (store.root / "consumption.started").exists()
    if case != "cancel":
        assert terminal.confirmations == []


def test_solo_operator_real_mode_rejects_injected_approval_and_source_proof():
    with pytest.raises(ConnectivityError) as raised:
        harness_module.SoloOperatorApprovalStore(
            Path("/unopened-solo-state"), source_probe=lambda _commit: "f" * 64
        )
    assert raised.value.code == "solo_test_boundary_rejected"
    native = "1 0 0:1 / / rw - ext4 /dev/root rw\n"
    for kind in ("9p", "drvfs", "tmpfs", "overlay"):
        mountinfo = native + f"2 1 0:2 / /state rw - {kind} none rw\n"
        assert harness_module._solo_filesystem(Path("/state/approval"), mountinfo) == kind
    assert harness_module._solo_filesystem(Path("/home/operator/state"), native) == "ext4"


def test_solo_operator_consumption_precedes_post_and_success_requires_saved_cleanup(tmp_path):
    store, _, _ = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    observed = []

    def observe(request):
        if request.method == "POST":
            assert (store.root / "consumption.started").exists()
            assert (store.root / "consumed.json").exists()
            records = list(map(json.loads, journal.path.read_text().splitlines()))
            assert any(
                row["operation"] == "authorization_consume" and row["event"] == "outcome"
                for row in records
            )
            observed.append("consumed_before_post")

    controller, lease, journal, calls = _solo_lifecycle(store, on_request=observe)
    result = controller.run()
    assert observed == ["consumed_before_post"]
    assert [call.method for call in calls] == ["POST", "GET", "DELETE"]
    assert json.loads(calls[0].content)["spend_control"] == {"limit": 137}
    assert result["approval_consumption_durable"] is True
    assert result["cleanup_verified"] is True
    assert result["task_submission_count"] == result["responses_calls"] == 0
    assert _saved_audit(lease)["cleanup_verified"] is True
    assert not lease.lock_path.exists()


@pytest.mark.parametrize("mismatch", ["source", "expiry", "project", "config", "limit"])
def test_solo_operator_request_mismatch_fails_before_lease_and_transport(tmp_path, mismatch):
    store, _, current = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    controller, lease, _, calls = _solo_lifecycle(store)
    if mismatch == "source":
        current["source"] = "a" * 64
    elif mismatch == "expiry":
        current["now"] += timedelta(seconds=121)
    elif mismatch == "project":
        controller.client.project_id_hash = "a" * 64
    elif mismatch == "config":
        controller.connect_seconds = 9
    else:
        controller.client._spend_control_approval = SpendControlApproval(138, "manual:wrong", True)
    with pytest.raises(ConnectivityError):
        controller.run()
    assert calls == []
    assert not lease.lock_path.exists()
    assert not (store.root / "consumption.started").exists()


@pytest.mark.parametrize("fault", ["guard-fsync", "journal-intent", "final-write"])
def test_solo_operator_durability_failure_retains_state_and_lease_without_post(tmp_path, fault):
    store, _, _ = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    controller, lease, journal, calls = _solo_lifecycle(store)
    if fault == "guard-fsync":
        store._fsync = lambda _fd: (_ for _ in ()).throw(OSError("synthetic sync failure"))
    elif fault == "journal-intent":
        journal._fsync = lambda _fd: (_ for _ in ()).throw(OSError("synthetic sync failure"))
    else:
        writes = []

        def fail_final(descriptor, raw):
            writes.append(descriptor)
            return 0 if len(writes) == 2 else os.write(descriptor, raw)

        store._write = fail_final
    with pytest.raises((ConnectivityError, harness_module.DurabilityError)):
        controller.run()
    assert calls == []
    assert lease.acquired and lease.lock_path.exists()
    assert (store.root / "consumption.started").exists()
    assert store.inspect()["live_allowed"] is False
    assert store.inspect()["cleanup_verified"] is False


@pytest.mark.parametrize("case", ["ambiguous-create", "cleanup-unverified"])
def test_solo_operator_failure_cannot_reuse_approval_or_claim_clean_cleanup(tmp_path, case):
    store, _, _ = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    controller, lease, _, calls = _solo_lifecycle(
        store,
        stop=case != "cleanup-unverified",
        create_status=500 if case == "ambiguous-create" else 200,
    )
    with pytest.raises(ConnectivityError):
        controller.run()
    assert len([call for call in calls if call.method == "POST"]) == 1
    assert (store.root / "consumption.started").exists()
    assert lease.lock_path.exists()
    assert _saved_audit(lease)["cleanup_verified"] is False
    with pytest.raises(ConnectivityError):
        store.approve(_solo_request(), expires_in_seconds=120)


def test_solo_operator_inspection_is_read_only_and_never_grants_recovery(tmp_path):
    store, _, _ = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    before = {path.name: path.read_bytes() for path in store.root.iterdir()}
    report = store.inspect()
    assert report == {
        "state": "pending_review",
        "synthetic": True,
        "live_allowed": False,
        "cleanup_verified": False,
        "recovery_authorized": False,
    }
    assert {path.name: path.read_bytes() for path in store.root.iterdir()} == before
    (store.root / "approval.json").write_bytes(b"partial")
    assert store.inspect()["state"] == "corrupt"


def test_solo_operator_subprocess_replay_is_rejected_after_success(tmp_path):
    store, _, _ = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    controller, _, _, _ = _solo_lifecycle(store)
    controller.run()
    child = r"""
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
import sys
spec = importlib.util.spec_from_file_location("solo_child", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
state = Path(sys.argv[2])
store = module.SoloOperatorApprovalStore(state, synthetic=True,
    source_probe=lambda _commit: "f" * 64,
    now_utc=lambda: datetime(2026, 10, 23, 12, 0, tzinfo=UTC))
lease = module.StagingLease(state, synthetic=True)
lease.acquire()
journal = module.StagingJournal(state, synthetic=True)
try:
    store.consume(journal, lease)
except module.ConnectivityError as exc:
    if exc.code != "solo_approval_already_used_or_pending":
        raise SystemExit(3)
    print("replay_rejected")
else:
    raise SystemExit(2)
finally:
    journal.close()
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", child, harness_module.__file__, str(store.state_directory)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={"PATH": os.defpath},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "replay_rejected"
    assert (store.root / "consumption.started").exists()


def test_solo_operator_command_exposes_approve_inspect_and_scoped_run():
    path = ROOT / "benchmarks/codex_r/exploratory/f09_solo_operator.py"
    result = subprocess.run(
        [sys.executable, "-B", str(path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert (
        "approve" in result.stdout
        and "inspect" in result.stdout
        and "run" in result.stdout
        and "reconcile-preflight" in result.stdout
    )
    assert "run-one" not in result.stdout and "authorize-one" not in result.stdout


def test_preflight_reconciliation_inventory_uses_only_fixed_read_only_docker_queries(
    monkeypatch,
):
    cli = _solo_cli_module()
    calls = []
    responses = [
        b"rkmcp-probe-F09-0123456789abcdef\nunrelated-container\n",
        b"rkmcp-candidate-F09-0123456789ab\nunrelated-network\n",
    ]
    runtime = SimpleNamespace(
        F09_DOCKER_SOCKET="unix:///var/run/docker.sock",
        _operator_environment=lambda environment: {"PATH": environment.get("PATH", "")},
    )

    def bounded_run(command, *, timeout, env):
        calls.append((command, timeout, env))
        return subprocess.CompletedProcess(command, 0, responses.pop(0), b"")

    runtime._bounded_run = bounded_run
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")
    inventory = cli._f09_docker_inventory(runtime)

    assert inventory == {
        "containers": ["rkmcp-probe-F09-0123456789abcdef"],
        "networks": ["rkmcp-candidate-F09-0123456789ab"],
    }
    assert len(calls) == 2
    assert calls[0][0][3:] == ["ps", "--all", "--format", "{{.Names}}"]
    assert calls[1][0][3:] == ["network", "ls", "--format", "{{.Name}}"]
    assert all(call[0][1:3] == ["--host", "unix:///var/run/docker.sock"] for call in calls)


def _solo_cli_module():
    path = ROOT / "benchmarks/codex_r/exploratory/f09_solo_operator.py"
    spec = importlib.util.spec_from_file_location("codex_f09_solo_operator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Keep exact class identity with the synthetic harness imported by this module.
    module.harness = harness_module
    return module


def _approve_cli_store(tmp_path):
    store, _, current = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    return store, current


def _preflight_failure_state(tmp_path, *, audit_changes=None, extra_operations=()):
    store, _, _ = _solo_store(tmp_path)
    approval = store.approve(_solo_request(), expires_in_seconds=120)
    attempt_id = approval["attempt_id"]
    lease = StagingLease(store.state_directory, synthetic=True)
    lease.acquire()
    journal = StagingJournal(store.state_directory, synthetic=True)
    store.consume(journal, lease)
    preflight = journal.append("executor_preflight", "intent")
    journal.append("executor_preflight", "outcome", intent_seq=preflight, code="preflight_failed")
    audit = {
        "schema_version": 2,
        "record_type": "managed_agents_connectivity_audit_not_benchmark_result",
        "synthetic": True,
        "state": "preflight",
        "failure_code": "executor_preflight_failed",
        "session_creation_outcome": "not_attempted",
        "session_id_sha256": None,
        "environment_id_sha256": None,
        "connected_observed": False,
        "session_deletion_verified": False,
        "session_deletion_not_required": False,
        "executor_start_attempted": False,
        "executor_preflight_verified": False,
        "executor_termination_verified": False,
        "approval_consumption_durable": True,
        "cleanup_verified": False,
        "task_submission_count": 0,
        "responses_calls": 0,
        "transitions": [],
    }
    audit.update(audit_changes or {})
    audit_intent = journal.append("audit_persist", "intent")
    audit_path = journal.root / "connectivity-audit.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    audit_path.chmod(0o600)
    journal.append("audit_persist", "outcome", intent_seq=audit_intent)
    for operation in extra_operations:
        intent = journal.append(operation, "intent")
        journal.append(operation, "outcome", intent_seq=intent, code="synthetic_rejected")
    original_journal_path = journal.path
    journal.close()

    workspace_parent = store.state_directory / "f09-workspaces"
    workspace_parent.mkdir(mode=0o700)
    workspace = workspace_parent / attempt_id
    workspace.mkdir(mode=0o700)
    store.read_only = True
    return store, attempt_id, original_journal_path, audit_path, workspace


def _install_reconciliation_fakes(monkeypatch, cli, *, acl=None, inventory=None):
    runtime = cli._load_docker_runtime()
    acl = acl or "user::rwx\ngroup::---\nmask::---\nother::---\n"
    monkeypatch.setattr(
        runtime,
        "_read_f09_workspace_acl",
        lambda *_args, **_kwargs: acl,
    )
    monkeypatch.setattr(cli, "_load_docker_runtime", lambda: runtime)
    inventory_calls = []

    def read_inventory(_runtime):
        inventory_calls.append("read")
        return inventory or {"containers": [], "networks": []}

    monkeypatch.setattr(cli, "_f09_docker_inventory", read_inventory)
    return runtime, inventory_calls


def _reconciliation_rejection_snapshot(store, workspace):
    lease_root = store.state_directory / harness_module.JOURNAL_DIRNAME
    return {
        "lease": (lease_root / "active.lock").read_bytes(),
        "consumed_markers": {
            name: (store.root / name).read_bytes()
            for name in ("consumption.started", "consumed.json")
        },
        "workspace": {
            path.name: path.read_bytes() if path.is_file() else None for path in workspace.iterdir()
        },
        "run_names": sorted(path.name for path in lease_root.glob("run-*")),
        "run_files": {
            str(path.relative_to(lease_root)): path.read_bytes()
            for path in lease_root.glob("run-*/*")
            if path.is_file()
        },
        "release_markers": sorted(path.name for path in lease_root.glob("release-*")),
    }


def _assert_reconciliation_rejection_unchanged(store, workspace, snapshot):
    lease_root = store.state_directory / harness_module.JOURNAL_DIRNAME
    assert (lease_root / "active.lock").read_bytes() == snapshot["lease"]
    assert {
        name: (store.root / name).read_bytes() for name in ("consumption.started", "consumed.json")
    } == snapshot["consumed_markers"]
    assert store.inspect()["state"] == "consumed_or_uncertain"
    assert {
        path.name: path.read_bytes() if path.is_file() else None for path in workspace.iterdir()
    } == snapshot["workspace"]
    assert sorted(path.name for path in lease_root.glob("run-*")) == snapshot["run_names"]
    assert {
        str(path.relative_to(lease_root)): path.read_bytes()
        for path in lease_root.glob("run-*/*")
        if path.is_file()
    } == snapshot["run_files"]
    assert sorted(path.name for path in lease_root.glob("release-*")) == snapshot["release_markers"]
    assert not list(lease_root.glob("run-*/preflight-reconciliation.json"))


def test_preflight_reconciliation_removes_workspace_and_releases_only_verified_lease(
    tmp_path, monkeypatch
):
    cli = _solo_cli_module()
    store, attempt_id, journal_path, audit_path, workspace = _preflight_failure_state(tmp_path)
    _install_reconciliation_fakes(monkeypatch, cli)
    old_journal = journal_path.read_bytes()
    old_audit = audit_path.read_bytes()
    markers = {
        name: (store.root / name).read_bytes() for name in ("consumption.started", "consumed.json")
    }
    terminal = _SoloTerminal()

    result = cli._reconcile_preflight_failure(
        store,
        attempt_id,
        terminal_input=terminal,
        terminal_output=terminal,
        _synthetic_test=True,
    )

    assert result == {
        "attempt_id": attempt_id,
        "local_reconciliation_verified": True,
        "approval_consumption_preserved": True,
        "session_creation_outcome": "not_attempted",
        "executor_start_attempted": False,
        "workspace_removed": True,
        "f09_resources_absent": True,
        "lease_release_state": "resolved",
        "live_execution_authorized": False,
    }
    assert not workspace.exists()
    assert not (store.state_directory / harness_module.JOURNAL_DIRNAME / "active.lock").exists()
    assert journal_path.read_bytes() == old_journal
    assert audit_path.read_bytes() == old_audit
    assert {
        name: (store.root / name).read_bytes() for name in ("consumption.started", "consumed.json")
    } == markers
    assert store.inspect()["state"] == "consumed_or_uncertain"
    new_journal = next(
        path
        for path in (store.state_directory / harness_module.JOURNAL_DIRNAME).glob(
            "run-*/connectivity.jsonl"
        )
        if path != journal_path
    )
    report = harness_module.inspect_staging_journal(new_journal)
    assert report["integrity"] == "valid"
    assert report["durable_release_authorization"] is True
    assert report["cleanup_complete"] is False

    store.read_only = False
    with pytest.raises(ConnectivityError):
        cli._execute_approved(store)


@pytest.mark.parametrize("operation", ["session_create", "executor_start"])
def test_preflight_reconciliation_rejects_any_session_or_executor_start_intent(
    tmp_path, monkeypatch, operation
):
    cli = _solo_cli_module()
    store, attempt_id, _journal_path, _, workspace = _preflight_failure_state(
        tmp_path, extra_operations=(operation,)
    )
    _, inventory_calls = _install_reconciliation_fakes(monkeypatch, cli)
    terminal = _SoloTerminal()
    snapshot = _reconciliation_rejection_snapshot(store, workspace)

    with pytest.raises(ConnectivityError) as rejected:
        cli._reconcile_preflight_failure(
            store,
            attempt_id,
            terminal_input=terminal,
            terminal_output=terminal,
            _synthetic_test=True,
        )
    assert rejected.value.code == "reconcile_journal_not_preflight_only"
    assert str(rejected.value) == "Managed Agents connectivity check failed"
    assert inventory_calls == []
    _assert_reconciliation_rejection_unchanged(store, workspace, snapshot)


def test_preflight_reconciliation_rejects_docker_resources_and_keeps_lease(tmp_path, monkeypatch):
    cli = _solo_cli_module()
    store, attempt_id, _journal_path, _, workspace = _preflight_failure_state(tmp_path)
    _, inventory_calls = _install_reconciliation_fakes(
        monkeypatch,
        cli,
        inventory={"containers": ["rkmcp-probe-F09-0123456789abcdef"], "networks": []},
    )
    terminal = _SoloTerminal()
    snapshot = _reconciliation_rejection_snapshot(store, workspace)

    with pytest.raises(ConnectivityError) as rejected:
        cli._reconcile_preflight_failure(
            store,
            attempt_id,
            terminal_input=terminal,
            terminal_output=terminal,
            _synthetic_test=True,
        )
    assert rejected.value.code == "reconcile_f09_resources_present"
    assert str(rejected.value) == "Managed Agents connectivity check failed"
    assert inventory_calls == ["read"]
    _assert_reconciliation_rejection_unchanged(store, workspace, snapshot)


@pytest.mark.parametrize(
    ("audit_changes", "workspace_file", "acl", "expected_code"),
    [
        (
            {"session_creation_outcome": "unknown"},
            False,
            None,
            "reconcile_audit_not_preflight_only",
        ),
        ({}, True, None, "reconcile_workspace_not_empty_or_scoped"),
        (
            {},
            False,
            "user::rwx\nuser:65534:rwx\ngroup::---\nmask::rwx\nother::---\n",
            "reconcile_workspace_acl_not_private",
        ),
    ],
)
def test_preflight_reconciliation_rejects_uncertain_audit_or_workspace(
    tmp_path, monkeypatch, audit_changes, workspace_file, acl, expected_code
):
    cli = _solo_cli_module()
    store, attempt_id, _journal_path, _, workspace = _preflight_failure_state(
        tmp_path, audit_changes=audit_changes
    )
    _, inventory_calls = _install_reconciliation_fakes(monkeypatch, cli, acl=acl)
    if workspace_file:
        (workspace / "unexpected").write_text("synthetic", encoding="utf-8")
    terminal = _SoloTerminal()
    snapshot = _reconciliation_rejection_snapshot(store, workspace)

    with pytest.raises(ConnectivityError) as rejected:
        cli._reconcile_preflight_failure(
            store,
            attempt_id,
            terminal_input=terminal,
            terminal_output=terminal,
            _synthetic_test=True,
        )
    assert rejected.value.code == expected_code
    assert str(rejected.value) == "Managed Agents connectivity check failed"
    assert inventory_calls == []
    _assert_reconciliation_rejection_unchanged(store, workspace, snapshot)


def test_solo_operator_run_cli_synthetic_end_to_end_consumes_once_and_cleans(tmp_path, capsys):
    cli = _solo_cli_module()
    store, _ = _approve_cli_store(tmp_path)
    terminal = _SoloTerminal()
    captured = {}

    def components(**kwargs):
        client, calls = _http_client(
            store.state_directory,
            [_event("agent.session.environment.connected")],
            project_id="synthetic-staging-project-id",
            spend_approval=store.spend_approval(),
        )
        captured.update(kwargs)
        captured["calls"] = calls
        return client, FakeExecutor()

    result_code = cli.main(
        ["run", "--state-dir", str(store.state_directory)],
        _store_factory=lambda _path, **_kwargs: store,
        _test_components=components,
        _test_input=terminal,
        _test_output=terminal,
    )
    captured_output = capsys.readouterr()
    methods = [request.method for request in captured["calls"]]
    assert methods == ["POST", "GET", "DELETE"]
    body = json.loads(captured["calls"][0].content)
    assert body["spend_control"] == {"limit": 137}
    assert "input" not in body and set(body) == {"agent", "environment", "spend_control"}
    assert result_code == 0
    assert captured_output.out == ""
    assert APP_KEY not in captured_output.err and ENV_KEY not in captured_output.err
    result = json.loads(captured_output.err)
    assert result["cleanup_verified"] is True
    assert result["task_submission_count"] == result["responses_calls"] == 0
    assert result["approval_consumption_durable"] is True
    assert (store.root / "consumption.started").exists()
    assert (store.root / "consumed.json").exists()
    assert _saved_audit(captured["lease"])["cleanup_verified"] is True
    assert not captured["lease"].lock_path.exists()
    assert terminal.confirmations == [
        f"RUN F09 {store.validate()['claims']['attempt_id']} 137 CENTS ONE SESSION ZERO TASKS",
        harness_module.SOLO_CONFIRMATION,
    ]


def test_solo_operator_unexpected_component_failure_is_classified_before_consumption(tmp_path):
    cli = _solo_cli_module()
    store, _ = _approve_cli_store(tmp_path)
    terminal = _SoloTerminal()
    synthetic_secret = "synthetic-secret-do-not-disclose"

    def fail_before_client_creation(**_kwargs):
        raise RuntimeError(f"transport setup detail {synthetic_secret}")

    with pytest.raises(ConnectivityError) as raised:
        cli._execute_approved(
            store,
            terminal_input=terminal,
            terminal_output=terminal,
            synthetic_components=fail_before_client_creation,
        )

    assert raised.value.code == "solo_synthetic_components_unavailable"
    assert synthetic_secret not in str(raised.value)
    assert store.inspect()["state"] == "pending_review"
    assert not (store.root / "consumption.started").exists()
    assert not (store.root / "consumed.json").exists()
    journals = list(
        (store.state_directory / harness_module.JOURNAL_DIRNAME).rglob("connectivity.jsonl")
    )
    assert len(journals) == 1 and journals[0].read_bytes() == b""


@pytest.mark.parametrize(
    ("state", "expected_code", "uncertain"),
    [
        ("pending_review", "solo_lifecycle_failed_before_consumption", False),
        ("consumed_or_uncertain", "solo_lifecycle_failed_uncertain", True),
        ("corrupt", "solo_lifecycle_failed_uncertain", True),
    ],
)
def test_solo_operator_unexpected_lifecycle_diagnostic_uses_read_only_state(
    state, expected_code, uncertain
):
    cli = _solo_cli_module()

    class SyntheticInspection:
        def inspect(self):
            return {"state": state}

    error = cli._unexpected_lifecycle_error(SyntheticInspection())
    assert error.code == expected_code
    assert error.uncertain is uncertain
    assert "exception" not in str(error).lower()


def test_solo_operator_phase_diagnostic_does_not_expose_unexpected_exception_text():
    cli = _solo_cli_module()
    secret_like = "Bearer synthetic-token https://example.invalid/?token=synthetic"

    def fail():
        raise RuntimeError(secret_like)

    with pytest.raises(ConnectivityError) as raised:
        cli._diagnostic_call("solo_live_components_unavailable", fail)

    assert raised.value.code == "solo_live_components_unavailable"
    assert secret_like not in str(raised.value)


def test_live_component_construction_and_live_harness_init_are_offline(monkeypatch):
    cli = _solo_cli_module()
    request = _solo_request()
    state_directory = Path("synthetic-f09-state").resolve()
    record = {
        "request": request,
        "claims": {
            "attempt_id": "F09-synthetic-attempt",
            "billing_owner_approval_reference": "manual:synthetic-approval",
        },
    }
    # This in-memory store exercises the live binding contract without reading or
    # creating an approval record, credential, container, network, or session.
    store = object.__new__(cli.harness.SoloOperatorApprovalStore)
    store.synthetic = False
    store.state_directory = state_directory
    store.validate = lambda: record
    authorization = cli.harness.SoloOperatorAuthorization(
        store,
        object.__new__(cli.harness.StagingLease),
    )
    lease = authorization.lease
    lease.root = state_directory / cli.harness.JOURNAL_DIRNAME
    lease.synthetic = False
    lease.lock_path = lease.root / "active.lock"
    lease.acquired = False
    lease._lease_id = None

    class NoNetworkHTTPClient:
        def __init__(self, **kwargs):
            assert kwargs["transport"] is None
            assert kwargs["verify"] is True
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        def close(self):
            pass

    monkeypatch.setattr(cli.harness.httpx, "Client", NoNetworkHTTPClient)
    docker_calls = []

    def no_docker_executable(command):
        assert command == "docker"
        return "synthetic-docker-not-executed"

    def forbid_subprocess(*_args, **_kwargs):
        docker_calls.append(True)
        raise AssertionError("Docker subprocess boundary must not be called")

    monkeypatch.setattr(shutil, "which", no_docker_executable)
    monkeypatch.setattr(subprocess, "run", forbid_subprocess)
    client, executor, environment_key = cli._build_live_components(
        store=store,
        request=request,
        authorization=authorization,
        lease=lease,
        journal=object(),
        api_key="synthetic-application-key",
        env_key="synthetic-environment-key",
    )
    assert type(client) is cli.harness.StagingAgentsClient
    assert client.synthetic is False
    assert client._live_capability is cli.harness._LIVE_CLIENT_CAPABILITY
    journal = SimpleNamespace(synthetic=False, root=lease.root / "run-synthetic")

    try:
        controller = cli.harness.ConnectivityHarness(
            client=client,
            executor=executor,
            journal=journal,
            lease=lease,
            agent_config=request["agent"],
            environment_key=environment_key,
            create_seconds=request["create_seconds"],
            connect_seconds=request["connect_seconds"],
            cleanup_seconds=request["cleanup_seconds"],
            operator_authorization=authorization,
        )

        assert controller.state == "preflight"
        assert client.synthetic is False
        assert client._live_harness is controller
        assert executor._live_harness is controller
        assert type(executor).__name__ == "F09DockerExecutorAdapter"
        assert type(executor.runtime).__name__ == "F09ConnectivityRuntime"
        assert executor.topology.resource_scope == "F09"
        assert executor.topology.started is False
        assert environment_key == "synthetic-environment-key"
        assert docker_calls == []
    finally:
        client.close()


@pytest.mark.parametrize("case", ["missing", "expired", "replayed", "source-mismatch"])
def test_solo_operator_run_cli_rejects_missing_expired_replayed_or_changed_approval(tmp_path, case):
    cli = _solo_cli_module()
    if case == "missing":
        store, _, _ = _solo_store(tmp_path)
    else:
        store, current = _approve_cli_store(tmp_path)
        if case == "expired":
            current["now"] += timedelta(seconds=121)
        elif case == "source-mismatch":
            current["source"] = "9" * 64
        elif case == "replayed":
            first_terminal = _SoloTerminal()

            def components(**_kwargs):
                client, _calls = _http_client(
                    store.state_directory,
                    [_event("agent.session.environment.connected")],
                    project_id="synthetic-staging-project-id",
                    spend_approval=store.spend_approval(),
                )
                return client, FakeExecutor()

            cli._execute_approved(
                store,
                terminal_input=first_terminal,
                terminal_output=first_terminal,
                synthetic_components=components,
            )
    terminal = _SoloTerminal()
    calls = []

    def unexpected_components(**_kwargs):
        calls.append("constructed")
        raise AssertionError("Rejected approval must stop before client construction")

    with pytest.raises(ConnectivityError):
        cli._execute_approved(
            store,
            terminal_input=terminal,
            terminal_output=terminal,
            synthetic_components=unexpected_components,
        )
    assert calls == []
    assert terminal.confirmations == []


@pytest.mark.parametrize("mismatch", ["project", "spend"])
def test_solo_operator_run_cli_rejects_mismatched_client_before_transport(tmp_path, mismatch):
    cli = _solo_cli_module()
    store, _ = _approve_cli_store(tmp_path)
    terminal = _SoloTerminal()
    calls = []

    def mismatched_components(**_kwargs):
        client, requests = _http_client(
            store.state_directory,
            [_event("agent.session.environment.connected")],
            project_id=(
                "wrong-synthetic-project"
                if mismatch == "project"
                else "synthetic-staging-project-id"
            ),
            spend_approval=SpendControlApproval(138, "manual:synthetic-mismatch", True)
            if mismatch == "spend"
            else store.spend_approval(),
        )
        calls.extend(requests)
        return client, FakeExecutor()

    with pytest.raises(ConnectivityError):
        cli._execute_approved(
            store,
            terminal_input=terminal,
            terminal_output=terminal,
            synthetic_components=mismatched_components,
        )
    assert calls == []
    assert (store.root / "consumption.started").exists() is False


def test_solo_operator_run_cli_ambiguous_create_is_never_retried(tmp_path):
    cli = _solo_cli_module()
    store, _ = _approve_cli_store(tmp_path)
    terminal = _SoloTerminal()
    captured = {}

    def ambiguous_components(**kwargs):
        client, calls = _http_client(
            store.state_directory,
            [],
            project_id="synthetic-staging-project-id",
            spend_approval=store.spend_approval(),
            create_status=500,
        )
        captured.update(kwargs)
        captured["calls"] = calls
        return client, FakeExecutor()

    with pytest.raises(ConnectivityError):
        cli._execute_approved(
            store,
            terminal_input=terminal,
            terminal_output=terminal,
            synthetic_components=ambiguous_components,
        )
    assert [request.method for request in captured["calls"]] == ["POST"]
    assert store.inspect()["state"] == "consumed_or_uncertain"
    assert captured["lease"].lock_path.exists()
    assert _saved_audit(captured["lease"])["cleanup_verified"] is False


def test_solo_operator_live_credentials_fail_closed_without_echoing_values():
    cli = _solo_cli_module()
    for environment in (
        {},
        {"OPENAI_API_KEY": "synthetic-secret-a"},
        {
            "OPENAI_API_KEY": "synthetic-secret-a",
            "OPENAI_EXECUTOR_API_KEY": "synthetic-secret-a",
        },
        {
            "OPENAI_API_KEY": "synthetic-secret-a\nforged-header",
            "OPENAI_EXECUTOR_API_KEY": "synthetic-secret-b",
        },
        {
            "OPENAI_API_KEY": "a" * 4097,
            "OPENAI_EXECUTOR_API_KEY": "synthetic-secret-b",
        },
    ):
        with pytest.raises(ConnectivityError) as raised:
            cli._live_credentials(environment)
        assert raised.value.code == "solo_credentials_unavailable"
        assert "synthetic-secret-a" not in str(raised.value)


def test_f09_docker_boundaries_force_local_socket_and_drop_context_overrides():
    path = ROOT / "benchmarks/codex_r/exploratory/docker_runtime.py"
    spec = importlib.util.spec_from_file_location("codex_f09_docker_runtime", path)
    assert spec is not None and spec.loader is not None
    runtime_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime_module)

    topology = object.__new__(runtime_module.RestrictedEgressNetwork)
    topology.docker = "/usr/bin/docker"
    topology.resource_scope = "F09"
    assert topology._docker_command("network", "create") == [
        "/usr/bin/docker",
        "--host",
        "unix:///var/run/docker.sock",
        "network",
        "create",
    ]
    safe = runtime_module._operator_environment(
        {
            "PATH": "/usr/bin",
            "DOCKER_HOST": "tcp://synthetic-remote:2375",
            "DOCKER_CONTEXT": "synthetic-remote",
            "DOCKER_CONFIG": "/synthetic/config",
            "OPENAI_API_KEY": "synthetic-app-secret",
            "OPENAI_EXECUTOR_API_KEY": "synthetic-executor-secret",
            "HTTP_PROXY": "http://synthetic-proxy.invalid",
        }
    )
    assert safe == {"PATH": "/usr/bin"}


@pytest.mark.parametrize("failure", ["connection", "executor-start", "cleanup", "audit"])
def test_solo_operator_run_cli_failure_paths_never_report_success(tmp_path, monkeypatch, failure):
    cli = _solo_cli_module()
    store, _ = _approve_cli_store(tmp_path)
    terminal = _SoloTerminal()
    captured = {}
    events = (
        [_event("agent.session.environment.failed")]
        if failure == "connection"
        else [_event("agent.session.environment.connected")]
    )

    def components(**kwargs):
        client, calls = _http_client(
            store.state_directory,
            events,
            project_id="synthetic-staging-project-id",
            spend_approval=store.spend_approval(),
        )
        captured.update(kwargs)
        captured["calls"] = calls
        executor = FakeExecutor(
            start_exception=(
                ConnectivityError("synthetic_executor_start_failure")
                if failure == "executor-start"
                else None
            ),
            stop=failure != "cleanup",
        )
        captured["executor"] = executor
        return client, executor

    if failure == "audit":
        monkeypatch.setattr(
            harness_module.ConnectivityHarness,
            "_persist_audit",
            lambda _controller: (_ for _ in ()).throw(OSError("synthetic audit write failure")),
        )

    with pytest.raises(ConnectivityError):
        cli._execute_approved(
            store,
            terminal_input=terminal,
            terminal_output=terminal,
            synthetic_components=components,
        )
    assert [request.method for request in captured["calls"]].count("POST") == 1
    assert captured["lease"].acquired is (failure != "connection")
    assert (store.root / "consumed.json").exists()
    if failure == "audit":
        assert not list(captured["lease"].root.glob("run-*/connectivity-audit.json"))
    else:
        audit = _saved_audit(captured["lease"])
        assert audit["cleanup_verified"] is (failure == "connection")


@pytest.mark.parametrize("failure", ["wrong-commit", "modified-source"])
def test_solo_operator_source_identification_rejects_wrong_commit_or_modified_file(
    monkeypatch, failure
):
    calls = []

    def fake_git(argv, **_kwargs):
        operation = argv[-2]
        calls.append(operation)
        if operation == "rev-parse":
            value = ("b" if failure == "wrong-commit" else "a") * 40
            return subprocess.CompletedProcess(argv, 0, stdout=value.encode())
        return subprocess.CompletedProcess(argv, 0, stdout=b"synthetically different source")

    monkeypatch.setattr(harness_module.subprocess, "run", fake_git)
    expected = "a" * 40
    with pytest.raises(ConnectivityError) as rejected:
        harness_module._solo_source_identification(expected)
    assert rejected.value.code == "solo_source_mismatch"
    if failure == "wrong-commit":
        assert calls == ["rev-parse"]
    else:
        assert calls == ["rev-parse", "show"]


def test_solo_operator_never_promotes_legacy_or_synthetic_records(tmp_path):
    store, _, _ = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    path = store.root / "approval.json"
    record = store._read("approval.json")
    record["synthetic"] = False  # Deliberately forged fixture; never a real approval.
    path.write_bytes(store._bytes(record))
    with pytest.raises(ConnectivityError) as mismatch:
        store.validate()
    assert mismatch.value.code == "solo_record_invalid"
    record["synthetic"] = True
    record["record_type"] = harness_module.STAGING_AUTHORIZATION_RECORD_TYPE
    path.write_bytes(store._bytes(record))
    with pytest.raises(ConnectivityError):
        store.validate()


def test_solo_operator_expiry_during_confirmation_or_after_consumption_blocks_post(tmp_path):
    store, terminal, current = _solo_store(tmp_path)
    readline = terminal.readline

    def delayed_reply():
        current["now"] += timedelta(seconds=121)
        return readline()

    terminal.readline = delayed_reply
    with pytest.raises(ConnectivityError):
        store.approve(_solo_request(), expires_in_seconds=120)
    assert not (store.root / "approval.json").exists()
    terminal.readline = readline
    store.approve(_solo_request(), expires_in_seconds=120)
    controller, lease, journal, calls = _solo_lifecycle(store)
    append = journal.append

    def expire_after_consumption(operation, event, **kwargs):
        sequence = append(operation, event, **kwargs)
        if operation == "authorization_consume" and event == "outcome":
            current["now"] += timedelta(seconds=121)
        return sequence

    journal.append = expire_after_consumption
    with pytest.raises(ConnectivityError):
        controller.run()
    assert calls == []
    assert (store.root / "consumed.json").exists()
    assert lease.lock_path.exists()


def test_solo_operator_concurrent_lifecycles_can_create_only_one_session(tmp_path):
    store, _, _ = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    first = _solo_lifecycle(store)
    second = _solo_lifecycle(store)
    barrier = threading.Barrier(2)

    def attempt(controller):
        barrier.wait(timeout=2)
        try:
            return controller.run()["cleanup_verified"]
        except (ConnectivityError, harness_module.DurabilityError):
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt, item[0]) for item in (first, second)]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(results) == [False, True]
    assert sum(call.method == "POST" for item in (first, second) for call in item[3]) == 1


def test_solo_operator_private_record_and_symlink_checks_are_fail_closed(tmp_path):
    store, _, _ = _solo_store(tmp_path)
    store.approve(_solo_request(), expires_in_seconds=120)
    path = store.root / "approval.json"
    path.chmod(0o644)
    with pytest.raises(ConnectivityError):
        store.validate()
    path.chmod(0o600)  # Restore only this newly generated synthetic fixture.
    target = path.with_suffix(".original")
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ConnectivityError):
        store.validate()
    assert store.inspect()["state"] == "corrupt"


def test_solo_operator_cli_inspection_does_not_create_missing_state(tmp_path):
    state = tmp_path / "missing-store"
    state.mkdir(mode=0o700)
    path = ROOT / "benchmarks/codex_r/exploratory/f09_solo_operator.py"
    result = subprocess.run(
        [sys.executable, "-B", str(path), "inspect", "--state-dir", str(state)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert not list(state.iterdir())


def test_solo_operator_rejects_secret_shaped_model_before_confirmation_or_storage(tmp_path):
    store, terminal, _ = _solo_store(tmp_path)
    request = _solo_request()
    request["agent"] = {"model": "sk-synthetic-model-input-must-not-be-stored", "tools": []}
    with pytest.raises(ConnectivityError) as raised:
        store.approve(request, expires_in_seconds=120)
    assert raised.value.code == "solo_request_invalid"
    assert terminal.getvalue() == ""
    assert not list(store.root.iterdir())
