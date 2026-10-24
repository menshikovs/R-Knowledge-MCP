"""Explicitly offline P0-B tests; real subprocesses are ONLY synthetic crash children."""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p0b_p0a_fixtures", ROOT / "tests/test_codex_executor_contract_integration.py"
)
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)
lifecycle = fixtures.lifecycle
safety_lib = lifecycle.safety_lib
SECRET = fixtures.SECRET_TEXT


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("Network access is prohibited in P0-B tests")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    original = subprocess.run

    def child_only(argv, *args, **kwargs):
        allowed = {CRASH_SCRIPT, MARKER_CRASH_SCRIPT, CONTROLLER_CRASH_SCRIPT}
        if len(argv) < 3 or argv[:2] != [sys.executable, "-c"] or argv[2] not in allowed:
            pytest.fail("Only the fixed synthetic crash child may run a real subprocess")
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", child_only)


class Clock:
    def __init__(self):
        self.value = 0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.value

    def advance(self, seconds):
        with self.lock:
            self.value += seconds


class SSE(httpx.SyncByteStream):
    def __init__(self, scenario, clock, entered, release):
        self.scenario, self.clock = scenario, clock
        self.entered, self.release = entered, release

    def __iter__(self):
        if self.scenario == "separate_task_budget":
            self.clock.advance(59)
            yield b'data: {"type":"agent.session.environment.connected"}\n\n'
            self.clock.advance(850)
            yield b'data: {"type":"agent.session.turn.failed"}\n\n'
            return
        if self.scenario == "delayed_connection":
            self.clock.advance(61)
        if self.scenario in {"task_post", "no_terminal", "task_deadline", "expired_intent"}:
            yield b'data: {"type":"agent.session.environment.connected"}\n\n'
        if self.scenario in {"silent", "task_deadline"}:
            self.entered.set()
            self.release.wait()
            return
        if self.scenario == "no_terminal":
            return
        yield b'data: {"type":"agent.session.environment.failed"}\n\n'


