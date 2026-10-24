"""Local, non-network F09 approval command. Contains no connectivity/run command."""

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


def main(argv=None):
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
    args = parser.parse_args(argv)
    try:
        store = harness.SoloOperatorApprovalStore(
            args.state_dir, read_only=args.command == "inspect"
        )
        if args.command == "approve":
            result = store.approve(
                _request(args.request), expires_in_seconds=args.expires_in_seconds
            )
        else:
            result = store.inspect()
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 0
    except (harness.ConnectivityError, harness.DurabilityError) as exc:
        print(getattr(exc, "code", "solo_state_unavailable"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
