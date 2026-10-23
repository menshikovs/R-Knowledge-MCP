"""Synthetic-only regressions for the zero-task connectivity harness."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

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
    delete_status=200,
    spend_approval=SYNTHETIC_SPEND_APPROVAL,
):
    calls = calls if calls is not None else []
    event_bytes = _sse(events)

    def handler(request):
        calls.append(request)
        if timeline is not None:
            timeline.append(f"http:{request.method}")
        if request.method == "POST" and request.url.path == "/v1/agents/sessions":
            body = json.loads(request.content)
            assert set(body) == {"agent", "environment", "spend_control"}
            assert "input" not in body and "events" not in body
            assert body["environment"]["type"] == "self_hosted"
            assert body["spend_control"] == {"limit": 1250}
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
        project_id="synthetic-staging-project",
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

    assert task_route.value.code == responses_route.value.code == "route_rejected"
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


def test_live_harness_rejects_unreviewed_executor():
    from types import SimpleNamespace

    root = Path("synthetic-scope")
    concrete_client = object.__new__(StagingAgentsClient)
    concrete_client.synthetic = False
    concrete_client._live_capability = harness_module._LIVE_CLIENT_CAPABILITY
    with pytest.raises(ValueError, match="reviewed Docker adapter"):
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