def execute(
    tmp_path,
    scenario="ordinary",
    *,
    audit_writer=None,
    journal_write=None,
    real_lease=False,
    transition_hook=None,
    consume_real_markers=False,
):
    workspace = tmp_path / "public"
    (workspace / "data").mkdir(parents=True)
    (workspace / "TASK.md").write_text("Synthetic input, never a live experiment.\n")
    (workspace / "renv.lock").write_text("{}\n")
    (workspace / "data/records.csv").write_text("x\n1\n")
    clock, entered, release = Clock(), threading.Event(), threading.Event()
    requests, timing = [], []
    triggered = threading.Event()

    def journal_hook(where, item):
        if transition_hook:
            transition_hook(where, item)
        if (
            scenario == "expired_intent"
            and where == "after"
            and item["operation"] == "task_submit"
            and item["event"] == "intent"
        ):
            clock.advance(901)

    journal = safety_lib.Journal(
        tmp_path / "state",
        "R01-A/attempt-1",
        synthetic=True,
        transition_hook=journal_hook,
        **({"write": journal_write} if journal_write else {}),
    )
    control = None

    def wait(done, seconds):
        if entered.is_set() and not release.is_set() and not triggered.is_set():
            triggered.set()
            phase = timing[0].primary.phase
            clock.advance(timing[0].budgets[phase] + 1)
        else:
            done.wait(min(seconds, 0.01))

    def factory(*_args):
        instance = safety_lib.LifecycleSafety(journal, clock=clock, wait=wait)
        timing.append(instance)
        return instance

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/sessions"):
            assert (
                "session_create" in safety_lib.inspect_journal(journal.path)["pending_operations"]
            )
            if scenario == "slow_session":
                clock.advance(31)
            return httpx.Response(201, json=fixtures.session_record(fixtures.ACCEPTED[2]))
        if request.method == "GET":
            if scenario == "late_headers":
                clock.advance(46)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=SSE(scenario, clock, entered, release),
            )
        if request.method == "DELETE":
            if not journal.failed:
                assert (
                    "session_delete"
                    in safety_lib.inspect_journal(journal.path)["pending_operations"]
                )
            if scenario == "delete_failure":
                return httpx.Response(500, json={"secret": SECRET})
            return httpx.Response(200, json={"id": "synthetic_session", "deleted": True})
        event_type = json.loads(request.content)["events"][0]["type"]
        if event_type == "agent.session.input.message":
            assert "task_submit" in safety_lib.inspect_journal(journal.path)["pending_operations"]
            if scenario == "task_post":
                clock.advance(16)
            return httpx.Response(200, json={})
        assert event_type == "agent.session.input.cancel"
        if scenario == "cancel_timeout":
            clock.advance(11)
        return httpx.Response(200, json={})

    client = fixtures.managed.ManagedAgentsClient(
        fixtures.APP_KEY, transport=httpx.MockTransport(handler)
    )
    client.synthetic = True
    docker = fixtures.FakeDocker(workspace)

    def runner(argv, *, timeout=20, env=None):
        effects = {
            "create": "executor_create",
            "start": "executor_start",
            "run": "image_version_probe",
            "rm": "executor_terminate",
        }
        if argv[1] in effects:
            if journal.failed:
                assert argv[1] == "rm"  # Destructive cleanup only, never launch or POST.
            else:
                assert (
                    effects[argv[1]]
                    in safety_lib.inspect_journal(journal.path)["pending_operations"]
                )
        if scenario == "startup_timeout" and argv[1] == "start":
            clock.advance(46)
        if scenario == "separate_task_budget" and argv[1] == "start":
            clock.advance(18)
        if scenario == "termination_timeout" and argv[1] == "rm":
            clock.advance(21)
        return docker(argv, timeout=timeout, env=env)

    runtime = fixtures.runtime_module.CodexCandidateRuntime(
        fixtures.IMAGE, docker="synthetic-docker", command_runner=runner
    )

    class Topology:
        started = False
        internal_network = fixtures.NETWORK

        def start(self):
            self.started = True
            return {"proxy_internal_ip": "172.20.0.2"}

        def cleanup(self):
            return scenario != "topology_failure"

    def gates():
        if scenario == "preparation_timeout":
            clock.advance(61)
        return {}

    lease = (
        fixtures.adapter.SingleTrialLease(tmp_path / "state", "R01-A")
        if real_lease
        else fixtures.Lease()
    )
    if scenario == "lease_release_failure":

        class FailingLease(fixtures.Lease):
            def __exit__(self, *_args):
                raise OSError(SECRET)

        lease = FailingLease()
    lease.clean = False
    ledger = fixtures.runtime_module.pilot.BalanceAwareLedger(
        1004,
        checked_at=datetime.now(UTC).isoformat(),
        balance_source="synthetic fixture",
        reserve_cents=200,
    )

    def review(_record):
        if scenario == "review_timeout":
            clock.advance(301)
        return None

    control = lifecycle.R01ALifecycleController(
        client=client,
        runtime=runtime,
        topology=Topology(),
        ledger=ledger,
        authorize=lambda *_: None,
        consume_authorization=fixtures.adapter.consume_authorization
        if consume_real_markers
        else lambda *_args, **_kwargs: None,
        lease_factory=lambda *_: lease,
        score=lambda *_: pytest.fail("No pre-task scoring"),
        frozen_r_image_id=fixtures.runtime_module.FROZEN_R_IMAGE_ID,
        environment_key=fixtures.ENV_KEY,
        estimated_spend_cents=100,
        checkpoint_review=review,
        current_live_gates=gates,
        synthetic_mode=True,
        safety_factory=factory,
        audit_writer=audit_writer,
    )
    context = {
        "trial_id": "R01-A",
        "expected_tools": [],
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "condition": "A",
        "workspace": str(workspace),
    }
    try:
        record = control.run_one(
            context=context,
            authorization={"synthetic": True, "authorization_id": "a" * 32},
            state_directory=tmp_path / "state",
        )
    except lifecycle.LifecycleError as exc:
        record = exc.audit_record
    finally:
        release.set()
    return record, journal, docker, requests, lease


