"""Harmless stand-in for benchmarks.codex_r.run_simple used by the launcher tests.

It accepts the same flags the launcher passes, never touches Docker, the network or
any credential, and prints lines in the formats of the real runner's Progress and
main loop.  Behaviour is selected with FAKE_MODE (environment):

ok          every trial is scored, exit 0 (default)
fail        the first trial errors, then exit 1
stderr      writes a warning to stderr, then behaves like ok
sigint      runs until SIGINT, simulates 1.5 s of cleanup, exits 130 like the runner
ignore      ignores SIGINT (to exercise the launcher's forced kill)
crash       kills itself with SIGKILL after the first trial starts
noconnect   never prints "executor connected": prints the runner's watchdog line, then waits
            for SIGINT like `sigint`
incomplete  like `sigint`, but cleanup ends as "Cleanup incomplete" with exit status 1
timeout     like `noconnect`, plus an explicit EXECUTOR_CONNECTION_TIMEOUT message
"""

import argparse
import os
import secrets
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

MODE = os.environ.get("FAKE_MODE", "ok")
DELAY = float(os.environ.get("FAKE_DELAY", "0.05"))
OUTPUT = os.environ.get("FAKE_RESULTS", "/tmp/fake-run")
stopping = False

B1_ORDER = [
    ("D03", 1, "control"),
    ("D03", 1, "treatment"),
    ("D01", 1, "treatment"),
    ("D01", 1, "control"),
    ("C01", 1, "control"),
    ("C01", 1, "treatment"),
    ("D03", 2, "treatment"),
    ("D03", 2, "control"),
    ("D01", 2, "control"),
    ("D01", 2, "treatment"),
    ("C01", 2, "treatment"),
    ("C01", 2, "control"),
]


def say(text, stream=sys.stdout):
    print(text, file=stream, flush=True)


def on_sigint(signum, frame):
    global stopping
    stopping = True


parser = argparse.ArgumentParser()
parser.add_argument("--effort", required=True)
parser.add_argument("--tasks", nargs="+")
parser.add_argument("--pilot")
parser.add_argument("--experiment")
parser.add_argument("--resume")
parser.add_argument("--results")
parser.add_argument("--modes", nargs="+", default=["without-mcp", "with-mcp"])
parser.add_argument("--repetitions", type=int, default=1)
parser.add_argument("--timeout", type=int, default=900)
parser.add_argument("--instructions", default="standard")
parser.add_argument("--knowledge-pilot-scorer", default="legacy")
parser.add_argument("--executor-image")
parser.add_argument("--scorer-image")
parser.add_argument("--mcp-image")
args = parser.parse_args()

say(f"ARGV {' '.join(sys.argv[1:])}")
signal.signal(signal.SIGINT, signal.SIG_IGN if MODE == "ignore" else on_sigint)
if MODE == "stderr":
    say("fake: a warning on stderr", sys.stderr)

if args.results and not args.resume:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
    Path(args.results, stamp).mkdir(parents=True)
    OUTPUT = str(Path(args.results, stamp))

if args.experiment == "b1-discovery":
    trials = [(f"b1-discovery-{t}-R{r}-{c}", t) for t, r, c in B1_ORDER]
elif args.resume:
    trials = [("resumed-D03-B-1", "D03")]
else:
    tasks = args.tasks or ["PILOT"]
    trials = [
        (f"{task}-{'B' if mode == 'with-mcp' else 'A'}-{repetition}", task)
        for repetition in range(1, args.repetitions + 1)
        for task in tasks
        for mode in dict.fromkeys(args.modes)
    ]

waits_for_sigint = MODE in {"sigint", "ignore", "noconnect", "incomplete", "timeout"}
done = 0
for trial, _task in trials:
    say(f"{trial}: session created [0.5s]")
    say(f"{trial}: Docker executor started [0.8s]")
    if MODE == "crash":
        os.kill(os.getpid(), signal.SIGKILL)
    if MODE in {"noconnect", "timeout"}:
        say(f"{trial}: waiting: waiting for executor [15.0s]")
        say(f"{trial}: executor not connected [45.0s]")
        if MODE == "timeout":
            say(f"{trial}: EXECUTOR_CONNECTION_TIMEOUT [60.0s]")
    deadline = time.monotonic() + (30 if waits_for_sigint else DELAY)
    while time.monotonic() < deadline and not stopping:
        time.sleep(0.02)
    if stopping:
        say(f"{trial}: waiting: cleanup [1.0s]")
        time.sleep(1.5)
        if MODE == "incomplete":
            say(f"{trial}: interrupted score=None/None; error recorded")
            say(f"Cleanup incomplete. Results: {OUTPUT}")
            sys.exit(1)
        say(f"{trial}: cleanup completed [2.5s]")
        say(f"{trial}: interrupted score=None/None; error recorded")
        say(f"Results: {OUTPUT}")
        sys.exit(130)
    say(f"{trial}: executor connected [2.0s]")
    say(f"{trial}: waiting: running turn [5.0s]")
    say(f"{trial}: cleanup completed [9.0s]")
    if MODE == "fail" and done == 0:
        say(f"{trial}: error score=None/None; error recorded")
        say(f"Cleanup incomplete. Results: {OUTPUT}")
        sys.exit(1)
    say(f"{trial}: scored score=4/4")
    done += 1
say(f"Results: {OUTPUT}")
sys.exit(0)
