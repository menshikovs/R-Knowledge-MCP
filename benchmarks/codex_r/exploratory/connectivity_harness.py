"""Staging-only Managed Agents executor connectivity check.

This module intentionally has no task submission or Responses API surface. It
must not be used to run R01-A. Live use requires a separately approved staging
project and separately restricted application/environment credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

import httpx

_CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "managed_agents_connectivity_executor_contract",
    Path(__file__).with_name("executor_contract.py"),
)
if _CONTRACT_SPEC is None or _CONTRACT_SPEC.loader is None:
    raise RuntimeError("Executor URL and sanitizer contract is unavailable")
contract = importlib.util.module_from_spec(_CONTRACT_SPEC)
_CONTRACT_SPEC.loader.exec_module(contract)


API_ORIGIN = "https://api.openai.com"
JOURNAL_DIRNAME = "managed-agents-connectivity"
PROJECT_CONFIRMATION_ENV = "RKMCP_CONNECTIVITY_STAGING_PROJECT_ID"
_LIVE_CLIENT_CAPABILITY = object()
MAX_RESPONSE_BYTES = 2 << 20
MAX_SSE_EVENT_BYTES = 256 << 10
MAX_SSE_LINE_BYTES = 64 << 10
MAX_SSE_TOTAL_BYTES = 8 << 20
MAX_EVENTS = 10_000
MAX_CREATE_SECONDS = 30.0
MAX_CONNECT_SECONDS = 300.0
MAX_CLEANUP_SECONDS = 60.0
MAX_RELEASE_MARKERS = 10_000
MAX_STAGING_AUTHORIZATION_SECONDS = 15 * 60
MAX_STAGING_AUTHORIZATION_RECORD_BYTES = 16 << 10
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
RELEASE_ID = re.compile(r"^[a-f0-9]{32}$")
ALLOWED_STATES = frozenset(
    {
        "preflight",
        "create_intent",
        "session_created",
        "session_unknown",
        "stream_open",
        "executor_start_intent",
        "executor_running",
        "connected",
        "timed_out",
        "failed",
        "stop_executor",
        "executor_stopped",
        "executor_stop_unverified",
        "delete_intent",
        "session_deleted",
        "cleanup_verified",
        "cleanup_unverified",
    }
)
STATE_TRANSITIONS = {
    "preflight": {"create_intent"},
    "create_intent": {"session_created", "session_unknown", "failed"},
    "session_created": {"stream_open", "failed", "timed_out", "stop_executor"},
    "stream_open": {"executor_start_intent", "failed", "timed_out", "stop_executor"},
    "executor_start_intent": {"executor_running", "failed", "timed_out", "stop_executor"},
    "executor_running": {"connected", "failed", "timed_out", "stop_executor"},
    "connected": {"stop_executor"},
    "session_unknown": {"stop_executor"},
    "timed_out": {"stop_executor"},
    "failed": {"stop_executor"},
    "stop_executor": {"executor_stopped", "executor_stop_unverified"},
    "executor_stopped": {"delete_intent", "cleanup_verified", "cleanup_unverified"},
    "executor_stop_unverified": {"delete_intent", "cleanup_unverified"},
    "delete_intent": {"session_deleted", "cleanup_unverified"},
    "session_deleted": {"cleanup_verified", "cleanup_unverified"},
    "cleanup_verified": set(),
    "cleanup_unverified": set(),
}
ALLOWED_OPERATIONS = frozenset(
    {
        "authorization_consume",
        "session_create",
        "stream_open",
        "executor_start",
        "executor_stop",
        "session_delete",
        "audit_persist",
        "lease_release",
    }
)


class ConnectivityError(RuntimeError):
    """Connectivity check failed; details are represented by safe codes only."""

    def __init__(self, code: str, *, state: str | None = None, uncertain=False):
        super().__init__("Managed Agents connectivity check failed")
        self.code = code if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else "operation_failed"
        self.state = state
        self.uncertain = bool(uncertain)


class SpendControlApproval:
    """Externally approved finite session spend limit; never supplies a default."""

    __slots__ = ("limit", "approval_reference", "billing_owner_acknowledged", "_sealed")

    def __init__(self, limit, approval_reference, billing_owner_acknowledged):
        object.__setattr__(self, "limit", limit)
        object.__setattr__(self, "approval_reference", approval_reference)
        object.__setattr__(self, "billing_owner_acknowledged", billing_owner_acknowledged)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("Spend control approval is immutable")
        object.__setattr__(self, name, value)


SPEND_APPROVAL_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
STAGING_AUTHORIZATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SOURCE_COMMIT_SHA = re.compile(r"^[a-f0-9]{40}$")
F09_ATTEMPT_ID = re.compile(r"^F09-[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
STAGING_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "issuer_id",
        "project_name",
        "project_id",
        "source_commit",
        "issued_at",
        "session_count",
        "task_count",
        "task_submission_allowed",
        "responses_inference_allowed",
        "spend_control_limit_cents",
        "expires_at",
        "billing_owner_id",
        "billing_owner_approval_reference",
        "billing_owner_acknowledged",
        "billing_risk_acknowledged",
        "attempt_id",
        "configuration_sha256",
        "credential_scope_sha256",
    }
)
STAGING_AUTHORIZATION_ISSUE_FIELDS = STAGING_AUTHORIZATION_FIELDS - {
    "schema_version",
    "authorization_id",
    "issuer_id",
    "issued_at",
}
STAGING_AUTHORIZATION_STORE_DIRNAME = "f09-staging-one-time-authorization"
STAGING_AUTHORIZATION_RECORD_TYPE = "f09_staging_authorization_not_r01a"
STAGING_AUTHORIZATION_CONSUMED_TYPE = "f09_staging_authorization_consumed_not_r01a"


class StagingAuthorizationBinding:
    """Expected non-secret request scope; structural validation grants no authority."""

    __slots__ = ("attempt_id", "configuration_sha256", "credential_scope_sha256", "limit")

    def __init__(self, attempt_id, configuration_sha256, credential_scope_sha256, limit):
        if (
            type(attempt_id) is not str
            or not F09_ATTEMPT_ID.fullmatch(attempt_id)
            or type(configuration_sha256) is not str
            or not SHA256.fullmatch(configuration_sha256)
            or type(credential_scope_sha256) is not str
            or not SHA256.fullmatch(credential_scope_sha256)
            or type(limit) is not int
            or limit <= 0
        ):
            raise ConnectivityError("staging_authorization_binding_invalid")
        object.__setattr__(self, "attempt_id", attempt_id)
        object.__setattr__(self, "configuration_sha256", configuration_sha256)
        object.__setattr__(self, "credential_scope_sha256", credential_scope_sha256)
        object.__setattr__(self, "limit", limit)

    def __setattr__(self, _name, _value):
        raise AttributeError("Staging authorization bindings are immutable")


def connectivity_configuration_sha256(
    agent_config: dict, *, create_seconds: float, connect_seconds: float, cleanup_seconds: float
) -> str:
    """Bind the parameters controlled by this harness, excluding all key material.

    This does not verify executable/image provenance or authenticate an approver.
    """
    budgets = (create_seconds, connect_seconds, cleanup_seconds)
    caps = (MAX_CREATE_SECONDS, MAX_CONNECT_SECONDS, MAX_CLEANUP_SECONDS)
    if any(
        type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= cap
        for value, cap in zip(budgets, caps, strict=True)
    ):
        raise ConnectivityError("staging_authorization_configuration_invalid")
    agent = StagingAgentsClient._validate_agent_config(agent_config)
    record = {
        "agent": agent,
        "workspace_directory": "/workspace",
        "create_seconds": float(create_seconds),
        "connect_seconds": float(connect_seconds),
        "cleanup_seconds": float(cleanup_seconds),
        "session_count": 1,
        "task_count": 0,
        "responses_calls": 0,
    }
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def unverified_credential_scope_sha256(attestation: object, *, expected_project_id: str) -> str:
    """Hash explicit non-secret dashboard metadata, never runtime credentials.

    The digest binds a reviewed attestation. It does not verify that loaded keys
    are the listed resources or that the provider grants these permissions.
    """
    identifiers = {
        "organization_id",
        "project_id",
        "owner_id",
        "application_key_resource_id",
        "environment_key_label",
        "operator_id",
        "reviewer_id",
    }
    fields = identifiers | {
        "verification_method",
        "application_permissions",
        "environment_permissions",
        "matching_organization_project_owner_confirmed",
        "reviewed_at",
    }
    if type(attestation) is not dict or set(attestation) != fields:
        raise ConnectivityError("staging_credential_attestation_invalid")
    for field in identifiers:
        value = attestation[field]
        if (
            type(value) is not str
            or not STAGING_AUTHORIZATION_ID.fullmatch(value)
            or contract.sanitize_reference_data(value, redact_urls=True) != value
        ):
            raise ConnectivityError("staging_credential_attestation_invalid")
    if (
        type(attestation["verification_method"]) is not str
        or attestation["verification_method"] != "operator_dashboard_attestation"
        or attestation["project_id"] != expected_project_id
        or type(attestation["application_permissions"]) is not list
        or type(attestation["environment_permissions"]) is not list
        or len(attestation["application_permissions"]) != 2
        or len(attestation["environment_permissions"]) != 1
        or any(
            type(permission) is not str
            for permission in attestation["application_permissions"]
            + attestation["environment_permissions"]
        )
        or attestation["application_permissions"] != ["api.agents.read", "api.agents.write"]
        or attestation["environment_permissions"] != ["api.agents.environments.connect"]
        or attestation["matching_organization_project_owner_confirmed"] is not True
        or type(attestation["reviewed_at"]) is not str
    ):
        raise ConnectivityError("staging_credential_attestation_invalid")
    try:
        _parse_staging_utc_timestamp(attestation["reviewed_at"])
    except (ValueError, OverflowError):
        raise ConnectivityError("staging_credential_attestation_invalid") from None
    return hashlib.sha256(
        json.dumps(attestation, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_staging_utc_timestamp(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("non-canonical UTC timestamp")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(UTC)


def parse_unverified_staging_authorization_claims(
    claims: object,
    *,
    expected_project_id: str,
    expected_source_commit: str,
    expected_binding: StagingAuthorizationBinding | None = None,
    now_utc: datetime,
) -> Mapping[str, object]:
    """Validate bounded authorization claims without granting authority.

    This parser authenticates no issuer. The solo workflow separately requires
    local interactive confirmation; parsing a caller's JSON grants no authority.
    """
    if (
        type(claims) is not dict
        or len(claims) != len(STAGING_AUTHORIZATION_FIELDS)
        or set(claims) != STAGING_AUTHORIZATION_FIELDS
        or type(expected_binding) is not StagingAuthorizationBinding
        or type(expected_project_id) is not str
        or not PROJECT_ID.fullmatch(expected_project_id)
        or type(expected_source_commit) is not str
        or not SOURCE_COMMIT_SHA.fullmatch(expected_source_commit)
        or not isinstance(now_utc, datetime)
        or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
    ):
        raise ConnectivityError("staging_authorization_claims_invalid")

    strings = (
        claims["authorization_id"],
        claims["issuer_id"],
        claims["project_name"],
        claims["project_id"],
        claims["source_commit"],
        claims["issued_at"],
        claims["expires_at"],
        claims["billing_owner_id"],
        claims["billing_owner_approval_reference"],
        claims["attempt_id"],
        claims["configuration_sha256"],
        claims["credential_scope_sha256"],
    )
    if any(type(value) is not str or len(value) > 256 for value in strings):
        raise ConnectivityError("staging_authorization_claims_invalid")

    if (
        type(claims["schema_version"]) is not int
        or claims["schema_version"] != 2
        or not STAGING_AUTHORIZATION_ID.fullmatch(claims["authorization_id"])
        or not STAGING_AUTHORIZATION_ID.fullmatch(claims["issuer_id"])
        or claims["project_name"] != "rkmcp-staging"
        or claims["project_id"] != expected_project_id
        or not PROJECT_ID.fullmatch(claims["project_id"])
        or claims["source_commit"] != expected_source_commit
        or not SOURCE_COMMIT_SHA.fullmatch(claims["source_commit"])
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", claims["issued_at"])
        or type(claims["session_count"]) is not int
        or claims["session_count"] != 1
        or type(claims["task_count"]) is not int
        or claims["task_count"] != 0
        or claims["task_submission_allowed"] is not False
        or claims["responses_inference_allowed"] is not False
        or type(claims["spend_control_limit_cents"]) is not int
        or claims["spend_control_limit_cents"] != expected_binding.limit
        or claims["spend_control_limit_cents"] <= 0
        or claims["attempt_id"] != expected_binding.attempt_id
        or not F09_ATTEMPT_ID.fullmatch(claims["attempt_id"])
        or claims["configuration_sha256"] != expected_binding.configuration_sha256
        or claims["credential_scope_sha256"] != expected_binding.credential_scope_sha256
        or not STAGING_AUTHORIZATION_ID.fullmatch(claims["billing_owner_id"])
        or not SPEND_APPROVAL_REFERENCE.fullmatch(claims["billing_owner_approval_reference"])
        or claims["billing_owner_acknowledged"] is not True
        or claims["billing_risk_acknowledged"] is not True
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", claims["expires_at"])
    ):
        raise ConnectivityError("staging_authorization_claims_invalid")

    try:
        issued_at = _parse_staging_utc_timestamp(claims["issued_at"])
        expiration = _parse_staging_utc_timestamp(claims["expires_at"])
        current_time = now_utc.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ConnectivityError("staging_authorization_claims_invalid") from None
    if (
        issued_at > current_time
        or expiration <= current_time
        or expiration <= issued_at
        or (expiration - issued_at).total_seconds() > MAX_STAGING_AUTHORIZATION_SECONDS
        or (current_time - issued_at).total_seconds() > MAX_STAGING_AUTHORIZATION_SECONDS
    ):
        raise ConnectivityError("staging_authorization_claims_invalid")

    return MappingProxyType(
        {
            "authorization_id": claims["authorization_id"],
            "issuer_id": claims["issuer_id"],
            "project_id": claims["project_id"],
            "source_commit": claims["source_commit"],
            "issued_at": issued_at,
            "session_count": claims["session_count"],
            "task_count": claims["task_count"],
            "spend_control_limit_cents": claims["spend_control_limit_cents"],
            "expires_at": expiration,
            "billing_owner_id": claims["billing_owner_id"],
            "billing_owner_approval_reference": claims["billing_owner_approval_reference"],
            "billing_owner_acknowledged": claims["billing_owner_acknowledged"],
            "billing_risk_acknowledged": claims["billing_risk_acknowledged"],
            "attempt_id": claims["attempt_id"],
            "configuration_sha256": claims["configuration_sha256"],
            "credential_scope_sha256": claims["credential_scope_sha256"],
        }
    )


def require_trusted_staging_authorization(
    claims: object,
    *,
    expected_project_id: str,
    expected_source_commit: str,
    expected_binding: StagingAuthorizationBinding | None = None,
    now_utc: datetime,
) -> None:
    """Fail closed until a separately reviewed trusted issuer is configured."""
    parse_unverified_staging_authorization_claims(
        claims,
        expected_project_id=expected_project_id,
        expected_source_commit=expected_source_commit,
        expected_binding=expected_binding,
        now_utc=now_utc,
    )
    raise ConnectivityError("staging_authorization_issuer_unavailable")


def _validated_spend_control(approval: SpendControlApproval | None) -> dict:
    if type(approval) is not SpendControlApproval:
        raise ConnectivityError("spend_control_approval_required")
    limit = approval.limit
    positive_integer_cents = type(limit) is int and limit > 0
    if (
        not positive_integer_cents
        or not isinstance(approval.approval_reference, str)
        or not SPEND_APPROVAL_REFERENCE.fullmatch(approval.approval_reference)
        or approval.billing_owner_acknowledged is not True
    ):
        raise ConnectivityError("spend_control_approval_invalid")
    return {"limit": limit}


class DurabilityError(RuntimeError):
    """Private staging evidence could not be written durably."""


class SessionUnknown(ConnectivityError):
    """Session creation may have succeeded, but its ID was not confirmed."""


class BoundedCallTimeout(TimeoutError):
    """Caller deadline expired; settled signals eventual callback disposal."""

    def __init__(self, settled: threading.Event):
        super().__init__()
        self.settled = settled


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_call(
    callback,
    *,
    deadline: float,
    clock,
    real_deadline: float | None = None,
    late_cleanup=None,
    late_cleanup_on_error=None,
):
    """Bound waiting and dispose eventual results exactly once after abandonment."""
    if real_deadline is None:
        real_deadline = time.monotonic() + max(0.0, deadline - clock())
    completed = threading.Event()
    settled = threading.Event()
    lock = threading.Lock()
    result = []
    abandoned = False
    cleanup_claimed = False

    def expired():
        return clock() >= deadline or time.monotonic() >= real_deadline

    def worker():
        nonlocal abandoned, cleanup_claimed
        # Do not begin an external operation after its budget expired.
        with lock:
            if abandoned or expired():
                result.append((False, TimeoutError()))
                completed.set()
                settled.set()
                return
        try:
            value = (True, callback())
        except BaseException as exc:
            value = (False, exc)
        with lock:
            result.append(value)
            dispose = abandoned or expired()
            cleanup_claimed = dispose
            completed.set()
        try:
            if dispose and value[0] and late_cleanup is not None:
                late_cleanup(value[1])
            elif dispose and not value[0] and late_cleanup_on_error is not None:
                late_cleanup_on_error()
        except BaseException:
            pass  # Best effort only; this cannot certify cleanup.
        finally:
            settled.set()

    threading.Thread(target=worker, daemon=True).start()
    while not completed.wait(0.01):
        with lock:
            if expired():
                abandoned = True
                raise BoundedCallTimeout(settled)
    with lock:
        timed_out = abandoned or expired()
        success, value = result[0]
        dispose = timed_out and not cleanup_claimed
        cleanup_claimed = cleanup_claimed or dispose
    if timed_out:
        if dispose and success and late_cleanup is not None:

            def cleanup_then_settle():
                try:
                    late_cleanup(value)
                except BaseException:
                    pass
                finally:
                    settled.set()

            threading.Thread(target=cleanup_then_settle, daemon=True).start()
        elif dispose and not success and late_cleanup_on_error is not None:

            def error_cleanup_then_settle():
                try:
                    late_cleanup_on_error()
                except BaseException:
                    pass
                finally:
                    settled.set()

            threading.Thread(target=error_cleanup_then_settle, daemon=True).start()
        raise BoundedCallTimeout(settled)
    if success:
        return value
    raise value


def _check_external_private_root(path: Path, *, allow_repository=False) -> Path:
    root = path.expanduser().absolute()
    repo = Path(__file__).resolve().parents[3]
    try:
        resolved = root.resolve(strict=False)
        resolved.relative_to(repo)
    except ValueError:
        inside_repository = False
    else:
        inside_repository = True
    if inside_repository and not allow_repository:
        raise DurabilityError("Connectivity evidence must be outside the repository")
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise DurabilityError("Linked connectivity evidence paths are forbidden")
    return resolved


def _fsync_directory(path: Path, *, required: bool) -> bool:
    if os.name == "nt":
        if required:
            raise DurabilityError("Live connectivity evidence requires POSIX directory fsync")
        return False
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    except OSError:
        if required:
            raise DurabilityError("Connectivity directory fsync failed") from None
        return False
    finally:
        os.close(descriptor)
    return True


def _ensure_private_directory(path: Path, *, synthetic: bool) -> None:
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise DurabilityError("Connectivity evidence directory is not owner-only")
        for created in reversed(missing):
            _fsync_directory(created.parent, required=not synthetic)


@contextmanager
def _lease_operation_gate(root: Path, *, synthetic: bool):
    """Serialize lease acquisition/release across processes; never unlink this gate."""
    path = root / "lease.gate"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = None
    locked = False
    try:
        try:
            descriptor = os.open(path, flags | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            descriptor = os.open(path, flags, 0o600)
            created = False
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("lease gate is not a regular file")
        if os.name == "nt":
            if metadata.st_size == 0:
                if os.write(descriptor, b"\0") != 1:
                    raise OSError("short lease gate initialization")
                os.fsync(descriptor)
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            os.chmod(path, 0o600)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
                raise OSError("lease gate permissions are not private")
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        if created:
            os.fsync(descriptor)
            _fsync_directory(root, required=not synthetic)
        yield
    except (OSError, BlockingIOError) as exc:
        if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in {11, 13, 36}:
            raise DurabilityError("A staging lease operation is already in progress") from None
        raise DurabilityError("Staging lease operation gate is unavailable") from None
    finally:
        if descriptor is not None:
            if locked:
                try:
                    if os.name == "nt":
                        import msvcrt

                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)


def _release_marker_bytes(event: str, release_id: str, lease_hash: str) -> bytes:
    record = {
        "schema_version": 1,
        "record_type": f"managed_agents_lease_release_{event}",
        "release_id": release_id,
        "lease_sha256": lease_hash,
    }
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _write_release_marker(root: Path, path: Path, payload: bytes, *, synthetic: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags, 0o600)
        if os.write(descriptor, payload) != len(payload):
            raise OSError("short lease release marker write")
        os.fsync(descriptor)
        _fsync_directory(root, required=not synthetic)
    except BaseException:
        raise DurabilityError("Lease release state could not be recorded") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _release_marker_state(root: Path) -> str:
    """Return clear/resolved/unresolved/corrupt without changing release evidence."""
    try:
        markers = [entry for entry in root.iterdir() if entry.name.startswith("release-")]
        if len(markers) > MAX_RELEASE_MARKERS * 2:
            return "corrupt"
        pending_ids = set()
        complete_ids = set()
        pending_hashes = {}
        complete_hashes = {}
        for path in markers:
            match = re.fullmatch(r"release-([a-f0-9]{32})\.(pending|complete)", path.name)
            if match is None:
                return "corrupt"
            release_id, event = match.groups()
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            descriptor = os.open(path, flags)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 512:
                    return "corrupt"
                payload = os.read(descriptor, 513)
            finally:
                os.close(descriptor)
            try:
                record = json.loads(payload)
            except (UnicodeError, ValueError):
                return "corrupt"
            expected_keys = {"schema_version", "record_type", "release_id", "lease_sha256"}
            if (
                not isinstance(record, dict)
                or set(record) != expected_keys
                or type(record["schema_version"]) is not int
                or record["schema_version"] != 1
                or record["record_type"] != f"managed_agents_lease_release_{event}"
                or record["release_id"] != release_id
                or not isinstance(record["lease_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", record["lease_sha256"])
                or payload != _release_marker_bytes(event, release_id, record["lease_sha256"])
            ):
                return "corrupt"
            if event == "pending":
                pending_ids.add(release_id)
                pending_hashes[release_id] = record["lease_sha256"]
            else:
                complete_ids.add(release_id)
                complete_hashes[release_id] = record["lease_sha256"]
        if complete_ids - pending_ids:
            return "corrupt"
        if any(pending_hashes[rid] != complete_hashes[rid] for rid in complete_ids):
            return "corrupt"
        if len(pending_ids) > MAX_RELEASE_MARKERS:
            return "corrupt"
        return (
            "unresolved" if pending_ids - complete_ids else "resolved" if pending_ids else "clear"
        )
    except (OSError, ValueError, TypeError):
        return "corrupt"


class StagingLease:
    """Exclusive staging lock; uncertain runs deliberately leave the lock file."""

    def __init__(self, state_directory: Path, *, synthetic: bool):
        self.root = (
            _check_external_private_root(Path(state_directory), allow_repository=synthetic)
            / JOURNAL_DIRNAME
        )
        self.synthetic = synthetic
        self.lock_path = self.root / "active.lock"
        self.acquired = False
        self._lease_id = None

    def acquire(self) -> None:
        _ensure_private_directory(self.root, synthetic=self.synthetic)
        with _lease_operation_gate(self.root, synthetic=self.synthetic):
            release_state = _release_marker_state(self.root)
            if release_state in {"unresolved", "corrupt"}:
                raise DurabilityError("A lease release requires operator reconciliation")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            try:
                descriptor = os.open(self.lock_path, flags, 0o600)
            except FileExistsError:
                raise DurabilityError("A staging connectivity lease already exists") from None
            lease_id = uuid.uuid4().hex
            try:
                payload = f"managed_agents_connectivity_lease_v1:{lease_id}\n".encode("ascii")
                if os.write(descriptor, payload) != len(payload):
                    raise OSError("short lease write")
                os.fsync(descriptor)
                _fsync_directory(self.root, required=not self.synthetic)
            except BaseException:
                os.close(descriptor)
                raise DurabilityError("Staging connectivity lease is not durable") from None
            os.close(descriptor)
            self._lease_id = lease_id
            self.acquired = True

    def release(self) -> None:
        if not self.acquired:
            raise DurabilityError("Staging connectivity lease is not held")
        with _lease_operation_gate(self.root, synthetic=self.synthetic):
            release_id = uuid.uuid4().hex
            lease_hash = _sha256(self._lease_id)
            pending = self.root / f"release-{release_id}.pending"
            complete = self.root / f"release-{release_id}.complete"
            _write_release_marker(
                self.root,
                pending,
                _release_marker_bytes("pending", release_id, lease_hash),
                synthetic=self.synthetic,
            )
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                descriptor = os.open(self.lock_path, flags)
                try:
                    lock_record = os.read(descriptor, 256)
                finally:
                    os.close(descriptor)
                expected = f"managed_agents_connectivity_lease_v1:{self._lease_id}\n".encode(
                    "ascii"
                )
                if lock_record != expected:
                    raise OSError("lease identity changed")
                self.lock_path.unlink()
                _fsync_directory(self.root, required=not self.synthetic)
                _write_release_marker(
                    self.root,
                    complete,
                    _release_marker_bytes("complete", release_id, lease_hash),
                    synthetic=self.synthetic,
                )
            except BaseException:
                raise DurabilityError(
                    "Lease release is unresolved; operator reconciliation required"
                ) from None
            self.acquired = False


class StagingJournal:
    """Append-only hash-chained journal in a namespace separate from R01-A."""

    def __init__(
        self,
        root: Path,
        *,
        synthetic: bool,
        write=os.write,
        fsync=os.fsync,
    ):
        if type(synthetic) is not bool:
            raise DurabilityError("Synthetic evidence mode must be explicit")
        self.root = (
            _check_external_private_root(Path(root), allow_repository=synthetic) / JOURNAL_DIRNAME
        )
        self.synthetic = synthetic
        _ensure_private_directory(self.root, synthetic=synthetic)
        self.run_id = uuid.uuid4().hex
        self.root = self.root / f"run-{self.run_id}"
        _ensure_private_directory(self.root, synthetic=synthetic)
        if not synthetic and (os.name == "nt"):
            raise DurabilityError("Live connectivity journal requires POSIX durability")
        self.path = self.root / "connectivity.jsonl"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            self.fd = os.open(self.path, flags, 0o600)
            _fsync_directory(self.root, required=not synthetic)
        except OSError:
            if getattr(self, "fd", None) is not None:
                os.close(self.fd)
                self.fd = None
            raise DurabilityError("Connectivity journal could not be created") from None
        self._write, self._fsync = write, fsync
        self._lock = threading.Lock()
        self.sequence = 0
        self.previous = "0" * 64
        self.failed = False
        self.pending: dict[int, tuple[str, str | None]] = {}

    def append(
        self,
        operation: str,
        event: str,
        *,
        intent_seq: int | None = None,
        code="ok",
        resource_sha256: str | None = None,
    ) -> int:
        if operation not in ALLOWED_OPERATIONS or event not in {"intent", "outcome"}:
            raise DurabilityError("Unknown connectivity journal transition")
        if (event == "intent" and intent_seq is not None) or (
            event == "outcome" and (type(intent_seq) is not int or intent_seq <= 0)
        ):
            raise DurabilityError("Invalid connectivity journal reference")
        if resource_sha256 is not None and not re.fullmatch(r"[a-f0-9]{64}", resource_sha256):
            raise DurabilityError("Invalid connectivity journal resource reference")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "operation_failed"
        with self._lock:
            if self.failed:
                raise DurabilityError("Connectivity journal has an incomplete write")
            if event == "outcome" and self.pending.get(intent_seq) != (
                operation,
                resource_sha256,
            ):
                raise DurabilityError("Connectivity outcome has no matching durable intent")
            entry = {
                "schema_version": 1,
                "record_type": "managed_agents_connectivity_journal_not_benchmark_result",
                "synthetic": self.synthetic,
                "seq": self.sequence + 1,
                "operation": operation,
                "event": event,
                "intent_seq": intent_seq,
                "code": code,
                "resource_sha256": resource_sha256,
                "previous_sha256": self.previous,
            }
            raw = (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode()
            try:
                written = self._write(self.fd, raw)
                if written != len(raw):
                    raise OSError("short journal write")
                self._fsync(self.fd)
            except BaseException:
                self.failed = True
                raise DurabilityError("Connectivity journal write was not durable") from None
            self.sequence += 1
            self.previous = hashlib.sha256(raw).hexdigest()
            if event == "intent":
                self.pending[self.sequence] = (operation, resource_sha256)
            else:
                del self.pending[intent_seq]
            return self.sequence

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class IssuedStagingCapability:
    """In-memory synthetic capability; its representation never contains bytes."""

    __slots__ = ("authorization_id", "_value")

    def __init__(self, authorization_id: str, value: bytes):
        self.authorization_id = authorization_id
        self._value = value

    def __repr__(self) -> str:
        return f"IssuedStagingCapability({self.authorization_id!r}, value=<redacted>)"


class OfflineStagingAuthorizationStore:
    """Synthetic-only model of one-time F09 capability issuance and consumption.

    This store deliberately cannot run in live mode. The issuer/runtime role
    names and callbacks below model separation for offline tests only; they are
    not OS-authenticated identities and cannot unlock ConnectivityHarness.
    """

    def __init__(
        self,
        root: Path,
        *,
        synthetic: bool,
        issuer_role: str,
        runtime_role: str,
        current_role: Callable[[], str],
        write=os.write,
        fsync=os.fsync,
        sync_directory=None,
    ):
        if synthetic is not True:
            raise DurabilityError("Trusted F09 issuer/runtime OS boundary is unavailable")
        if (
            type(issuer_role) is not str
            or type(runtime_role) is not str
            or not STAGING_AUTHORIZATION_ID.fullmatch(issuer_role)
            or not STAGING_AUTHORIZATION_ID.fullmatch(runtime_role)
            or issuer_role == runtime_role
            or not callable(current_role)
        ):
            raise DurabilityError("Synthetic authorization roles are invalid")
        self.root = (
            _check_external_private_root(Path(root), allow_repository=False)
            / STAGING_AUTHORIZATION_STORE_DIRNAME
        )
        self.synthetic = True
        self.issuer_role = issuer_role
        self.runtime_role = runtime_role
        self._current_role = current_role
        self._write = write
        self._fsync = fsync
        self._sync_directory = sync_directory or (
            lambda path: _fsync_directory(path, required=False)
        )
        self.issued_root = self.root / "issued"
        self.consumed_root = self.root / "consumed"
        _ensure_private_directory(self.root, synthetic=True)
        _ensure_private_directory(self.issued_root, synthetic=True)
        _ensure_private_directory(self.consumed_root, synthetic=True)
        self._directory_identities = {
            path: (path.stat().st_dev, path.stat().st_ino)
            for path in (self.root, self.issued_root, self.consumed_root)
        }

    def _check_paths(self) -> None:
        """Detect replaced synthetic state paths; this is not an OS trust boundary."""
        try:
            _check_external_private_root(self.root, allow_repository=False)
            for path, identity in self._directory_identities.items():
                metadata = path.lstat()
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or (metadata.st_dev, metadata.st_ino) != identity
                    or (os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o700)
                ):
                    raise OSError("synthetic store directory changed")
        except (OSError, DurabilityError):
            raise ConnectivityError("staging_authorization_store_invalid", uncertain=True) from None

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ConnectivityError("staging_authorization_claims_invalid")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _require_role(self, expected: str, mismatch_code: str) -> None:
        try:
            observed = self._current_role()
        except BaseException:
            raise ConnectivityError("staging_authorization_identity_unavailable") from None
        if observed != expected:
            raise ConnectivityError(mismatch_code)

    @staticmethod
    def _canonical_bytes(record: dict) -> bytes:
        return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    def _write_new_file(
        self,
        path: Path,
        payload: bytes,
        *,
        exists_code: str = "staging_authorization_record_exists",
    ) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = None
        try:
            self._check_paths()
            descriptor = os.open(path, flags, 0o600)
            offset = 0
            while offset < len(payload):
                written = self._write(descriptor, payload[offset:])
                if type(written) is not int or not 0 < written <= len(payload) - offset:
                    raise OSError("short authorization store write")
                offset += written
            self._fsync(descriptor)
            if self._sync_directory(path.parent) is not True:
                raise OSError("authorization directory fsync is unavailable")
            self._check_paths()
        except FileExistsError:
            raise ConnectivityError(exists_code) from None
        except BaseException:
            raise ConnectivityError(
                "staging_authorization_durability_uncertain", uncertain=True
            ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def issue(
        self,
        claims: object,
        *,
        expected_project_id: str,
        expected_source_commit: str,
        expected_binding: StagingAuthorizationBinding,
        now_utc: datetime,
    ) -> IssuedStagingCapability:
        self._require_role(self.issuer_role, "staging_authorization_issuer_identity_mismatch")
        if type(claims) is not dict or set(claims) != STAGING_AUTHORIZATION_ISSUE_FIELDS:
            raise ConnectivityError("staging_authorization_claims_invalid")
        authorization_id = uuid.uuid4().hex
        full_claims = {
            "schema_version": 2,
            "authorization_id": authorization_id,
            "issuer_id": self.issuer_role,
            **claims,
            "issued_at": self._timestamp(now_utc),
        }
        parse_unverified_staging_authorization_claims(
            full_claims,
            expected_project_id=expected_project_id,
            expected_source_commit=expected_source_commit,
            expected_binding=expected_binding,
            now_utc=now_utc,
        )
        capability = secrets.token_bytes(32)
        record = {
            "record_type": STAGING_AUTHORIZATION_RECORD_TYPE,
            "schema_version": 2,
            "synthetic": True,
            "claims": full_claims,
            "capability_sha256": hashlib.sha256(capability).hexdigest(),
        }
        self._write_new_file(
            self.issued_root / f"{authorization_id}.json", self._canonical_bytes(record)
        )
        return IssuedStagingCapability(authorization_id, capability)

    def _read_issued_record(self, authorization_id: str) -> dict:
        if type(authorization_id) is not str or not STAGING_AUTHORIZATION_ID.fullmatch(
            authorization_id
        ):
            raise ConnectivityError("staging_authorization_claims_invalid")
        path = self.issued_root / f"{authorization_id}.json"
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            self._check_paths()
            if path.is_symlink():
                raise ValueError("linked authorization record")
            descriptor = os.open(path, flags)
            try:
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1
                    or metadata.st_size > MAX_STAGING_AUTHORIZATION_RECORD_BYTES
                ):
                    raise ValueError("invalid authorization record file")
                if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
                    raise ValueError("authorization record permissions are not private")
                raw = os.read(descriptor, MAX_STAGING_AUTHORIZATION_RECORD_BYTES + 1)
                final_metadata = path.lstat()
                if (metadata.st_dev, metadata.st_ino) != (
                    final_metadata.st_dev,
                    final_metadata.st_ino,
                ) or metadata.st_size != len(raw):
                    raise ValueError("authorization record replaced or incomplete")
            finally:
                os.close(descriptor)
            self._check_paths()
            if len(raw) > MAX_STAGING_AUTHORIZATION_RECORD_BYTES:
                raise ValueError("authorization record is oversized")
            record = json.loads(raw)
            if (
                not isinstance(record, dict)
                or set(record)
                != {"record_type", "schema_version", "synthetic", "claims", "capability_sha256"}
                or record["record_type"] != STAGING_AUTHORIZATION_RECORD_TYPE
                or type(record["schema_version"]) is not int
                or record["schema_version"] != 2
                or record["synthetic"] is not True
                or not isinstance(record["capability_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", record["capability_sha256"])
                or record["claims"].get("authorization_id") != authorization_id
                or raw != self._canonical_bytes(record)
            ):
                raise ValueError("authorization record integrity failure")
            return record
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
            raise ConnectivityError(
                "staging_authorization_record_invalid", uncertain=True
            ) from None

    def validate(
        self,
        capability: IssuedStagingCapability,
        *,
        expected_project_id: str,
        expected_source_commit: str,
        expected_binding: StagingAuthorizationBinding,
        now_utc: datetime,
    ) -> Mapping[str, object]:
        """Read-only validation; valid synthetic claims never grant live authority."""
        self._require_role(self.runtime_role, "staging_authorization_runtime_identity_mismatch")
        if (
            type(capability) is not IssuedStagingCapability
            or type(capability._value) is not bytes
            or len(capability._value) != 32
        ):
            raise ConnectivityError("staging_authorization_capability_invalid")
        record = self._read_issued_record(capability.authorization_id)
        parsed = parse_unverified_staging_authorization_claims(
            record["claims"],
            expected_project_id=expected_project_id,
            expected_source_commit=expected_source_commit,
            expected_binding=expected_binding,
            now_utc=now_utc,
        )
        supplied_digest = hashlib.sha256(capability._value).hexdigest()
        if not hmac.compare_digest(record["capability_sha256"], supplied_digest):
            raise ConnectivityError("staging_authorization_capability_invalid")
        return parsed

    def consume(
        self,
        capability: IssuedStagingCapability,
        *,
        expected_project_id: str,
        expected_source_commit: str,
        expected_binding: StagingAuthorizationBinding,
        now_utc: datetime,
        journal: StagingJournal,
    ) -> Mapping[str, object]:
        if type(journal) is not StagingJournal or journal.synthetic is not True:
            raise ConnectivityError("staging_authorization_journal_invalid")
        parsed = self.validate(
            capability,
            expected_project_id=expected_project_id,
            expected_source_commit=expected_source_commit,
            expected_binding=expected_binding,
            now_utc=now_utc,
        )

        authorization_digest = hashlib.sha256(capability.authorization_id.encode()).hexdigest()
        # An exclusive, retained consumption-start record burns the attempt even
        # when the subsequent journal intent or final consumed-marker write fails.
        # This is process-crash evidence only; a same-UID adversary can still
        # rewrite this synthetic store, which is why it cannot authorize live use.
        claim = {
            "record_type": "f09_synthetic_consumption_started_not_r01a",
            "schema_version": 2,
            "synthetic": True,
            "attempt_id": parsed["attempt_id"],
            "authorization_id": capability.authorization_id,
        }
        self._write_new_file(
            self.consumed_root / f"attempt-{_sha256(parsed['attempt_id'])}.claimed",
            self._canonical_bytes(claim),
            exists_code="staging_authorization_replayed",
        )
        intent = journal.append(
            "authorization_consume", "intent", resource_sha256=authorization_digest
        )
        marker = {
            "record_type": STAGING_AUTHORIZATION_CONSUMED_TYPE,
            "schema_version": 2,
            "synthetic": True,
            "authorization_id": capability.authorization_id,
            "capability_sha256": hashlib.sha256(capability._value).hexdigest(),
            "attempt_id": parsed["attempt_id"],
            "configuration_sha256": parsed["configuration_sha256"],
            "credential_scope_sha256": parsed["credential_scope_sha256"],
            "spend_control_limit_cents": parsed["spend_control_limit_cents"],
            "project_id": parsed["project_id"],
            "source_commit": parsed["source_commit"],
            "consumed_at": self._timestamp(now_utc),
        }
        self._write_new_file(
            self.consumed_root / f"{capability.authorization_id}.consumed",
            self._canonical_bytes(marker),
            exists_code="staging_authorization_replayed",
        )
        journal.append(
            "authorization_consume",
            "outcome",
            intent_seq=intent,
            code="consumed",
            resource_sha256=authorization_digest,
        )
        return parsed


class SyntheticStagingAuthorization:
    """Offline rehearsal only; never a trusted issuer or a live-mode permit."""

    def __init__(
        self, store, capability, binding, *, project_id, source_commit, attestation, now_utc
    ):
        if type(store) is not OfflineStagingAuthorizationStore or store.synthetic is not True:
            raise ConnectivityError("staging_authorization_store_invalid")
        if type(binding) is not StagingAuthorizationBinding:
            raise ConnectivityError("staging_authorization_binding_invalid")
        self.store, self.capability, self.binding = store, capability, binding
        self.project_id, self.source_commit = project_id, source_commit
        self.attestation, self.now_utc = attestation, now_utc

    def validate_request(self, harness) -> None:
        if (
            harness.journal.synthetic is not True
            or type(harness.client) is not StagingAgentsClient
            or harness.client.synthetic is not True
            or harness.client.project_id_hash != _sha256(self.project_id)
            or connectivity_configuration_sha256(
                harness.agent_config,
                create_seconds=harness.create_seconds,
                connect_seconds=harness.connect_seconds,
                cleanup_seconds=harness.cleanup_seconds,
            )
            != self.binding.configuration_sha256
            or unverified_credential_scope_sha256(
                self.attestation, expected_project_id=self.project_id
            )
            != self.binding.credential_scope_sha256
        ):
            raise ConnectivityError("staging_authorization_request_mismatch")
        parsed = self.store.validate(
            self.capability,
            expected_project_id=self.project_id,
            expected_source_commit=self.source_commit,
            expected_binding=self.binding,
            now_utc=self.now_utc(),
        )
        approval = harness.client._spend_control_approval
        if (
            _validated_spend_control(approval)["limit"] != self.binding.limit
            or approval.approval_reference != parsed["billing_owner_approval_reference"]
        ):
            raise ConnectivityError("staging_authorization_request_mismatch")

    def consume(self, journal) -> None:
        self.store.consume(
            self.capability,
            expected_project_id=self.project_id,
            expected_source_commit=self.source_commit,
            expected_binding=self.binding,
            now_utc=self.now_utc(),
            journal=journal,
        )


SOLO_APPROVAL_TYPE = "f09_solo_operator_manual_approval_not_r01a"
SOLO_CONFIRMATION = "I ACCEPT BILLING RESPONSIBILITY AND BEST-EFFORT SPEND CONTROL"
SOLO_SOURCE_FILES = (
    "connectivity_harness.py",
    "f09_solo_operator.py",
    "executor_contract.py",
    "docker_runtime.py",
    "egress_proxy.py",
)


def _solo_source_identification(expected_commit: str) -> str:
    """Identify reviewed local files without executing them or contacting Git remotes."""
    repository = Path(__file__).resolve().parents[3]

    def git(*arguments):
        try:
            result = subprocess.run(
                ["git", "--no-pager", "-C", str(repository), *arguments],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode or len(result.stdout) > 2 << 20:
                raise ValueError
            return result.stdout
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ConnectivityError("solo_source_unverified") from None

    if git("rev-parse", "HEAD").decode("ascii").strip() != expected_commit:
        raise ConnectivityError("solo_source_mismatch")
    hashes = {}
    for name in SOLO_SOURCE_FILES:
        path = Path(__file__).with_name(name)
        relative = "benchmarks/codex_r/exploratory/" + name
        try:
            if path.is_symlink() or path.stat().st_size > 2 << 20:
                raise ValueError
            with path.open("rb") as source:
                raw = source.read((2 << 20) + 1)
            if len(raw) > 2 << 20:
                raise ValueError
        except (OSError, ValueError):
            raise ConnectivityError("solo_source_unverified") from None
        if raw.replace(b"\r\n", b"\n") != git("show", expected_commit + ":" + relative):
            raise ConnectivityError("solo_source_mismatch")
        hashes[name] = hashlib.sha256(raw).hexdigest()
    return _sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")))


def _solo_filesystem(path: Path, mountinfo: str) -> str:
    matches = []
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if separator and len(fields) >= 5 and after.split():
            mount = fields[4]
            for escaped, decoded in (("\\040", " "), ("\\011", "\t"), ("\\134", "\\")):
                mount = mount.replace(escaped, decoded)
            if path == Path(mount) or Path(mount) in path.parents:
                matches.append((len(mount), after.split()[0]))
    return max(matches)[1] if matches else "unknown"


def validate_solo_request(request: object) -> dict:
    """Validate non-secret operator configuration; no credential introspection."""
    fields = {
        "schema_version",
        "source_commit",
        "project_id",
        "agent",
        "create_seconds",
        "connect_seconds",
        "cleanup_seconds",
        "executor_image",
        "spend_limit_cents",
        "billing_owner_id",
        "credential_attestation",
    }
    if type(request) is not dict or set(request) != fields:
        raise ConnectivityError("solo_request_invalid")
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != 1
        or type(request["source_commit"]) is not str
        or not SOURCE_COMMIT_SHA.fullmatch(request["source_commit"])
        or type(request["project_id"]) is not str
        or not PROJECT_ID.fullmatch(request["project_id"])
        or type(request["executor_image"]) is not str
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", request["executor_image"])
        or type(request["billing_owner_id"]) is not str
        or not STAGING_AUTHORIZATION_ID.fullmatch(request["billing_owner_id"])
        or contract.sanitize_reference_data(request["billing_owner_id"])
        != request["billing_owner_id"]
    ):
        raise ConnectivityError("solo_request_invalid")
    _validated_spend_control(SpendControlApproval(request["spend_limit_cents"], "manual", True))
    connectivity_configuration_sha256(
        request["agent"],
        create_seconds=request["create_seconds"],
        connect_seconds=request["connect_seconds"],
        cleanup_seconds=request["cleanup_seconds"],
    )
    if contract.sanitize_reference_data(request["agent"], redact_urls=True) != request["agent"]:
        raise ConnectivityError("solo_request_invalid")
    unverified_credential_scope_sha256(
        request["credential_attestation"], expected_project_id=request["project_id"]
    )
    raw = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw.encode()) > MAX_STAGING_AUTHORIZATION_RECORD_BYTES // 2:
        raise ConnectivityError("solo_request_invalid")
    return json.loads(raw)


class SoloOperatorApprovalStore:
    """One approval per persistent directory, trusting the local operator account.

    Protects against accidental reuse, not malicious code running as that user.
    Synthetic records cannot be opened as real operator approvals.
    """

    def __init__(
        self,
        state_directory: Path,
        *,
        synthetic=False,
        source_probe=None,
        now_utc=None,
        terminal_input=None,
        terminal_output=None,
        write=None,
        fsync=None,
        read_only=False,
    ):
        if (
            type(synthetic) is not bool
            or type(read_only) is not bool
            or (
                not synthetic
                and any(
                    value is not None
                    for value in (
                        source_probe,
                        now_utc,
                        terminal_input,
                        terminal_output,
                        write,
                        fsync,
                    )
                )
            )
        ):
            raise ConnectivityError("solo_test_boundary_rejected")
        self.synthetic = synthetic
        self.state_directory = _check_external_private_root(Path(state_directory))
        self.root = self.state_directory / "f09-solo-operator"
        self._source_probe = source_probe or _solo_source_identification
        self._now = now_utc or (lambda: datetime.now(UTC))
        self._input = terminal_input if terminal_input is not None else sys.stdin
        self._output = terminal_output if terminal_output is not None else sys.stderr
        self._write, self._fsync = write or os.write, fsync or os.fsync
        self._check_directory(self.state_directory)
        self.read_only = read_only
        if not read_only:
            try:
                self.root.mkdir(mode=0o700)
                _fsync_directory(self.state_directory, required=True)
            except FileExistsError:
                pass
            except OSError:
                raise ConnectivityError("solo_state_unavailable", uncertain=True) from None
        self._check_directory(self.root)
        self._identity = (self.root.stat().st_dev, self.root.stat().st_ino)

    def _check_directory(self, path):
        try:
            if sys.platform != "linux":
                raise ValueError
            _check_external_private_root(path)
            metadata = path.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise ValueError
            if not self.synthetic:
                with Path("/proc/self/mountinfo").open("rb") as source:
                    raw = source.read((1 << 20) + 1)
                if len(raw) > 1 << 20 or _solo_filesystem(path, raw.decode()) not in {
                    "ext4",
                    "xfs",
                    "btrfs",
                }:
                    raise ValueError
        except (OSError, ValueError, DurabilityError):
            raise ConnectivityError("solo_private_persistent_linux_state_required") from None

    def _check_state(self):
        self._check_directory(self.state_directory)
        self._check_directory(self.root)
        if (self.root.stat().st_dev, self.root.stat().st_ino) != self._identity:
            raise ConnectivityError("solo_state_replaced", uncertain=True)

    @staticmethod
    def _bytes(record):
        return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()

    def _write_new(self, name, record):
        if self.read_only:
            raise ConnectivityError("solo_read_only_store")
        self._check_state()
        raw = self._bytes(record)
        descriptor = None
        try:
            descriptor = os.open(
                self.root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            if self._write(descriptor, raw) != len(raw):
                raise OSError
            self._fsync(descriptor)
            _fsync_directory(self.root, required=True)
            self._check_state()
        except FileExistsError:
            raise ConnectivityError("solo_approval_already_used_or_pending") from None
        except (OSError, DurabilityError):
            raise ConnectivityError("solo_durability_uncertain", uncertain=True) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _read(self, name):
        self._check_state()
        descriptor = None
        try:
            descriptor = os.open(self.root / name, os.O_RDONLY | os.O_NOFOLLOW)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
                or metadata.st_size > MAX_STAGING_AUTHORIZATION_RECORD_BYTES
            ):
                raise ValueError
            raw = os.read(descriptor, MAX_STAGING_AUTHORIZATION_RECORD_BYTES + 1)
            after = (self.root / name).lstat()
            record = json.loads(raw)
            if (
                type(record) is not dict
                or raw != self._bytes(record)
                or len(raw) != metadata.st_size
                or (metadata.st_dev, metadata.st_ino) != (after.st_dev, after.st_ino)
            ):
                raise ValueError
            self._check_state()
            return record
        except (OSError, ValueError, TypeError):
            raise ConnectivityError("solo_record_invalid", uncertain=True) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _binding(record):
        request = record["request"]
        return StagingAuthorizationBinding(
            record["claims"]["attempt_id"],
            _sha256(
                json.dumps(
                    {"request": request, "source": record["source_files_sha256"]},
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            unverified_credential_scope_sha256(
                request["credential_attestation"], expected_project_id=request["project_id"]
            ),
            request["spend_limit_cents"],
        )

    def approve(self, request, *, expires_in_seconds):
        if self.read_only:
            raise ConnectivityError("solo_read_only_store")
        request = validate_solo_request(request)
        if (
            type(expires_in_seconds) is not int
            or not 0 < expires_in_seconds <= MAX_STAGING_AUTHORIZATION_SECONDS
        ):
            raise ConnectivityError("solo_expiration_invalid")
        if not self._input.isatty() or not self._output.isatty():
            raise ConnectivityError("solo_interactive_terminal_required")
        source_hash = self._source_probe(request["source_commit"])
        if type(source_hash) is not str or not SHA256.fullmatch(source_hash):
            raise ConnectivityError("solo_source_unverified")
        with _lease_operation_gate(self.root, synthetic=False):
            if any(path.name != "lease.gate" for path in self.root.iterdir()):
                raise ConnectivityError("solo_approval_already_used_or_pending")
            if (self.state_directory / JOURNAL_DIRNAME).exists():
                raise ConnectivityError("solo_prior_lifecycle_requires_reconciliation")
            issued = self._now()
            expiration = issued + timedelta(seconds=expires_in_seconds)
            attempt = "F09-" + uuid.uuid4().hex
            authorization_id = uuid.uuid4().hex
            claims = {
                "schema_version": 2,
                "authorization_id": authorization_id,
                "issuer_id": request["credential_attestation"]["operator_id"],
                "project_name": "rkmcp-staging",
                "project_id": request["project_id"],
                "source_commit": request["source_commit"],
                "attempt_id": attempt,
                "issued_at": OfflineStagingAuthorizationStore._timestamp(issued),
                "expires_at": OfflineStagingAuthorizationStore._timestamp(expiration),
                "session_count": 1,
                "task_count": 0,
                "task_submission_allowed": False,
                "responses_inference_allowed": False,
                "spend_control_limit_cents": request["spend_limit_cents"],
                "billing_owner_id": request["billing_owner_id"],
                "billing_owner_approval_reference": "manual:" + authorization_id,
                "billing_owner_acknowledged": True,
                "billing_risk_acknowledged": True,
            }
            record = {
                "schema_version": 1,
                "record_type": SOLO_APPROVAL_TYPE,
                "synthetic": self.synthetic,
                "request": request,
                "claims": claims,
                "source_files_sha256": source_hash,
                "confirmation_scheme": "interactive_exact_phrase_v1",
            }
            binding = self._binding(record)
            claims["configuration_sha256"] = binding.configuration_sha256
            claims["credential_scope_sha256"] = binding.credential_scope_sha256
            summary = {
                "attempt_id": attempt,
                "project_id": request["project_id"],
                "source_commit": request["source_commit"],
                "configuration_sha256": binding.configuration_sha256,
                "limit_usd_cents": binding.limit,
                "expires_at": claims["expires_at"],
                "scope": "one session, zero tasks, no Responses or inference",
            }
            print(json.dumps(summary, sort_keys=True, indent=2), file=self._output)
            print(
                "Same-user approval trusts this account; "
                "spend control is best-effort, not a billing ceiling.",
                file=self._output,
            )
            phrase = f"APPROVE {attempt} {binding.limit} CENTS ONE SESSION ZERO TASKS"
            try:
                for expected in (phrase, SOLO_CONFIRMATION):
                    print("Type exactly: " + expected, file=self._output, flush=True)
                    if self._input.readline().rstrip("\r\n") != expected:
                        raise ConnectivityError("solo_confirmation_rejected")
            except (EOFError, KeyboardInterrupt):
                raise ConnectivityError("solo_confirmation_rejected") from None
            parse_unverified_staging_authorization_claims(
                claims,
                expected_project_id=request["project_id"],
                expected_source_commit=request["source_commit"],
                expected_binding=binding,
                now_utc=self._now(),
            )
            if self._source_probe(request["source_commit"]) != source_hash:
                raise ConnectivityError("solo_source_mismatch")
            self._write_new("approval.json", record)
            return summary

    def validate(self):
        record = self._read("approval.json")
        if (
            set(record)
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
            or record["record_type"] != SOLO_APPROVAL_TYPE
            or type(record["synthetic"]) is not bool
            or record["synthetic"] is not self.synthetic
            or record["confirmation_scheme"] != "interactive_exact_phrase_v1"
            or type(record["claims"]) is not dict
            or set(record["claims"]) != STAGING_AUTHORIZATION_FIELDS
            or type(record["source_files_sha256"]) is not str
            or not SHA256.fullmatch(record["source_files_sha256"])
        ):
            raise ConnectivityError("solo_record_invalid")
        request = validate_solo_request(record["request"])
        if self._source_probe(request["source_commit"]) != record["source_files_sha256"]:
            raise ConnectivityError("solo_source_mismatch")
        binding = self._binding(record)
        parse_unverified_staging_authorization_claims(
            record["claims"],
            expected_project_id=request["project_id"],
            expected_source_commit=request["source_commit"],
            expected_binding=binding,
            now_utc=self._now(),
        )
        return record

    def spend_approval(self):
        record = self.validate()
        return SpendControlApproval(
            record["request"]["spend_limit_cents"],
            record["claims"]["billing_owner_approval_reference"],
            True,
        )

    def consume(self, journal, lease):
        if self.read_only:
            raise ConnectivityError("solo_read_only_store")
        if (
            type(journal) is not StagingJournal
            or type(lease) is not StagingLease
            or journal.synthetic is not self.synthetic
            or lease.synthetic is not self.synthetic
            or journal.root.parent != lease.root
            or lease.root != self.state_directory / JOURNAL_DIRNAME
            or not lease.acquired
            or not lease.lock_path.exists()
        ):
            raise ConnectivityError("solo_lease_scope_invalid")
        with _lease_operation_gate(self.root, synthetic=False):
            record = self.validate()
            reference = _sha256(record["claims"]["authorization_id"])
            evidence = {
                "record_type": "f09_solo_operator_consumption",
                "schema_version": 1,
                "synthetic": self.synthetic,
                "approval_sha256": _sha256(self._bytes(record).decode()),
            }
            self._write_new("consumption.started", evidence)
            intent = journal.append("authorization_consume", "intent", resource_sha256=reference)
            self._write_new("consumed.json", evidence)
            journal.append(
                "authorization_consume",
                "outcome",
                intent_seq=intent,
                resource_sha256=reference,
                code="consumed",
            )

    def inspect(self):
        """Read-only state summary, never an execution or recovery authorization."""
        self._check_state()
        entries = list(islice(self.root.iterdir(), 17))
        names = {path.name for path in entries}
        state = "empty"
        known = {"lease.gate", "approval.json", "consumption.started", "consumed.json"}
        if len(entries) > 16 or names - known:
            state = "corrupt"
        elif "consumption.started" in names or "consumed.json" in names:
            state = "consumed_or_uncertain"
        elif "approval.json" in names:
            state = "pending_review"
        try:
            records = {name: self._read(name) for name in names & (known - {"lease.gate"})}
            if "approval.json" in records and (
                records["approval.json"].get("record_type") != SOLO_APPROVAL_TYPE
                or records["approval.json"].get("synthetic") is not self.synthetic
            ):
                state = "corrupt"
            if "consumed.json" in records and (
                "consumption.started" not in records
                or records["consumed.json"] != records["consumption.started"]
            ):
                state = "corrupt"
        except ConnectivityError:
            state = "corrupt"
        return {
            "state": state,
            "synthetic": self.synthetic,
            "live_allowed": False,
            "cleanup_verified": False,
            "recovery_authorized": False,
        }


class SoloOperatorAuthorization:
    """Manual approval binding for the existing lifecycle; live gate remains closed."""

    def __init__(self, store, lease):
        if type(store) is not SoloOperatorApprovalStore or type(lease) is not StagingLease:
            raise ConnectivityError("solo_lease_scope_invalid")
        self.store, self.lease = store, lease

    def validate_request(self, harness):
        if type(harness.client) is not StagingAgentsClient:
            raise ConnectivityError("solo_request_mismatch")
        record = self.store.validate()
        request = record["request"]
        actual = connectivity_configuration_sha256(
            harness.agent_config,
            create_seconds=harness.create_seconds,
            connect_seconds=harness.connect_seconds,
            cleanup_seconds=harness.cleanup_seconds,
        )
        expected = connectivity_configuration_sha256(
            request["agent"],
            create_seconds=request["create_seconds"],
            connect_seconds=request["connect_seconds"],
            cleanup_seconds=request["cleanup_seconds"],
        )
        approval = harness.client._spend_control_approval
        if (
            type(harness.client) is not StagingAgentsClient
            or harness.client.synthetic is not self.store.synthetic
            or harness.journal.synthetic is not self.store.synthetic
            or harness.lease is not self.lease
            or actual != expected
            or harness.client.project_id_hash != _sha256(request["project_id"])
            or _validated_spend_control(approval)["limit"] != request["spend_limit_cents"]
            or approval.approval_reference != record["claims"]["billing_owner_approval_reference"]
        ):
            raise ConnectivityError("solo_request_mismatch")
        if type(harness.executor) is DockerExecutorAdapter and (
            harness.executor.runtime.image_id != request["executor_image"]
        ):
            raise ConnectivityError("solo_executor_image_mismatch")

    def consume(self, journal):
        self.store.consume(journal, self.lease)


class StagingAgentsClient:
    """Fixed-route HTTPS client with no task, inference, or arbitrary URL method."""

    def __init__(
        self,
        application_api_key: str,
        *,
        project_id: str,
        spend_control_approval: SpendControlApproval | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
        synthetic: bool = False,
    ):
        if not isinstance(application_api_key, str) or not application_api_key.strip():
            raise ValueError("A staging application key is required")
        if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
            raise ValueError("A staging project ID is required")
        if not 0 < timeout <= MAX_CREATE_SECONDS:
            raise ValueError("Connectivity HTTP timeout exceeds the reviewed cap")
        if type(synthetic) is not bool:
            raise ValueError("Synthetic mode must be explicit")
        if not synthetic and transport is not None:
            raise ValueError("Live connectivity forbids injected transports")
        if synthetic and not isinstance(transport, httpx.MockTransport):
            raise ValueError("Synthetic connectivity clients require httpx.MockTransport")
        if not synthetic:
            raise ValueError("Live F09 execution is disabled pending solo-operator review")
        self.synthetic = synthetic
        self._key = application_api_key
        self._spend_control_approval = spend_control_approval
        self.project_id_hash = _sha256(project_id)
        self._client = httpx.Client(
            base_url=API_ORIGIN,
            headers={
                "Authorization": f"Bearer {application_api_key}",
                "OpenAI-Beta": "agents=v1",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            verify=True,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def _json(self, method: str, path: str, *, body: dict | None = None, timeout=None) -> dict:
        allowed = (
            (method == "POST" and path == "/v1/agents/sessions")
            or (
                method == "GET"
                and re.fullmatch(r"/v1/agents/sessions/[A-Za-z0-9_-]{1,128}/events", path)
            )
            or (
                method == "DELETE"
                and re.fullmatch(r"/v1/agents/sessions/[A-Za-z0-9_-]{1,128}", path)
            )
        )
        if not allowed:
            raise ConnectivityError("route_rejected")
        if method == "POST":
            if not isinstance(body, dict) or set(body) != {
                "agent",
                "environment",
                "spend_control",
            }:
                raise ConnectivityError("create_body_rejected")
            try:
                self._validate_agent_config(body["agent"])
            except ValueError:
                raise ConnectivityError("create_body_rejected") from None
            environment = body["environment"]
            if (
                not isinstance(environment, dict)
                or set(environment) != {"type", "workspace_directory"}
                or environment.get("type") != "self_hosted"
                or environment.get("workspace_directory") != "/workspace"
            ):
                raise ConnectivityError("create_body_rejected")
            spend_control = body["spend_control"]
            if (
                not isinstance(spend_control, dict)
                or set(spend_control) != {"limit"}
                or type(spend_control.get("limit")) is not int
                or spend_control["limit"] <= 0
            ):
                raise ConnectivityError("create_body_rejected")
        try:
            request_options = {"json": body}
            if timeout is not None:
                request_options["timeout"] = timeout
            with self._client.stream(method, path, **request_options) as response:
                if response.is_redirect:
                    raise ConnectivityError("redirect_rejected", uncertain=method == "POST")
                if not response.is_success:
                    raise ConnectivityError(
                        "http_rejected",
                        uncertain=method == "POST"
                        and (response.status_code >= 500 or response.status_code in {408, 429}),
                    )
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ConnectivityError("response_limit")
                    data.extend(chunk)
        except ConnectivityError:
            raise
        except httpx.HTTPError:
            raise ConnectivityError("https_transport_failed", uncertain=method == "POST") from None
        try:
            value = json.loads(data)
        except (ValueError, json.JSONDecodeError):
            raise ConnectivityError("invalid_json", uncertain=method == "POST") from None
        if not isinstance(value, dict):
            raise ConnectivityError("invalid_response_shape", uncertain=method == "POST")
        return value

    @staticmethod
    def _validate_agent_config(agent: dict) -> dict:
        if not isinstance(agent, dict) or set(agent) - {"model", "reasoning", "tools"}:
            raise ValueError("Staging agent config contains an unreviewed field")
        if not isinstance(agent.get("model"), str) or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,128}", agent["model"]
        ):
            raise ValueError("A reviewed staging model is required")
        if agent.get("tools", []) != []:
            raise ValueError("Connectivity-only sessions cannot enable tools")
        reasoning = agent.get("reasoning")
        if reasoning is not None and (
            not isinstance(reasoning, dict)
            or set(reasoning) != {"effort"}
            or reasoning["effort"] not in {"low", "medium", "high"}
        ):
            raise ValueError("Staging reasoning configuration is unreviewed")
        return {**agent, "tools": []}

    def create_session(
        self, agent_config: dict, *, workspace_directory="/workspace", timeout: float | None = None
    ) -> dict:
        spend_control = _validated_spend_control(self._spend_control_approval)
        agent = self._validate_agent_config(agent_config)
        if workspace_directory != "/workspace":
            raise ValueError("Staging workspace path is invalid")
        # This exact schema has no input, events, task, stream, or arbitrary URL field.
        body = {
            "agent": agent,
            "environment": {
                "type": "self_hosted",
                "workspace_directory": workspace_directory,
            },
            "spend_control": spend_control,
        }
        if timeout is not None and not 0 < timeout <= MAX_CREATE_SECONDS:
            raise ValueError("Session creation timeout exceeds the reviewed cap")
        record = self._json("POST", "/v1/agents/sessions", body=body, timeout=timeout)
        session_id = record.get("id")
        environment = record.get("environment")
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise ConnectivityError("session_id_invalid", uncertain=True)
        if not isinstance(environment, dict) or environment.get("type") != "self_hosted":
            raise ConnectivityError("environment_invalid", uncertain=True)
        environment_id = environment.get("id")
        remote_url = environment.get("remote_url")
        if not isinstance(environment_id, str) or not SESSION_ID.fullmatch(environment_id):
            raise ConnectivityError("environment_id_invalid", uncertain=True)
        try:
            contract.validate_executor_remote_url(remote_url)
        except contract.ExecutorURLValidationError:
            raise ConnectivityError("remote_url_rejected", uncertain=True) from None
        return {
            "session_id": session_id,
            "environment_id": environment_id,
            "remote_url": remote_url,
        }

    def open_event_stream(self, session_id: str, *, timeout: float):
        if not SESSION_ID.fullmatch(session_id) or not 0 < timeout <= MAX_CONNECT_SECONDS:
            raise ConnectivityError("stream_parameters_invalid")
        path = f"/v1/agents/sessions/{session_id}/events"
        try:
            request = self._client.build_request(
                "GET",
                path,
                headers={"Accept": "text/event-stream"},
                timeout=httpx.Timeout(
                    connect=min(15.0, timeout), read=timeout, write=15.0, pool=15.0
                ),
            )
            response = self._client.send(request, stream=True)
            if response.is_redirect:
                response.close()
                raise ConnectivityError("redirect_rejected")
            if not response.is_success:
                response.close()
                raise ConnectivityError("stream_http_rejected")
            if "text/event-stream" not in response.headers.get("content-type", "").lower():
                response.close()
                raise ConnectivityError("stream_content_type_invalid")
            return response
        except ConnectivityError:
            raise
        except httpx.HTTPError:
            raise ConnectivityError("stream_transport_failed") from None

    @staticmethod
    def _bounded_lines(chunks):
        buffer = bytearray()
        total = 0
        event_bytes = 0
        for chunk in chunks:
            total += len(chunk)
            if total > MAX_SSE_TOTAL_BYTES:
                raise ConnectivityError("stream_total_limit")
            for byte in chunk:
                event_bytes += 1
                if len(buffer) >= MAX_SSE_LINE_BYTES:
                    raise ConnectivityError("stream_line_limit")
                if event_bytes > MAX_SSE_EVENT_BYTES:
                    raise ConnectivityError("stream_event_limit")
                if byte == 10:
                    if not buffer or buffer == b"\r":
                        event_bytes = 0
                    try:
                        yield bytes(buffer).rstrip(b"\r").decode("utf-8", errors="strict")
                    except UnicodeError:
                        raise ConnectivityError("stream_encoding_invalid") from None
                    buffer.clear()
                else:
                    buffer.append(byte)
        if buffer:
            raise ConnectivityError("stream_truncated")

    def iter_events(self, response):
        yield from self._decode_events(self._bounded_lines(response.iter_bytes(chunk_size=4096)))

    @staticmethod
    def close_event_stream(response) -> None:
        response.close()

    @staticmethod
    def _decode_events(lines):
        pending: list[str] = []
        pending_size = 0
        total_size = 0
        count = 0
        for line in lines:
            if not isinstance(line, str):
                raise ConnectivityError("stream_line_invalid")
            total_size += len(line.encode("utf-8"))
            if total_size > MAX_SSE_TOTAL_BYTES:
                raise ConnectivityError("stream_total_limit")
            if line.startswith("data:"):
                value = line[5:].lstrip()
                pending_size += len(value.encode("utf-8"))
                if pending_size > MAX_SSE_EVENT_BYTES:
                    raise ConnectivityError("stream_event_limit")
                pending.append(value)
            elif not line and pending:
                raw = "\n".join(pending)
                pending, pending_size = [], 0
                if raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    raise ConnectivityError("event_json_invalid") from None
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    raise ConnectivityError("event_shape_invalid")
                count += 1
                if count > MAX_EVENTS:
                    raise ConnectivityError("event_count_limit")
                # Return a minimal projection; raw event fields never enter the harness.
                event_type = event["type"]
                data = event.get("data", {})
                environment_id = event.get("environment_id")
                session_id = event.get("session_id")
                if isinstance(data, dict):
                    environment_id = environment_id or data.get("environment_id")
                    session_id = session_id or data.get("session_id")
                for payload in (event, data):
                    environment = payload.get("environment") if isinstance(payload, dict) else None
                    if isinstance(environment, dict):
                        environment_id = environment_id or environment.get("id")
                yield {
                    "type": event_type,
                    "environment_id": environment_id,
                    "session_id": session_id,
                }
        if pending:
            raise ConnectivityError("stream_truncated")

    def delete_session(self, session_id: str, *, timeout: float | None = None) -> bool:
        if not SESSION_ID.fullmatch(session_id):
            raise ConnectivityError("session_id_invalid")
        if timeout is not None and not 0 < timeout <= MAX_CLEANUP_SECONDS:
            raise ConnectivityError("cleanup_timeout_invalid")
        result = self._json("DELETE", f"/v1/agents/sessions/{session_id}", timeout=timeout)
        if result.get("id") != session_id or result.get("deleted") is not True:
            raise ConnectivityError("session_delete_unconfirmed")
        return True

    def close(self) -> None:
        self._client.close()


class Executor(Protocol):
    def start(self, session: dict, *, environment_key: str, timeout: float) -> str: ...

    def stop_verified(self, container_id: str | None, *, timeout: float) -> bool: ...


class ConnectivityHarness:
    """Runs only the zero-task state machine against injected boundaries."""

    def __init__(
        self,
        *,
        client: StagingAgentsClient,
        executor: Executor,
        journal: StagingJournal,
        lease: StagingLease,
        agent_config: dict,
        environment_key: str,
        clock=time.monotonic,
        create_seconds=MAX_CREATE_SECONDS,
        connect_seconds=MAX_CONNECT_SECONDS,
        cleanup_seconds=MAX_CLEANUP_SECONDS,
        wall_clock=lambda: datetime.now(UTC).isoformat(),
        synthetic_authorization: SyntheticStagingAuthorization | None = None,
        operator_authorization: SoloOperatorAuthorization | None = None,
    ):
        if not isinstance(environment_key, str) or not environment_key:
            raise ValueError("A restricted staging environment key is required")
        if not 0 < create_seconds <= MAX_CREATE_SECONDS:
            raise ValueError("Session creation deadline exceeds the reviewed cap")
        if not 0 < connect_seconds <= MAX_CONNECT_SECONDS:
            raise ValueError("Connection deadline exceeds the reviewed cap")
        if not 0 < cleanup_seconds <= MAX_CLEANUP_SECONDS:
            raise ValueError("Cleanup deadline exceeds the reviewed cap")
        self.client, self.executor = client, executor
        self.journal, self.lease = journal, lease
        if (
            not hasattr(client, "synthetic")
            or client.synthetic is not journal.synthetic
            or journal.synthetic is not lease.synthetic
            or journal.root.parent != lease.root
        ):
            raise ValueError("Staging client, evidence and lease scopes do not match")
        if journal.synthetic:
            if client.synthetic is not True:
                raise ValueError("Synthetic evidence requires a synthetic client")
        elif (
            type(client) is not StagingAgentsClient
            or client.synthetic is not False
            or getattr(client, "_live_capability", None) is not _LIVE_CLIENT_CAPABILITY
        ):
            raise ValueError("Live connectivity requires the concrete reviewed client")
        if not journal.synthetic and type(executor) is not DockerExecutorAdapter:
            raise ValueError("Live connectivity requires the reviewed Docker adapter")
        if not journal.synthetic:
            raise ValueError("Live F09 execution is disabled pending solo-operator review")
        if synthetic_authorization is not None and type(synthetic_authorization) is not (
            SyntheticStagingAuthorization
        ):
            raise ValueError("Only an explicit synthetic authorization rehearsal is supported")
        self.synthetic_authorization = synthetic_authorization
        if operator_authorization is not None and (
            type(operator_authorization) is not SoloOperatorAuthorization
            or synthetic_authorization is not None
        ):
            raise ValueError("Supply exactly one concrete F09 approval workflow")
        self.operator_authorization = operator_authorization
        self._approval = operator_authorization or synthetic_authorization
        self.agent_config = StagingAgentsClient._validate_agent_config(agent_config)
        self._environment_key = environment_key
        self.clock, self.wall_clock = clock, wall_clock
        self.create_seconds, self.connect_seconds = create_seconds, connect_seconds
        self.cleanup_seconds = cleanup_seconds
        self.state = "preflight"
        self._audit = {
            "schema_version": 2,
            "record_type": "managed_agents_connectivity_audit_not_benchmark_result",
            "synthetic": journal.synthetic,
            "state": self.state,
            "started_at": self.wall_clock(),
            "finished_at": None,
            "session_id_sha256": None,
            "environment_id_sha256": None,
            # Avoid a sensitive-key marker in this descriptive boolean name;
            # the shared sanitizer correctly redacts values under remote-URL keys.
            "remote_endpoint_omitted": True,
            "connected_observed": False,
            "executor_termination_verified": False,
            "executor_start_attempted": False,
            "session_deletion_verified": False,
            "session_creation_outcome": "not_attempted",
            "session_deletion_not_required": False,
            "cleanup_verified": False,
            "task_submission_count": 0,
            "responses_calls": 0,
            # Preserve this categorical boolean through the shared sanitizer;
            # credential-shaped field names deliberately redact their values.
            "approval_consumption_durable": False,
            "failure_code": None,
            "transitions": [],
        }

    def _transition(self, state: str) -> None:
        if state not in ALLOWED_STATES or state not in STATE_TRANSITIONS.get(self.state, set()):
            raise ConnectivityError("state_invalid", state=self.state)
        self.state = state
        self._audit["state"] = state
        self._audit["transitions"].append({"state": state, "at": self.wall_clock()})

    def _intent(self, operation: str, *, resource_sha256=None) -> int:
        return self.journal.append(operation, "intent", resource_sha256=resource_sha256)

    def _outcome(self, operation: str, seq: int, code="ok", *, resource_sha256=None) -> None:
        self.journal.append(
            operation,
            "outcome",
            intent_seq=seq,
            code=code,
            resource_sha256=resource_sha256,
        )

    def _cleanup_effect(self, operation: str, callback, *, resource_sha256=None) -> bool:
        """Attempt cleanup even if intent journaling fails; certify only durable pairs."""
        intent = None
        try:
            intent = self._intent(operation, resource_sha256=resource_sha256)
        except DurabilityError:
            pass
        try:
            result = bool(
                _bounded_call(
                    callback,
                    deadline=min(
                        self._cleanup_deadline,
                        self.clock() + max(0, self._cleanup_real_deadline - time.monotonic()),
                    ),
                    clock=self.clock,
                )
            )
        except Exception:
            result = False
        if intent is None:
            return False
        try:
            self._outcome(
                operation,
                intent,
                "ok" if result else "cleanup_unverified",
                resource_sha256=resource_sha256,
            )
        except DurabilityError:
            return False
        return result

    def _persist_audit(self) -> None:
        safe = contract.sanitize_reference_data(
            self._audit,
            secrets=(self._environment_key, self.client._key),
            redact_urls=True,
        )
        path = self.journal.root / "connectivity-audit.json"
        seq = self._intent("audit_persist")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                raw = (json.dumps(safe, sort_keys=True, indent=2) + "\n").encode("utf-8")
                if output.write(raw) != len(raw):
                    raise DurabilityError("Short connectivity audit write")
                output.flush()
                os.fsync(output.fileno())
            _fsync_directory(self.journal.root, required=not self.journal.synthetic)
        except BaseException:
            raise DurabilityError("Final connectivity audit was not durable") from None
        self._outcome("audit_persist", seq)

    def run(self) -> dict:
        session = None
        container_id = None
        session_known = False
        clean = False
        primary_code = None
        cleanup_ready = threading.Event()
        late_lock = threading.Lock()
        late_state = {
            "create_identity_verified": False,
            "create_delete_verified": False,
            "executor_stop_verified": False,
            "detached": False,
        }
        late_create_settled = None
        late_executor_settled = None

        def _remaining_cleanup():
            if not cleanup_ready.is_set():
                return 0.0
            return max(
                0.0,
                min(
                    self._cleanup_deadline - self.clock(),
                    self._cleanup_real_deadline - time.monotonic(),
                ),
            )

        def _stop_under_cleanup_deadline(container_identity):
            remaining = _remaining_cleanup()
            if remaining <= 0:
                return False
            if type(self.executor) is DockerExecutorAdapter:
                return self.executor.stop_verified(
                    container_identity,
                    timeout=remaining,
                    deadline=self._cleanup_real_deadline,
                )
            return self.executor.stop_verified(container_identity, timeout=remaining)

        def _late_created_session(record):
            cleanup_ready.wait()
            valid = (
                isinstance(record, dict)
                and set(record) == {"session_id", "environment_id", "remote_url"}
                and isinstance(record.get("session_id"), str)
                and SESSION_ID.fullmatch(record["session_id"])
                and isinstance(record.get("environment_id"), str)
                and SESSION_ID.fullmatch(record["environment_id"])
            )
            if valid:
                try:
                    contract.validate_executor_remote_url(record["remote_url"])
                except (contract.ExecutorURLValidationError, TypeError):
                    valid = False
            resource_hash = _sha256(record["session_id"]) if valid else None
            try:
                intent_seq = self._intent("session_delete", resource_sha256=resource_hash)
                if not valid:
                    self._outcome("session_delete", intent_seq, "late_identity_invalid")
                    return
                with late_lock:
                    late_state["create_identity_verified"] = True
                    late_state["session_id_sha256"] = resource_hash
                    late_state["environment_id_sha256"] = _sha256(record["environment_id"])
                remaining = _remaining_cleanup()
                if remaining <= 0:
                    self._outcome(
                        "session_delete",
                        intent_seq,
                        "cleanup_deadline_expired",
                        resource_sha256=resource_hash,
                    )
                    return
                result = _bounded_call(
                    lambda: self.client.delete_session(
                        record["session_id"], timeout=_remaining_cleanup()
                    ),
                    deadline=min(
                        self._cleanup_deadline,
                        self.clock() + remaining,
                    ),
                    clock=self.clock,
                )
                verified = result is True
                self._outcome(
                    "session_delete",
                    intent_seq,
                    "ok" if verified else "cleanup_unverified",
                    resource_sha256=resource_hash,
                )
                with late_lock:
                    late_state["create_delete_verified"] = verified
            except BaseException:
                # A missing durable outcome leaves the existing lease as the recovery gate.
                return

        def _late_executor_stop(late_id):
            cleanup_ready.wait()
            remaining = _remaining_cleanup()
            identity = late_id
            if identity is None and type(self.executor) is DockerExecutorAdapter:
                identity = self.executor._pending_container_id
            resource_hash = _sha256(identity) if isinstance(identity, str) and identity else None
            try:
                intent_seq = self._intent("executor_stop", resource_sha256=resource_hash)
            except DurabilityError:
                return
            stopped = False
            if remaining > 0 and (
                resource_hash is not None or type(self.executor) is DockerExecutorAdapter
            ):
                try:
                    stopped = (
                        _bounded_call(
                            lambda: _stop_under_cleanup_deadline(late_id),
                            deadline=min(self._cleanup_deadline, self.clock() + remaining),
                            clock=self.clock,
                        )
                        is True
                    )
                except Exception:
                    stopped = False
            try:
                self._outcome(
                    "executor_stop",
                    intent_seq,
                    "ok"
                    if stopped
                    else "cleanup_deadline_expired"
                    if remaining <= 0
                    else "cleanup_unverified",
                    resource_sha256=resource_hash,
                )
            except DurabilityError:
                stopped = False
            with late_lock:
                late_state["executor_stop_verified"] = stopped

        try:
            if self._approval is not None:
                self._approval.validate_request(self)
            self.lease.acquire()
            if self._approval is not None:
                self._approval.consume(self.journal)
                self._audit["approval_consumption_durable"] = True
                self._approval.validate_request(self)
        except BaseException:
            if self.lease.acquired:
                self._audit["failure_code"] = "staging_authorization_failed"
                try:
                    self._persist_audit()
                except BaseException:
                    pass  # Retain the lease and all available evidence; never certify cleanup.
            self.journal.close()
            self.client.close()
            raise

        def _create_session():
            if self._approval is not None:
                # Recheck expiration and exact request scope inside the bounded
                # worker, immediately before the sole session-create boundary.
                self._approval.validate_request(self)
            return self.client.create_session(self.agent_config, timeout=remaining)

        create_deadline = self.clock() + self.create_seconds
        try:
            self._transition("create_intent")
            intent = self._intent("session_create")
            try:
                remaining = create_deadline - self.clock()
                if remaining <= 0:
                    raise TimeoutError
                session = _bounded_call(
                    _create_session,
                    deadline=create_deadline,
                    clock=self.clock,
                    late_cleanup=_late_created_session,
                )
            except Exception as exc:
                if isinstance(exc, BoundedCallTimeout):
                    late_create_settled = exc.settled
                unknown = not isinstance(exc, ConnectivityError) or exc.uncertain
                self._audit["session_creation_outcome"] = "unknown" if unknown else "not_created"
                self._audit["failure_code"] = (
                    "session_create_uncertain" if unknown else getattr(exc, "code", "http_rejected")
                )
                self._audit["session_deletion_not_required"] = not unknown
                self._transition("session_unknown" if unknown else "failed")
                try:
                    self._outcome(
                        "session_create",
                        intent,
                        "outcome_unknown" if unknown else getattr(exc, "code", "http_rejected"),
                    )
                except DurabilityError:
                    pass
                if unknown:
                    raise SessionUnknown("session_create_uncertain", state=self.state) from None
                raise ConnectivityError("session_create_rejected", state=self.state) from None
            session_known = True
            self._audit["session_creation_outcome"] = "created"
            self._audit["session_id_sha256"] = _sha256(session["session_id"])
            self._audit["environment_id_sha256"] = _sha256(session["environment_id"])
            self._outcome("session_create", intent)
            self._transition("session_created")

            stream_intent = self._intent("stream_open")
            connect_deadline = self.clock() + self.connect_seconds
            connect_real_deadline = time.monotonic() + self.connect_seconds
            stream_response = None
            try:
                remaining = connect_deadline - self.clock()
                stream_response = _bounded_call(
                    lambda: self.client.open_event_stream(
                        session["session_id"], timeout=max(0.001, remaining)
                    ),
                    deadline=connect_deadline,
                    clock=self.clock,
                    real_deadline=connect_real_deadline,
                    late_cleanup=lambda response: response.close(),
                )
                self._outcome("stream_open", stream_intent)
                self._transition("stream_open")
                start_intent = self._intent("executor_start")
                self._transition("executor_start_intent")
                remaining = connect_deadline - self.clock()
                if remaining <= 0:
                    raise TimeoutError
                self._audit["executor_start_attempted"] = True
                try:
                    container_id = _bounded_call(
                        lambda: self.executor.start(
                            session,
                            environment_key=self._environment_key,
                            timeout=remaining,
                        ),
                        deadline=connect_deadline,
                        clock=self.clock,
                        real_deadline=connect_real_deadline,
                        late_cleanup=_late_executor_stop,
                        late_cleanup_on_error=(
                            (lambda: _late_executor_stop(None))
                            if type(self.executor) is DockerExecutorAdapter
                            else None
                        ),
                    )
                except Exception as exc:
                    if isinstance(exc, BoundedCallTimeout):
                        late_executor_settled = exc.settled
                    try:
                        self._outcome("executor_start", start_intent, "outcome_unknown")
                    except DurabilityError:
                        pass
                    raise
                if not isinstance(container_id, str) or not container_id:
                    try:
                        self._outcome("executor_start", start_intent, "outcome_unknown")
                    except DurabilityError:
                        pass
                    raise ConnectivityError("executor_identity_invalid")
                self._outcome("executor_start", start_intent)
                self._transition("executor_running")
                events = self.client.iter_events(stream_response)
                while True:
                    try:
                        event = _bounded_call(
                            lambda: next(events),
                            deadline=connect_deadline,
                            clock=self.clock,
                            real_deadline=connect_real_deadline,
                        )
                    except StopIteration:
                        break
                    # Check the clock before interpreting any received event.
                    if (
                        self.clock() >= connect_deadline
                        or time.monotonic() >= connect_real_deadline
                    ):
                        self._transition("timed_out")
                        raise TimeoutError
                    if event["type"] == "agent.session.environment.connected":
                        if event.get("environment_id") != session["environment_id"]:
                            raise ConnectivityError("connected_environment_mismatch")
                        if event.get("session_id") not in {None, session["session_id"]}:
                            raise ConnectivityError("connected_session_mismatch")
                        if self._audit["connected_observed"]:
                            raise ConnectivityError("duplicate_connected_event")
                        self._audit["connected_observed"] = True
                        self._transition("connected")
                        break
                    if event["type"] in {
                        "agent.session.environment.failed",
                        "agent.session.failed",
                        "error",
                    }:
                        raise ConnectivityError("remote_connection_failed")
                    if event["type"] not in {
                        "agent.session.environment.pending",
                        "agent.session.environment.disconnected",
                    }:
                        raise ConnectivityError("unexpected_event_type")
                if not self._audit["connected_observed"]:
                    self._transition("timed_out")
                    raise TimeoutError
            except Exception:
                if self.journal.pending.get(stream_intent) == "stream_open":
                    try:
                        self._outcome("stream_open", stream_intent, "operation_failed")
                    except DurabilityError:
                        pass
                raise
            finally:
                if stream_response is not None:
                    self.client.close_event_stream(stream_response)
        except SessionUnknown as exc:
            primary_code = exc.code
        except TimeoutError:
            primary_code = "deadline_expired"
            self._audit["failure_code"] = primary_code
            if self.state not in {"timed_out", "session_unknown"}:
                self._transition("timed_out")
        except Exception as exc:
            primary_code = exc.code if isinstance(exc, ConnectivityError) else "operation_failed"
            self._audit["failure_code"] = primary_code
            if self.state not in {"session_unknown", "timed_out", "failed"}:
                self._transition("failed")
        finally:
            self._cleanup_deadline = self.clock() + self.cleanup_seconds
            self._cleanup_real_deadline = time.monotonic() + self.cleanup_seconds
            cleanup_ready.set()
            late_worker_unsettled = False
            for settled in (late_create_settled, late_executor_settled):
                if settled is not None:
                    remaining = _remaining_cleanup()
                    if not settled.wait(remaining):
                        late_worker_unsettled = True
            with late_lock:
                if late_worker_unsettled:
                    late_state["detached"] = True
                if late_state["create_identity_verified"]:
                    self._audit["session_creation_outcome"] = "created_late"
                    self._audit["session_id_sha256"] = late_state.get("session_id_sha256")
                    self._audit["environment_id_sha256"] = late_state.get("environment_id_sha256")
                    self._audit["session_deletion_verified"] = late_state["create_delete_verified"]
            self._transition("stop_executor")
            if container_id is not None:
                self._audit["executor_termination_verified"] = self._cleanup_effect(
                    "executor_stop",
                    lambda: self.executor.stop_verified(
                        container_id,
                        timeout=_remaining_cleanup(),
                        **(
                            {"deadline": self._cleanup_real_deadline}
                            if type(self.executor) is DockerExecutorAdapter
                            else {}
                        ),
                    ),
                    resource_sha256=_sha256(container_id),
                )
            elif late_executor_settled is not None:
                self._audit["executor_termination_verified"] = late_state["executor_stop_verified"]
            elif (
                self._audit["executor_start_attempted"]
                and type(self.executor) is DockerExecutorAdapter
            ):
                self._audit["executor_termination_verified"] = self._cleanup_effect(
                    "executor_stop",
                    lambda: self.executor.stop_verified(
                        None,
                        timeout=_remaining_cleanup(),
                        deadline=self._cleanup_real_deadline,
                    ),
                    resource_sha256=(
                        _sha256(self.executor._pending_container_id)
                        if self.executor._pending_container_id
                        else None
                    ),
                )
            else:
                # No process identity is known; no executor termination is certified.
                self._audit["executor_termination_verified"] = (
                    not self._audit["executor_start_attempted"]
                    or late_state["executor_stop_verified"]
                )
            if self._audit["executor_termination_verified"]:
                self._transition("executor_stopped")
            else:
                self._transition("executor_stop_unverified")

            if session_known:
                try:
                    self._transition("delete_intent")
                    self._audit["session_deletion_verified"] = self._cleanup_effect(
                        "session_delete",
                        lambda: self.client.delete_session(
                            session["session_id"], timeout=_remaining_cleanup()
                        ),
                        resource_sha256=_sha256(session["session_id"]),
                    )
                    if self._audit["session_deletion_verified"]:
                        self._transition("session_deleted")
                except Exception:
                    self._audit["session_deletion_verified"] = False

            clean = bool(
                (
                    session_known
                    or late_state["create_identity_verified"]
                    or self._audit["session_deletion_not_required"]
                )
                and self._audit["executor_termination_verified"]
                and (
                    self._audit["session_deletion_verified"]
                    or self._audit["session_deletion_not_required"]
                )
                and self.journal.failed is False
                and not self.journal.pending
            )
            self._audit["cleanup_verified"] = clean
            if clean:
                self._transition("cleanup_verified")
            else:
                self._transition("cleanup_unverified")
            self._audit["finished_at"] = self.wall_clock()
            try:
                self._persist_audit()
            except BaseException:
                clean = False
                self._audit["cleanup_verified"] = False
                self.state = "cleanup_unverified"
            if clean:
                try:
                    release_intent = self._intent("lease_release")
                    # Persist release authorization before unlinking the lock. A
                    # crash after this record can leave a stale lock, which is
                    # fail-closed; it cannot leave an unjournaled clean release.
                    self._outcome("lease_release", release_intent, "release_authorized")
                    self.lease.release()
                except BaseException:
                    clean = False
                    self.state = "cleanup_unverified"
                    self._audit["state"] = self.state
            self._audit["cleanup_verified"] = clean
            if late_worker_unsettled:
                # The late callback owns these handles until it can durably record
                # its result. The lease remains held and recovery stays manual.
                def close_after_late_settlement():
                    for settled in (late_create_settled, late_executor_settled):
                        if settled is not None:
                            settled.wait()
                    self.journal.close()
                    self.client.close()

                threading.Thread(target=close_after_late_settlement, daemon=True).start()
            else:
                self.journal.close()
                self.client.close()

        if not clean:
            raise ConnectivityError(primary_code or "cleanup_unverified", state=self.state)
        return contract.sanitize_reference_data(
            self._audit,
            secrets=(self._environment_key, self.client._key),
            redact_urls=True,
        )


class DockerExecutorAdapter:
    """Narrow adapter around an injected reviewed runtime; no lifecycle controller."""

    def __init__(self, runtime, topology, workspace: Path, proxy_ip: str):
        self.runtime, self.topology = runtime, topology
        self.workspace, self.proxy_ip = Path(workspace), proxy_ip
        self._pending_container_id = None

    def start(self, session: dict, *, environment_key: str, timeout: float) -> str:
        if timeout <= 0:
            raise ConnectivityError("executor_preflight_failed")
        startup_deadline = time.monotonic() + timeout
        gateway = self.topology.start()
        if time.monotonic() >= startup_deadline:
            raise ConnectivityError("executor_start_deadline_expired")
        result = self.runtime.start_managed_executor(
            self.workspace,
            environment_id=session["environment_id"],
            remote_url=session["remote_url"],
            environment_key=environment_key,
            topology=self.topology,
            proxy_ip=gateway["proxy_internal_ip"],
        )
        container_id = result.get("container_id") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or result.get("executor_registered") is not False
            or not isinstance(container_id, str)
            or not re.fullmatch(r"[a-f0-9]{64}", container_id)
        ):
            self._pending_container_id = (
                container_id
                if isinstance(container_id, str) and re.fullmatch(r"[a-f0-9]{64}", container_id)
                else None
            )
            raise ConnectivityError("runtime_registration_claim_rejected")
        return container_id

    def stop_verified(
        self, container_id: str | None, *, timeout: float, deadline: float | None = None
    ) -> bool:
        if container_id is None:
            container_id = self._pending_container_id
        if timeout <= 0:
            return False
        deadline = (
            min(deadline, time.monotonic() + timeout)
            if deadline is not None
            else (time.monotonic() + timeout)
        )
        terminated = False
        if container_id is not None:
            try:
                terminated = bool(
                    _bounded_call(
                        lambda: self.runtime.stop_managed_executor(container_id),
                        deadline=deadline,
                        clock=time.monotonic,
                    )
                )
            except Exception:
                terminated = False
        else:
            terminated = False
        try:
            topology_removed = bool(
                _bounded_call(
                    self.topology.cleanup,
                    deadline=deadline,
                    clock=time.monotonic,
                )
            )
        except Exception:
            topology_removed = False
        if terminated:
            self._pending_container_id = None
        return terminated and topology_removed


def inspect_staging_journal(path: Path) -> dict:
    """Read bounded evidence only; never release a lease or authorize recovery."""
    report = {
        "integrity": "corrupt",
        "pending_intents": [],
        "cleanup_complete": False,
        "recovery_authorized": False,
        "synthetic": None,
        "lease_release_state": "unknown",
    }
    path = Path(path)
    if path.parent.name.startswith("run-") and path.parent.parent.name == JOURNAL_DIRNAME:
        report["lease_release_state"] = _release_marker_state(path.parent.parent)
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 8 << 20:
                return report
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                raw = source.read((8 << 20) + 1)
        finally:
            os.close(descriptor)
        if len(raw) > 8 << 20 or not raw.endswith(b"\n"):
            return report
        previous = "0" * 64
        pending = {}
        seen_operations = set()
        audit = False
        released = False
        synthetic = None
        for seq, line in enumerate(raw.splitlines(keepends=True), 1):
            entry = json.loads(line)
            if not isinstance(entry, dict) or set(entry) != {
                "schema_version",
                "record_type",
                "synthetic",
                "seq",
                "operation",
                "event",
                "intent_seq",
                "code",
                "resource_sha256",
                "previous_sha256",
            }:
                return report
            record_synthetic = entry["synthetic"]
            if (
                type(entry["seq"]) is not int
                or entry["seq"] != seq
                or not isinstance(entry["previous_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", entry["previous_sha256"])
                or entry["previous_sha256"] != previous
                or entry["record_type"]
                != "managed_agents_connectivity_journal_not_benchmark_result"
                or type(entry["schema_version"]) is not int
                or entry["schema_version"] != 1
                or type(record_synthetic) is not bool
                or (synthetic is not None and record_synthetic is not synthetic)
                or not isinstance(entry["operation"], str)
                or entry["operation"] not in ALLOWED_OPERATIONS
                or not isinstance(entry["code"], str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", entry["code"])
                or (
                    entry["resource_sha256"] is not None
                    and (
                        not isinstance(entry["resource_sha256"], str)
                        or not re.fullmatch(r"[a-f0-9]{64}", entry["resource_sha256"])
                    )
                )
            ):
                return report
            synthetic = record_synthetic
            operation = entry["operation"]
            if released:
                return report
            if (
                entry["event"] == "intent"
                and entry["intent_seq"] is None
                and entry["code"] == "ok"
                and operation not in seen_operations
                and (operation != "audit_persist" or not pending)
                and (operation != "lease_release" or (audit and not pending))
            ):
                pending[seq] = (operation, entry["resource_sha256"])
                seen_operations.add(operation)
            elif (
                entry["event"] == "outcome"
                and type(entry["intent_seq"]) is int
                and entry["intent_seq"] > 0
                and pending.get(entry["intent_seq"]) == (operation, entry["resource_sha256"])
            ):
                del pending[entry["intent_seq"]]
                if operation == "audit_persist" and entry["code"] == "ok":
                    audit = True
                if operation == "lease_release" and entry["code"] == "release_authorized":
                    released = True
            else:
                return report
            previous = hashlib.sha256(line).hexdigest()
        report["integrity"] = "valid" if raw else "incomplete"
        report["pending_intents"] = sorted(pending)
        report["synthetic"] = synthetic
        # Journal authorization is not independent proof of resource cleanup.
        report["durable_release_authorization"] = audit and released and not pending
        report["cleanup_complete"] = False
        return report
    except (OSError, ValueError, TypeError, AttributeError):
        return report