@pytest.mark.parametrize(
    ("scenario", "phase"),
    [
        ("preparation_timeout", "preparation"),
        ("slow_session", "session_creation"),
        ("startup_timeout", "startup"),
        ("late_headers", "startup"),
        ("silent", "connection"),
        ("delayed_connection", "connection"),
        ("task_post", "task_submission"),
        ("task_deadline", "task"),
    ],
)
def test_remaining_budget_deadlines_and_no_retry(tmp_path, monkeypatch, scenario, phase):
    def no_process(*_args, **_kwargs):
        pytest.fail("Real subprocess access is prohibited in deadline tests")

    monkeypatch.setattr(subprocess, "run", no_process)
    record, journal, docker, requests, lease = execute(tmp_path, scenario)
    assert phase in record["expired_phases"]
    assert record["synthetic"] and record["automatic_next_trial_authorized"] is False
    assert requests.count(("POST", "/v1/agents/sessions")) <= 1
    if scenario not in {"task_post", "task_deadline"}:
        assert record.get("task_submissions_attempted_count", 0) == 0
    if scenario in {"preparation_timeout", "slow_session", "late_headers"}:
        assert not any(call[1] == "create" for call in docker.calls)
    if scenario == "task_post":
        assert record["task_submission_uncertain"]
        assert record["task_submissions_attempted_count"] == 1
        assert not record["inference_submitted"]
    if scenario == "task_deadline":
        assert record["deadline_expired"] and record["container_termination_verified"]
    if record.get("unfinished_operations_uncertain"):
        assert not lease.clean and not record["cleanup_verified"]
    assert safety_lib.inspect_journal(journal.path)["replay_permitted"] is False


@pytest.mark.parametrize(
    "scenario",
    ["no_terminal", "cancel_timeout", "termination_timeout", "delete_failure", "topology_failure"],
)
def test_cleanup_errors_and_unknown_spending_never_erase_primary(tmp_path, scenario):
    record, journal, _, _, lease = execute(tmp_path, scenario)
    assert record["failure"] and record["primary_failure_classification"]
    assert record["scoring"] is None
    checkpoint = record["checkpoint"]
    assert checkpoint["reported_spend_cents"] is None and checkpoint["usage"] is None
    assert not checkpoint["reconciled"] and not checkpoint["automatic_next_trial_authorized"]
    if scenario in {"termination_timeout", "delete_failure", "topology_failure"}:
        assert not record["cleanup_verified"] and not lease.clean
    inspection = safety_lib.inspect_journal(journal.path)
    assert inspection["remote_session_state"] == "unknown"
    assert not inspection["cleanup_proven_by_inspection"]


def test_disk_failure_preserves_primary_and_retains_lease(tmp_path, capsys):
    def failed_writer(*_args, **_kwargs):
        raise OSError(SECRET)

    record, journal, _, _, lease = execute(tmp_path, "delete_failure", audit_writer=failed_writer)
    assert record["failure"] and record["primary_failure_classification"]
    assert record["evidence_failure"] == "final_audit_not_durable" and not lease.clean
    assert not journal.path.with_suffix(".audit.json").exists()
    inspection = safety_lib.inspect_journal(journal.path)
    assert not inspection["final_audit_outcome_recorded"]
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err + journal.path.read_text()


