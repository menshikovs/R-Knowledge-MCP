"""Local F09 solo-operator approval and connectivity commands."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

F09_EXECUTOR_CONTAINER_NAME = re.compile(r"^rkmcp-probe-F09-[a-f0-9]{16}$")
F09_TOPOLOGY_RESOURCE_NAME = re.compile(r"^rkmcp-(?:candidate|egress)-F09-[a-f0-9]{12}$")
MAX_DOCKER_INVENTORY_BYTES = 64 << 10

SPEC = importlib.util.spec_from_file_location(
    "f09_solo_connectivity", Path(__file__).with_name("connectivity_harness.py")
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("F09 implementation unavailable")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def _request(path):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 8192:
            raise ValueError
        raw = os.read(descriptor, 8193)
        if len(raw) != metadata.st_size:
            raise ValueError
        return harness.validate_solo_request(json.loads(raw))
    except (OSError, ValueError, TypeError):
        raise harness.ConnectivityError("solo_request_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _confirm_run(record, *, terminal_input, terminal_output):
    if not terminal_input.isatty() or not terminal_output.isatty():
        raise harness.ConnectivityError("solo_interactive_terminal_required")
    claims = record["claims"]
    summary = {
        "attempt_id": claims["attempt_id"],
        "project_id": claims["project_id"],
        "source_commit": claims["source_commit"],
        "limit_usd_cents": claims["spend_control_limit_cents"],
        "scope": "one session, zero tasks, no Responses or inference",
        "spend_control": "best-effort; not a guaranteed billing ceiling",
        "expires_at": claims["expires_at"],
    }
    print(json.dumps(summary, sort_keys=True, indent=2), file=terminal_output)
    expected = (
        f"RUN F09 {claims['attempt_id']} {claims['spend_control_limit_cents']} "
        "CENTS ONE SESSION ZERO TASKS"
    )
    for phrase in (expected, harness.SOLO_CONFIRMATION):
        print("Type exactly: " + phrase, file=terminal_output, flush=True)
        try:
            actual = terminal_input.readline().rstrip("\r\n")
        except (EOFError, KeyboardInterrupt):
            raise harness.ConnectivityError("solo_confirmation_rejected") from None
        if actual != phrase:
            raise harness.ConnectivityError("solo_confirmation_rejected")


def _build_live_components(*, store, request, authorization, lease, journal, api_key, env_key):
    """Construct only the concrete, pinned F09 HTTP and Docker boundaries."""
    runtime_module = _load_docker_runtime()

    workspace_root = store.state_directory / "f09-workspaces"
    executor_runtime = runtime_module.F09ConnectivityRuntime(
        request["executor_image"], workspace_root=workspace_root
    )
    topology = runtime_module.RestrictedEgressNetwork(
        executor_runtime.docker,
        resource_scope="F09",
        command_env=runtime_module._operator_environment(os.environ),
    )
    workspace = workspace_root / store.validate()["claims"]["attempt_id"]
    executor = harness.F09DockerExecutorAdapter(executor_runtime, topology, workspace)
    client = authorization.create_client(api_key)
    return client, executor, env_key


def _live_credentials(environment=None):
    environment = os.environ if environment is None else environment
    api_key = environment.get("OPENAI_API_KEY")
    env_key = environment.get("OPENAI_EXECUTOR_API_KEY")

    def well_formed_opaque_key(value):
        return (
            isinstance(value, str)
            and 1 <= len(value) <= 4096
            and value.isascii()
            and all(33 <= ord(char) <= 126 for char in value)
        )

    if (
        not well_formed_opaque_key(api_key)
        or not well_formed_opaque_key(env_key)
        or api_key == env_key
    ):
        raise harness.ConnectivityError("solo_credentials_unavailable")
    return api_key, env_key


def _diagnostic_call(code, callback, /, *args, **kwargs):
    """Run one setup phase while exposing only its fixed diagnostic code."""
    try:
        return callback(*args, **kwargs)
    except (harness.ConnectivityError, harness.DurabilityError):
        raise
    except Exception:
        raise harness.ConnectivityError(code) from None


def _load_docker_runtime():
    runtime_path = Path(__file__).with_name("docker_runtime.py")
    runtime_spec = importlib.util.spec_from_file_location("f09_docker_runtime", runtime_path)
    if runtime_spec is None or runtime_spec.loader is None:
        raise harness.ConnectivityError("solo_runtime_configuration_mismatch")
    runtime_module = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(runtime_module)
    return runtime_module


def _f09_docker_inventory(runtime_module=None):
    """Read local F09 container/network names only; this never creates resources."""
    runtime_module = _load_docker_runtime() if runtime_module is None else runtime_module
    docker = shutil.which("docker")
    if not docker:
        raise harness.ConnectivityError("reconcile_docker_inventory_unavailable")
    environment = runtime_module._operator_environment(os.environ)
    inventory = {}
    for kind, arguments in (
        ("containers", ["ps", "--all", "--format", "{{.Names}}"]),
        ("networks", ["network", "ls", "--format", "{{.Name}}"]),
    ):
        command = [docker, "--host", runtime_module.F09_DOCKER_SOCKET, *arguments]
        try:
            result = runtime_module._bounded_run(command, timeout=10, env=environment)
        except Exception:
            raise harness.ConnectivityError("reconcile_docker_inventory_unavailable") from None
        if result.returncode != 0 or len(result.stdout) > MAX_DOCKER_INVENTORY_BYTES:
            raise harness.ConnectivityError("reconcile_docker_inventory_unavailable")
        try:
            names = result.stdout.decode("ascii", "strict").splitlines()
        except UnicodeError:
            raise harness.ConnectivityError("reconcile_docker_inventory_invalid") from None
        if any(
            not name or len(name) > 256 or any(ord(char) < 32 for char in name) for name in names
        ):
            raise harness.ConnectivityError("reconcile_docker_inventory_invalid")
        pattern = (
            F09_EXECUTOR_CONTAINER_NAME if kind == "containers" else F09_TOPOLOGY_RESOURCE_NAME
        )
        inventory[kind] = [name for name in names if pattern.fullmatch(name)]
    return inventory


def _read_private_bytes(path: Path, limit: int, *, synthetic: bool) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError
        if not synthetic and (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise ValueError
        chunks = []
        size = 0
        while size <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        raw = b"".join(chunks)
        after = path.lstat()
        if (
            size != metadata.st_size
            or (metadata.st_dev, metadata.st_ino) != (after.st_dev, after.st_ino)
            or len(raw) > limit
        ):
            raise ValueError
        return raw
    except (OSError, ValueError):
        raise harness.ConnectivityError("reconcile_evidence_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _require_private_directory(path: Path, *, synthetic: bool, same_device: int) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        if (
            path.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or resolved != path.absolute()
            or metadata.st_dev != same_device
            or (not synthetic and metadata.st_uid != os.geteuid())
            or (not synthetic and stat.S_IMODE(metadata.st_mode) != 0o700)
        ):
            raise ValueError
        return resolved
    except (OSError, ValueError):
        raise harness.ConnectivityError("reconcile_workspace_invalid") from None


def _validate_consumed_approval(store, attempt_id):
    if store.inspect()["state"] != "consumed_or_uncertain":
        raise harness.ConnectivityError("reconcile_approval_not_consumed")
    required_names = {"lease.gate", "approval.json", "consumption.started", "consumed.json"}
    if {entry.name for entry in store.root.iterdir()} != required_names:
        raise harness.ConnectivityError("reconcile_approval_state_invalid")
    record = store._read("approval.json")
    if (
        type(record) is not dict
        or set(record)
        != {
            "schema_version",
            "record_type",
            "synthetic",
            "request",
            "claims",
            "source_files_sha256",
            "confirmation_scheme",
        }
        or type(record["schema_version"]) is not int
        or record["schema_version"] != 1
        or record["record_type"] != harness.SOLO_APPROVAL_TYPE
        or record["synthetic"] is not store.synthetic
        or record["confirmation_scheme"] != "interactive_exact_phrase_v1"
        or type(record["source_files_sha256"]) is not str
        or not re.fullmatch(r"[a-f0-9]{64}", record["source_files_sha256"])
    ):
        raise harness.ConnectivityError("reconcile_approval_state_invalid")
    request = harness.validate_solo_request(record["request"])
    claims = record["claims"]
    if type(claims) is not dict or claims.get("attempt_id") != attempt_id:
        raise harness.ConnectivityError("reconcile_attempt_mismatch")
    try:
        issued_at = harness._parse_staging_utc_timestamp(claims["issued_at"])
        harness.parse_unverified_staging_authorization_claims(
            claims,
            expected_project_id=request["project_id"],
            expected_source_commit=request["source_commit"],
            expected_binding=store._binding(record),
            # Reconciliation checks the immutable claim structure at issuance;
            # it does not revive or reuse the expired approval.
            now_utc=issued_at,
        )
    except (KeyError, TypeError, ValueError, harness.ConnectivityError):
        raise harness.ConnectivityError("reconcile_approval_state_invalid") from None
    if claims["attempt_id"] != attempt_id:
        raise harness.ConnectivityError("reconcile_attempt_mismatch")
    expected = {
        "record_type": "f09_solo_operator_consumption",
        "schema_version": 1,
        "synthetic": store.synthetic,
        "approval_sha256": harness._sha256(store._bytes(record).decode()),
    }
    started = store._read("consumption.started")
    consumed = store._read("consumed.json")
    if started != expected or consumed != expected:
        raise harness.ConnectivityError("reconcile_approval_state_invalid")
    return record


def _verified_preflight_failure(store, attempt_id):
    lease_root = store.state_directory / harness.JOURNAL_DIRNAME
    _require_private_directory(
        lease_root,
        synthetic=store.synthetic,
        same_device=store.state_directory.stat().st_dev,
    )
    if _read_private_bytes(lease_root / "lease.gate", 1, synthetic=store.synthetic) != b"":
        raise harness.ConnectivityError("reconcile_lease_gate_invalid")
    if harness._release_marker_state(lease_root) != "clear":
        raise harness.ConnectivityError("reconcile_lease_release_state_uncertain")
    entries = list(lease_root.iterdir())
    run_directories = [entry for entry in entries if entry.name.startswith("run-")]
    if (
        len(run_directories) != 1
        or any(
            entry.name not in {"active.lock", "lease.gate", run_directories[0].name}
            for entry in entries
        )
        or {entry.name for entry in entries}
        != {"active.lock", "lease.gate", run_directories[0].name}
    ):
        raise harness.ConnectivityError("reconcile_journal_scope_invalid")
    lock_raw = _read_private_bytes(lease_root / "active.lock", 256, synthetic=store.synthetic)
    match = re.fullmatch(rb"managed_agents_connectivity_lease_v1:([a-f0-9]{32})\n", lock_raw)
    if match is None:
        raise harness.ConnectivityError("reconcile_lease_invalid")
    lease_id = match.group(1).decode("ascii")

    run_dir = run_directories[0]
    if not re.fullmatch(r"run-[a-f0-9]{32}", run_dir.name):
        raise harness.ConnectivityError("reconcile_journal_scope_invalid")
    _require_private_directory(
        run_dir, synthetic=store.synthetic, same_device=lease_root.stat().st_dev
    )
    journal_path = run_dir / "connectivity.jsonl"
    journal_raw = _read_private_bytes(journal_path, 8 << 20, synthetic=store.synthetic)
    report = harness.inspect_staging_journal(journal_path)
    if (
        report["integrity"] != "valid"
        or report["pending_intents"]
        or report["synthetic"] is not store.synthetic
        or report["lease_release_state"] != "clear"
        or _read_private_bytes(journal_path, 8 << 20, synthetic=store.synthetic) != journal_raw
    ):
        raise harness.ConnectivityError("reconcile_journal_invalid")
    try:
        journal_records = [
            json.loads(line, object_pairs_hook=_unique_json_object)
            for line in journal_raw.splitlines()
        ]
    except (ValueError, TypeError):
        raise harness.ConnectivityError("reconcile_journal_invalid") from None
    expected = [
        ("authorization_consume", "intent", "ok"),
        ("authorization_consume", "outcome", "consumed"),
        ("executor_preflight", "intent", "ok"),
        ("executor_preflight", "outcome", "preflight_failed"),
        ("audit_persist", "intent", "ok"),
        ("audit_persist", "outcome", "ok"),
    ]
    if len(journal_records) != len(expected):
        raise harness.ConnectivityError("reconcile_journal_not_preflight_only")
    for index, (record, (operation, event, code)) in enumerate(
        zip(journal_records, expected, strict=True)
    ):
        if (
            record.get("operation") != operation
            or record.get("event") != event
            or record.get("code") != code
            or record.get("synthetic") is not store.synthetic
            or record.get("intent_seq") != (index if event == "outcome" else None)
        ):
            raise harness.ConnectivityError("reconcile_journal_not_preflight_only")
    approval_record = _validate_consumed_approval(store, attempt_id)
    authorization_id = approval_record["claims"]["authorization_id"]
    authorization_hash = harness._sha256(authorization_id)
    if (
        journal_records[0]["resource_sha256"] != authorization_hash
        or journal_records[1]["resource_sha256"] != authorization_hash
        or any(record["resource_sha256"] is not None for record in journal_records[2:])
    ):
        raise harness.ConnectivityError("reconcile_journal_not_preflight_only")
    audit_path = run_dir / "connectivity-audit.json"
    audit_raw = _read_private_bytes(audit_path, 1 << 20, synthetic=store.synthetic)
    try:
        audit = json.loads(audit_raw, object_pairs_hook=_unique_json_object)
    except (ValueError, TypeError):
        raise harness.ConnectivityError("reconcile_audit_invalid") from None
    if (
        type(audit) is not dict
        or type(audit.get("schema_version")) is not int
        or audit.get("schema_version") != 2
        or audit.get("record_type") != "managed_agents_connectivity_audit_not_benchmark_result"
        or audit.get("synthetic") is not store.synthetic
        or audit.get("state") != "preflight"
        or audit.get("failure_code") != "executor_preflight_failed"
        or audit.get("session_creation_outcome") != "not_attempted"
        or audit.get("session_id_sha256") is not None
        or audit.get("environment_id_sha256") is not None
        or audit.get("connected_observed") is not False
        or audit.get("session_deletion_verified") is not False
        or audit.get("session_deletion_not_required") is not False
        or audit.get("executor_start_attempted") is not False
        or audit.get("executor_preflight_verified") is not False
        or audit.get("executor_termination_verified") is not False
        or audit.get("approval_consumption_durable") is not True
        or audit.get("cleanup_verified") is not False
        or type(audit.get("task_submission_count")) is not int
        or audit.get("task_submission_count") != 0
        or type(audit.get("responses_calls")) is not int
        or audit.get("responses_calls") != 0
        or audit.get("transitions") != []
    ):
        raise harness.ConnectivityError("reconcile_audit_not_preflight_only")
    return lease_id, journal_raw, audit, audit_raw


def _verified_reconciliation_workspace(store, attempt_id, runtime_module):
    same_device = store.state_directory.stat().st_dev
    parent = store.state_directory / "f09-workspaces"
    parent = _require_private_directory(parent, synthetic=store.synthetic, same_device=same_device)
    workspace = parent / attempt_id
    if workspace.is_symlink():
        raise harness.ConnectivityError("reconcile_workspace_invalid")
    resolved = _require_private_directory(
        workspace, synthetic=store.synthetic, same_device=same_device
    )
    if resolved.parent != parent or any(resolved.iterdir()):
        raise harness.ConnectivityError("reconcile_workspace_not_empty_or_scoped")
    acl = runtime_module._read_f09_workspace_acl(
        resolved, runtime_module._operator_environment(os.environ)
    )
    if not runtime_module._has_private_revoked_f09_workspace_acl(acl):
        raise harness.ConnectivityError("reconcile_workspace_acl_not_private")
    return resolved, parent


def _persist_reconciliation_record(journal, record):
    intent = journal.append("audit_persist", "intent")
    path = journal.root / "preflight-reconciliation.json"
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if type(written) is not int or not 0 < written <= len(raw) - offset:
                raise OSError("short reconciliation audit write")
            offset += written
        os.fsync(descriptor)
        harness._fsync_directory(journal.root, required=not journal.synthetic)
    except OSError:
        raise harness.DurabilityError("F09 reconciliation audit was not durable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    journal.append("audit_persist", "outcome", intent_seq=intent)


def _confirm_preflight_reconciliation(attempt_id, *, terminal_input, terminal_output):
    if not terminal_input.isatty() or not terminal_output.isatty():
        raise harness.ConnectivityError("solo_interactive_terminal_required")
    print(
        json.dumps(
            {
                "attempt_id": attempt_id,
                "action": "remove verified empty local workspace and release its F09 lease",
                "network_or_session_operations": 0,
                "approval_reuse": False,
            },
            sort_keys=True,
            indent=2,
        ),
        file=terminal_output,
    )
    phrase = f"RECONCILE F09 {attempt_id} PREFLIGHT ONLY"
    print("Type exactly: " + phrase, file=terminal_output, flush=True)
    if terminal_input.readline().rstrip("\r\n") != phrase:
        raise harness.ConnectivityError("solo_confirmation_rejected")


def _reconcile_preflight_failure(
    store,
    attempt_id,
    *,
    terminal_input,
    terminal_output,
    _synthetic_test=False,
):
    """Reconcile only a journal-proven failure before session or executor start."""
    if (
        type(store) is not harness.SoloOperatorApprovalStore
        or type(_synthetic_test) is not bool
        or store.synthetic is not _synthetic_test
        or store.read_only is not True
        or type(attempt_id) is not str
        or not harness.F09_ATTEMPT_ID.fullmatch(attempt_id)
    ):
        raise harness.ConnectivityError("reconcile_scope_rejected")
    _confirm_preflight_reconciliation(
        attempt_id, terminal_input=terminal_input, terminal_output=terminal_output
    )
    store._check_state()
    runtime_module = _load_docker_runtime()
    lease_root = store.state_directory / harness.JOURNAL_DIRNAME
    lease = harness.StagingLease(store.state_directory, synthetic=store.synthetic)
    if not (lease_root / "lease.gate").is_file() or (lease_root / "lease.gate").is_symlink():
        raise harness.ConnectivityError("reconcile_lease_gate_invalid")
    with harness._lease_operation_gate(lease_root, synthetic=store.synthetic):
        lease_id, prior_journal, prior_audit, prior_audit_raw = _verified_preflight_failure(
            store, attempt_id
        )
        workspace, workspace_parent = _verified_reconciliation_workspace(
            store, attempt_id, runtime_module
        )
        before = _f09_docker_inventory(runtime_module)
        if before["containers"] or before["networks"]:
            raise harness.ConnectivityError("reconcile_f09_resources_present")

        journal = harness.StagingJournal(store.state_directory, synthetic=store.synthetic)
        try:
            cleanup_intent = journal.append("local_reconciliation", "intent")
            try:
                workspace.rmdir()
                harness._fsync_directory(workspace_parent, required=not store.synthetic)
            except OSError:
                raise harness.ConnectivityError("reconcile_workspace_cleanup_unverified") from None
            journal.append(
                "local_reconciliation",
                "outcome",
                intent_seq=cleanup_intent,
                code="workspace_removed",
            )
            after = _f09_docker_inventory(runtime_module)
            if after["containers"] or after["networks"]:
                raise harness.ConnectivityError("reconcile_f09_resources_present")

            record = {
                "schema_version": 1,
                "record_type": "f09_preflight_local_reconciliation_not_connectivity_result",
                "synthetic": store.synthetic,
                "attempt_id": attempt_id,
                "original_journal_sha256": hashlib.sha256(prior_journal).hexdigest(),
                "original_audit_sha256": hashlib.sha256(prior_audit_raw).hexdigest(),
                "session_create_intent_absent": True,
                "executor_start_intent_absent": True,
                "original_cleanup_verified": prior_audit["cleanup_verified"],
                "workspace_removed_and_parent_synced": True,
                "f09_containers_absent_before_and_after": True,
                "f09_networks_absent_before_and_after": True,
                "approval_consumption_preserved": True,
                "network_or_session_operations": 0,
            }
            _persist_reconciliation_record(journal, record)
            release_intent = journal.append("lease_release", "intent")
            journal.append(
                "lease_release",
                "outcome",
                intent_seq=release_intent,
                code="release_authorized",
            )
            lease._lease_id = lease_id
            lease.acquired = True
            lease._release_while_gate_held()
            if lease.lock_path.exists() or harness._release_marker_state(lease_root) != "resolved":
                raise harness.ConnectivityError(
                    "reconcile_lease_release_unverified", uncertain=True
                )
            result = {
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
        finally:
            journal.close()
    return result


def _unexpected_lifecycle_error(store):
    """Classify an unexpected run failure from read-only approval state only."""
    try:
        state = store.inspect().get("state")
    except Exception:
        state = None
    if state == "pending_review":
        return harness.ConnectivityError("solo_lifecycle_failed_before_consumption")
    return harness.ConnectivityError("solo_lifecycle_failed_uncertain", uncertain=True)


def _execute_approved(
    store,
    *,
    terminal_input=None,
    terminal_output=None,
    synthetic_components=None,
):
    """Consume one reviewed approval and run the zero-task lifecycle.

    The synthetic injection is private test support. The command-line path never
    supplies it and rejects synthetic stores before constructing a client.
    """
    terminal_input = sys.stdin if terminal_input is None else terminal_input
    terminal_output = sys.stderr if terminal_output is None else terminal_output
    if type(store) is not harness.SoloOperatorApprovalStore:
        raise harness.ConnectivityError("solo_approval_invalid")
    if store.synthetic and synthetic_components is None:
        raise harness.ConnectivityError("solo_synthetic_approval_rejected")
    if not store.synthetic and synthetic_components is not None:
        raise harness.ConnectivityError("solo_synthetic_approval_rejected")

    record = store.validate()
    if store.inspect()["state"] != "pending_review":
        raise harness.ConnectivityError("solo_approval_already_used_or_pending")
    _confirm_run(record, terminal_input=terminal_input, terminal_output=terminal_output)
    request = record["request"]
    lease = harness.StagingLease(store.state_directory, synthetic=store.synthetic)
    journal = harness.StagingJournal(store.state_directory, synthetic=store.synthetic)
    authorization = harness.SoloOperatorAuthorization(store, lease)
    client = None
    controller = None
    try:
        if store.synthetic:
            client, executor = _diagnostic_call(
                "solo_synthetic_components_unavailable",
                synthetic_components,
                store=store,
                request=request,
                authorization=authorization,
                lease=lease,
                journal=journal,
            )
            environment_key = "synthetic-environment-key"
        else:
            api_key, environment_key = _live_credentials()
            client, executor, environment_key = _diagnostic_call(
                "solo_live_components_unavailable",
                _build_live_components,
                store=store,
                request=request,
                authorization=authorization,
                lease=lease,
                journal=journal,
                api_key=api_key,
                env_key=environment_key,
            )
        controller = _diagnostic_call(
            "solo_harness_initialization_failed",
            harness.ConnectivityHarness,
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
        try:
            result = controller.run()
        except (harness.ConnectivityError, harness.DurabilityError):
            raise
        except Exception:
            raise _unexpected_lifecycle_error(store) from None
        if result.get("cleanup_verified") is not True:
            raise harness.ConnectivityError("cleanup_unverified")
        if result.get("connected_observed") is not True or result.get("failure_code") is not None:
            raise harness.ConnectivityError(result.get("failure_code") or "connection_not_verified")
        return result
    except BaseException:
        if controller is None:
            journal.close()
            if client is not None:
                client.close()
        raise


def main(
    argv=None,
    *,
    _store_factory=None,
    _test_components=None,
    _test_input=None,
    _test_output=None,
):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    approve = sub.add_parser(
        "approve", help="Interactively record one future approval; never run it"
    )
    approve.add_argument("--request", type=Path, required=True, help="Non-secret reviewed JSON")
    approve.add_argument(
        "--state-dir", type=Path, required=True, help="Private persistent Linux directory"
    )
    approve.add_argument("--expires-in-seconds", type=int, required=True)
    inspect = sub.add_parser("inspect", help="Read-only state summary; cannot authorize recovery")
    inspect.add_argument("--state-dir", type=Path, required=True)
    run = sub.add_parser(
        "run",
        help="LIVE / potentially paid: consume one approval for a zero-task connection",
    )
    run.add_argument("--state-dir", type=Path, required=True)
    reconcile = sub.add_parser(
        "reconcile-preflight",
        help="Local-only recovery for a journal-proven failure before session creation",
    )
    reconcile.add_argument("--state-dir", type=Path, required=True)
    reconcile.add_argument("--attempt-id", required=True)
    args = parser.parse_args(argv)
    try:
        if _store_factory is None:
            store = harness.SoloOperatorApprovalStore(
                args.state_dir, read_only=args.command in {"inspect", "reconcile-preflight"}
            )
        else:
            store = _store_factory(
                args.state_dir, read_only=args.command in {"inspect", "reconcile-preflight"}
            )
        if args.command == "approve":
            result = store.approve(
                _request(args.request), expires_in_seconds=args.expires_in_seconds
            )
        elif args.command == "inspect":
            result = store.inspect()
        elif args.command == "reconcile-preflight":
            result = _reconcile_preflight_failure(
                store,
                args.attempt_id,
                terminal_input=_test_input if _test_input is not None else sys.stdin,
                terminal_output=_test_output if _test_output is not None else sys.stderr,
            )
        else:
            result = _execute_approved(
                store,
                terminal_input=_test_input,
                terminal_output=_test_output,
                synthetic_components=_test_components,
            )
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 0
    except (harness.ConnectivityError, harness.DurabilityError) as exc:
        print(getattr(exc, "code", "solo_state_unavailable"), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("solo_run_interrupted_uncertain", file=sys.stderr)
        return 2
    except Exception:
        # Never print exception text from clients, subprocesses or external events.
        code = (
            "f09_reconciliation_failed"
            if args.command == "reconcile-preflight"
            else "f09_run_failed"
        )
        print(code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
