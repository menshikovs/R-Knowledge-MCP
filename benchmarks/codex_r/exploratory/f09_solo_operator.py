"""Local F09 solo-operator approval and connectivity commands."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

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
    runtime_path = Path(__file__).with_name("docker_runtime.py")
    runtime_spec = importlib.util.spec_from_file_location("f09_docker_runtime", runtime_path)
    if runtime_spec is None or runtime_spec.loader is None:
        raise harness.ConnectivityError("solo_runtime_configuration_mismatch")
    runtime_module = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(runtime_module)

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
    args = parser.parse_args(argv)
    try:
        if _store_factory is None:
            store = harness.SoloOperatorApprovalStore(
                args.state_dir, read_only=args.command == "inspect"
            )
        else:
            store = _store_factory(args.state_dir, read_only=args.command == "inspect")
        if args.command == "approve":
            result = store.approve(
                _request(args.request), expires_in_seconds=args.expires_in_seconds
            )
        elif args.command == "inspect":
            result = store.inspect()
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
        print("f09_run_failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