@pytest.mark.parametrize("short", [True, False])
def test_failed_intent_fsync_or_short_write_prevents_side_effect(tmp_path, short):
    calls = []

    def write(fd, raw):
        if short:
            os.write(fd, raw[: len(raw) // 2])
            return len(raw) // 2
        raise OSError(SECRET)

    journal = safety_lib.Journal(tmp_path, "R01-A/attempt-1", synthetic=True, write=write)
    safety = safety_lib.LifecycleSafety(journal)
    with pytest.raises(safety_lib.EvidenceError):
        safety.effect("session_create", lambda: calls.append("forbidden"))
    assert calls == [] and safety.evidence_failed
    journal.close()
    inspection = safety_lib.inspect_journal(journal.path)
    assert inspection["remote_session_state"] == "unknown" and not inspection["replay_permitted"]
    if short:
        assert inspection["incomplete_tail"]


def test_journal_schema_confidentiality_and_owner_permissions(tmp_path, capsys):
    journal = safety_lib.Journal(tmp_path, "R01-A/attempt-1", synthetic=True)
    for operation in sorted(safety_lib.OPERATIONS):
        seq = journal.append(operation, "intent")
        journal.append(operation, "outcome", intent_seq=seq, code=SECRET, cleanup_code=SECRET)
    for kwargs in (
        {"operation": SECRET, "event": "intent"},
        {"operation": "session_create", "event": SECRET},
        {"operation": "session_create", "event": "outcome", "intent_seq": SECRET},
    ):
        with pytest.raises(safety_lib.EvidenceError):
            journal.append(**kwargs)
    journal.close()
    assert SECRET not in journal.path.read_text() + capsys.readouterr().out
    inspection = safety_lib.inspect_journal(journal.path)
    assert not inspection["invalid_record"] and inspection["synthetic"] is True
    if os.name != "nt":
        assert journal.path.stat().st_mode & 0o777 == 0o600
        assert journal.path.parent.stat().st_mode & 0o777 == 0o700
    else:
        assert journal.directory_sync is False


CRASH_SCRIPT = r"""
import importlib.util, os, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("crash_safety",sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
operation, event, boundary = sys.argv[3:]
def hook(where, value):
    if value["operation"] == operation and value["event"] == event and where == boundary:
        os._exit(77)
journal=module.Journal(Path(sys.argv[2]),"R01-A/attempt-1",synthetic=True,transition_hook=hook)
seq=journal.append(operation,"intent")
(Path(sys.argv[2])/"synthetic-side-effect").write_text("synthetic")
journal.append(operation,"outcome",intent_seq=seq)
os._exit(78)
"""


@pytest.mark.parametrize("operation", sorted(safety_lib.OPERATIONS))
@pytest.mark.parametrize(
    ("event", "boundary"),
    [("intent", "before"), ("intent", "after"), ("outcome", "before"), ("outcome", "after")],
)
def test_process_crash_at_every_critical_transition_is_read_only_recoverable(
    tmp_path, operation, event, boundary
):
    # This is the only real subprocess launched here: a fixed local Python
    # child writing synthetic fixtures. It has no network or Docker code.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            CRASH_SCRIPT,
            str(ROOT / "benchmarks/codex_r/exploratory/lifecycle_safety.py"),
            str(tmp_path),
            operation,
            event,
            boundary,
        ],
        timeout=10,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 77
    path = tmp_path / "lifecycle-journals/R01-A-attempt-1.jsonl"
    before = path.read_bytes()
    inspection = safety_lib.inspect_journal(path)
    assert before == path.read_bytes()  # Inspection is strictly read-only.
    assert not inspection["replay_permitted"] and not inspection["automatic_recovery_permitted"]
    assert inspection["remote_session_state"] == "unknown"
    if (event, boundary) in {("intent", "after"), ("outcome", "before")}:
        assert operation in inspection["pending_operations"]
    assert not inspection["cleanup_proven_by_inspection"]
    with pytest.raises(FileExistsError):
        safety_lib.Journal(tmp_path, "R01-A/attempt-1", synthetic=True)


CONTROLLER_CRASH_SCRIPT = r"""
import importlib.util, os, socket, subprocess, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("crash_production_controller",sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
def deny(*args, **kwargs):
    raise AssertionError("Real Docker and network access are forbidden")
socket.socket.connect=deny; socket.create_connection=deny
subprocess.run=deny; subprocess.Popen=deny
# Only the temporary synthetic marker fixture skips authorization validation.
# Production consumption, lease handling, controller, client and runtime remain intact.
module.fixtures.adapter.validate_authorization=lambda *args,**kwargs: None
operation,event,boundary=sys.argv[3:]
def hook(where,item):
    if (item["operation"],item["event"],where)==(operation,event,boundary):
        os._exit(77)
module.execute(Path(sys.argv[2]),"no_terminal",transition_hook=hook,
    consume_real_markers=True,real_lease=True)
os._exit(78)
"""


@pytest.mark.parametrize("operation", sorted(safety_lib.OPERATIONS))
@pytest.mark.parametrize(
    ("event", "boundary"),
    [("intent", "before"), ("intent", "after"), ("outcome", "before"), ("outcome", "after")],
)
def test_production_controller_process_crash_preserves_uncertainty(
    tmp_path, operation, event, boundary
):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            CONTROLLER_CRASH_SCRIPT,
            str(Path(__file__).resolve()),
            str(tmp_path),
            operation,
            event,
            boundary,
        ],
        timeout=15,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 77, result.stderr.decode("utf-8", "replace")
    state = tmp_path / "state"
    journal = state / "lifecycle-journals/R01-A-attempt-1.jsonl"
    snapshot = journal.read_bytes()
    inspection = safety_lib.inspect_journal(journal)
    assert not inspection["automatic_recovery_permitted"]
    assert not inspection["replay_permitted"]
    assert inspection["remote_session_state"] == "unknown"
    released = operation == "lease_release" and event == "outcome"
    assert state.joinpath("active-trial.lock").is_file() is not released
    assert journal.read_bytes() == snapshot
    if (event, boundary) in {("intent", "after"), ("outcome", "before")}:
        assert operation in inspection["pending_operations"]
    if operation == "audit_persist":
        assert state.joinpath("consumed-trials/R01-A.json").is_file()
        assert inspection["final_audit_outcome_recorded"] is (
            event == "outcome" and boundary == "after"
        )


def test_truncated_or_mutated_journal_does_not_become_cleanup_success(tmp_path):
    journal = safety_lib.Journal(tmp_path, "R01-A/attempt-1", synthetic=True)
    journal.append("session_create", "intent")
    journal.close()
    with journal.path.open("ab") as output:
        output.write(b'{"schema_version":')
    before = journal.path.read_bytes()
    inspection = safety_lib.inspect_journal(journal.path)
    assert inspection["incomplete_tail"] and inspection["pending_operations"] == ["session_create"]
    assert journal.path.read_bytes() == before


def test_termination_race_serializes_and_verifies_removal_once(tmp_path):
    runtime, docker = fixtures.runtime(tmp_path)
    journal = safety_lib.Journal(tmp_path, "R01-A/attempt-1", synthetic=True)
    runtime.safety = safety_lib.LifecycleSafety(journal)
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                runtime.safety.cleanup(
                    "executor_terminate",
                    lambda: runtime.stop_managed_executor(fixtures.CID),
                    cap=20,
                )
            )
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    journal.close()
    assert results == [True, True]
    assert sum(call[1] == "rm" for call in docker.calls) == 1


MARKER_CRASH_SCRIPT = r"""
import importlib.util, os, sys
from pathlib import Path
from types import SimpleNamespace
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
safety=load("marker_safety",sys.argv[1]); adapter=load("marker_adapter",sys.argv[2])
root=Path(sys.argv[3])
def hook(where, record):
    if (where=="after" and record["operation"]=="trial_marker_create"
        and record["event"]=="outcome"):
        os._exit(77)
journal=safety.Journal(root,"R01-A/attempt-1",synthetic=True,transition_hook=hook)
control=safety.LifecycleSafety(journal)
adapter.validate_authorization=lambda *_args,**_kwargs: None
adapter.consume_authorization({"authorization_id":"a"*32},
    {"trial_id":"R01-A","attempt_id":"R01-A/attempt-1"}, root,
    lease=SimpleNamespace(safety=control))
os._exit(78)
"""


def test_interruption_between_consumed_markers_never_allows_replay(tmp_path, monkeypatch):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            MARKER_CRASH_SCRIPT,
            str(ROOT / "benchmarks/codex_r/exploratory/lifecycle_safety.py"),
            str(ROOT / "benchmarks/codex_r/exploratory/adapter.py"),
            str(tmp_path),
        ],
        timeout=10,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 77
    first = tmp_path / "consumed-trials/R01-A.json"
    second = tmp_path / ("consumed-authorizations/" + "a" * 32 + ".json")
    assert first.is_file() and not second.exists()
    snapshot = first.read_bytes()
    monkeypatch.setattr(fixtures.adapter, "validate_authorization", lambda *_args, **_kwargs: None)
    with pytest.raises(fixtures.adapter.AdapterError, match="consumed"):
        fixtures.adapter.consume_authorization(
            {"authorization_id": "a" * 32},
            {"trial_id": "R01-A", "attempt_id": "R01-A/attempt-1"},
            tmp_path,
        )
    assert first.read_bytes() == snapshot and not second.exists()
    report = safety_lib.inspect_journal(tmp_path / "lifecycle-journals/R01-A-attempt-1.jsonl")
    assert report["replay_permitted"] is False


def test_fsync_failure_does_not_authorize_a_side_effect(tmp_path):
    def failed_sync(_fd):
        raise OSError(SECRET)

    journal = safety_lib.Journal(tmp_path, "R01-A/attempt-1", synthetic=True, fsync=failed_sync)
    safety = safety_lib.LifecycleSafety(journal)
    actions = []
    with pytest.raises(safety_lib.EvidenceError):
        safety.effect("task_submit", lambda: actions.append("forbidden"))
    journal.close()
    assert actions == []
    assert not safety_lib.inspect_journal(journal.path)["replay_permitted"]


def test_evidence_failure_still_attempts_cleanup_without_certifying_it(tmp_path):
    def failed_write(*_args):
        raise OSError(SECRET)

    record, journal, docker, requests, lease = execute(tmp_path, journal_write=failed_write)
    assert record["primary_failure_classification"] == "EvidenceError"
    assert not record["cleanup_verified"] and not lease.clean
    assert requests == [] and docker.calls == []
    assert record["evidence_failure"] == "final_audit_not_durable"
    assert SECRET not in journal.path.read_text()


def test_disk_full_after_start_prevents_post_but_still_removes_candidate(tmp_path):
    def failed_task_intent(fd, raw):
        item = json.loads(raw)
        if item["operation"] == "task_submit" and item["event"] == "intent":
            raise OSError(SECRET)
        return os.write(fd, raw)

    record, journal, docker, requests, lease = execute(
        tmp_path, "no_terminal", journal_write=failed_task_intent
    )
    assert docker.removed and record["container_termination_verified"]
    assert record["primary_failure_classification"] == "EvidenceError"
    assert not record["cleanup_verified"] and not lease.clean
    assert requests.count(("POST", "/v1/agents/sessions/synthetic_session/events")) == 1
    assert SECRET not in journal.path.read_text()


def test_deadline_spent_in_durable_intent_cannot_send_a_task(tmp_path):
    record, _, _, requests, _ = execute(tmp_path, "expired_intent")
    assert "task" in record["expired_phases"]
    assert not record["inference_submitted"]
    assert requests.count(("POST", "/v1/agents/sessions/synthetic_session/events")) == 1


def test_operator_review_has_its_own_budget_and_unknown_spend(tmp_path):
    record, _, _, _, _ = execute(tmp_path, "review_timeout")
    assert "review" in record["expired_phases"]
    assert record["deadline_expired"] is False
    assert record["checkpoint"]["reported_spend_cents"] is None
    assert not record["automatic_next_trial_authorized"]


def test_task_budget_is_independent_of_startup_and_connection(tmp_path, monkeypatch):
    # A controller deadline must supersede the client's former stream-wide clock.
    # The task runs 850 seconds after 77 seconds of startup/connection.
    clock = Clock()
    monkeypatch.setitem(execute.__globals__, "Clock", lambda: clock)
    monkeypatch.setattr(fixtures.managed, "time", SimpleNamespace(monotonic=clock))
    record, _, _, _, _ = execute(tmp_path, "separate_task_budget")
    assert clock() == 927
    assert record["inference_submitted"]
    assert record["expired_phases"] == []
    assert not record["deadline_expired"]
    assert record["events"][-1]["type"] == "agent.session.turn.failed"


def test_negative_cleanup_result_has_an_unverified_journal_outcome(tmp_path):
    record, journal, _, _, _ = execute(tmp_path, "topology_failure")
    outcomes = [json.loads(line) for line in journal.path.read_text().splitlines()]
    cleanup = [
        item
        for item in outcomes
        if item["operation"] == "topology_cleanup" and item["event"] == "outcome"
    ]
    assert cleanup[-1]["code"] == "cleanup_unverified"
    assert cleanup[-1]["cleanup_code"] == "cleanup_unverified"
    assert not record["cleanup_verified"]


def test_lease_release_failure_retains_primary_in_committed_evidence(tmp_path):
    record, journal, _, _, _ = execute(tmp_path, "lease_release_failure")
    assert record["failure"] and record["primary_failure_classification"]
    assert not record["cleanup_verified"]
    assert "lease_release_unverified" in record["cleanup_failures"]
    inspection = safety_lib.inspect_journal(journal.path)
    assert inspection["final_audit_outcome_recorded"]
    assert not inspection["lease_release_outcome_recorded"]
    persisted = json.loads(journal.path.with_suffix(".audit.json").read_text())
    assert persisted["failure"] == record["failure"]
    assert SECRET not in journal.path.read_text() + json.dumps(persisted) + json.dumps(record)


def test_final_evidence_deadline_cannot_release_lease(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setitem(execute.__globals__, "Clock", lambda: clock)

    def slow_writer(path, value):
        safety_lib.private_write(path, value)
        clock.advance(61)

    record, journal, _, _, lease = execute(tmp_path, audit_writer=slow_writer)
    assert record["failure"] and not record["cleanup_verified"] and not lease.clean
    assert record["evidence_failure"] == "final_audit_not_durable"
    assert "postprocess" in record["expired_phases"]
    assert not safety_lib.inspect_journal(journal.path)["lease_release_outcome_recorded"]


def test_partial_final_audit_is_preserved_and_never_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-final.audit.json"

    def partial(_value, output, **_kwargs):
        output.write('{"synthetic":true')
        raise OSError(SECRET)

    monkeypatch.setattr(safety_lib.json, "dump", partial)
    with pytest.raises(OSError):
        safety_lib.private_write(path, {"synthetic": True})
    snapshot = path.read_bytes()
    with pytest.raises(FileExistsError):
        safety_lib.private_write(path, {"synthetic": True})
    assert path.read_bytes() == snapshot
    with pytest.raises(json.JSONDecodeError):
        json.loads(snapshot)


def test_stale_foreign_lease_is_retained_byte_for_byte(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    lock = state / "active-trial.lock"
    snapshot = b'{"trial_id":"R01-A","pid":123,"lease_id":"foreign"}\n'
    lock.write_bytes(snapshot)
    record, _, docker, requests, lease = execute(tmp_path, real_lease=True)
    assert not lease.acquired and not record["cleanup_verified"]
    assert lock.read_bytes() == snapshot and requests == [] and docker.calls == []


def test_read_only_recovery_and_synthetic_audit_cannot_import_as_real(tmp_path, capsys):
    record, journal, _, _, _ = execute(tmp_path)
    inspected = safety_lib.inspect_journal(journal.path)
    audit = journal.path.with_suffix(".audit.json")
    assert audit.is_file() and inspected["final_audit_outcome_recorded"]
    for value in (record, inspected, json.loads(audit.read_text())):
        with pytest.raises(ValueError, match="Result fields differ"):
            fixtures.runtime_module.pilot.bench.validate_record(value, {})
    snapshot = journal.path.read_bytes()
    assert fixtures.adapter.main(["inspect-journal", "--journal", str(journal.path)]) == 0
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err + audit.read_text() + journal.path.read_text()
    assert snapshot == journal.path.read_bytes()
