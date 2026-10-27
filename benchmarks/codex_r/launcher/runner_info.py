"""Read-only information for the launcher, taken from the real runner code.

Subcommands (arguments are plain argv values, nothing is evaluated):

catalog                      task ids, B1 plan and per-task scorers as ``key=values`` lines
runs --results DIR --limit N one tab separated line per run directory
summary --run DIR            one tab separated line per recorded trial

It never writes, never starts Docker and never calls the network.  Resume validation
is the runner's own ``load_resume_records``; B1 order and scorers come from the runner's
``planned_b1_trials`` / ``scorer_for_task``.
"""

import argparse
import json
import re
import sys
from argparse import Namespace
from pathlib import Path

from benchmarks.codex_r import run_simple as s

RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
SUCCESS = {"scored", "smoke_transport_observed"}
MAX_TEXT = 160


def clean(value):
    text = "" if value is None else str(value)
    return re.sub(r"[\t\r\n]+", " ", text)[:MAX_TEXT]


def catalog():
    print("r=" + " ".join(s.R_TASKS))
    print("hard=" + " ".join(s.hard.task_ids()))
    print("knowledge=" + " ".join(s.knowledge_pilot.PILOT_TASK_IDS))
    print("tool_value=" + " ".join(s.knowledge_pilot.task_ids()))
    print("full=" + " ".join(s.FULL_VERIFIED_TASKS))
    print("instructions=" + " ".join(sorted(s.INSTRUCTION_VARIANTS)))
    print("smoke=" + s.MCP_SMOKE_TASK)
    print("results_dir=" + str(s.bench.ROOT / "results"))
    tasks = list(s.B1_DISCOVERY_TASKS)
    trials = s.planned_b1_trials(tasks, 2)
    args = Namespace(
        experiment=s.B1_DISCOVERY_EXPERIMENT, knowledge_pilot_scorer="knowledge-pilot-v2"
    )
    print("b1_tasks=" + " ".join(tasks))
    print("b1_repetitions=2")
    print("b1_order=" + " ".join(f"{t['task']}:{t['repetition']}:{t['condition']}" for t in trials))
    print("b1_scorers=" + " ".join(f"{t}:{s.scorer_for_task(args, t)}" for t in tasks))


def read_json(path):
    if path.is_symlink() or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def describe(run):
    """Facts about one run directory; unknown stays unknown."""
    info = {
        "run_id": run.name,
        "experiment": "unknown",
        "created": "unknown",
        "effort": "unknown",
        "total": "unknown",
        "recorded": "unknown",
        "status": "unknown",
        "cleanup": "unknown",
        "resume": "blocked: no experiment.json",
    }
    try:
        experiment = read_json(run / "experiment.json")
    except (OSError, ValueError):
        experiment = None
    try:
        aggregate = read_json(run / "results.json")
    except (OSError, ValueError):
        aggregate = None
    if not isinstance(aggregate, list):
        aggregate = []
    if not isinstance(experiment, dict):
        # e.g. a run that stopped before the manifest was written
        statuses = sorted({str(r.get("status")) for r in aggregate if isinstance(r, dict)})
        if statuses:
            info["status"] = "/".join(statuses)
        return info
    info.update(
        experiment=str(experiment.get("experiment_id") or "standard"),
        created=str(experiment.get("created_at_utc") or "unknown"),
        effort=str(experiment.get("effort") or "unknown"),
        total=str(experiment.get("trial_count", "unknown")),
    )
    try:
        records, completed = s.load_resume_records(run, experiment)
    except Exception as exc:  # noqa: BLE001 - the runner's refusal text is the diagnostic
        info["resume"] = "blocked: " + clean(exc)
        records, completed = [r for r in aggregate if isinstance(r, dict)], None
    else:
        info["resume"] = "ok"
        info["recorded"] = str(len(completed))
    states = [str(r.get("status")) for r in records]
    if any(r.get("interrupted") for r in records) or "interrupted" in states:
        info["status"] = "interrupted"
    elif completed is not None and info["total"].isdigit() and len(completed) == int(info["total"]):
        info["status"] = "finished"
    elif completed is not None and not completed:
        info["status"] = "not started"
    elif completed is not None:
        info["status"] = "partial"
    if any(r.get("cleanup_completed") is False for r in records):
        info["cleanup"] = "incomplete"
    elif records:
        info["cleanup"] = "complete"
    info["errors"] = str(sum(1 for r in records if r.get("status") not in SUCCESS))
    return info


FIELDS = [
    "run_id",
    "experiment",
    "created",
    "effort",
    "total",
    "recorded",
    "status",
    "cleanup",
    "resume",
]


def runs(results, limit):
    root = Path(results)
    names = sorted((p for p in root.iterdir() if p.is_dir() and RUN_ID.match(p.name)), reverse=True)
    for run in names[:limit]:
        info = describe(run)
        print("\t".join(clean(info.get(field)) for field in FIELDS))


def summary(run):
    root = Path(run)
    rows = read_json(root / "results.json") or []
    for record in rows:
        if not isinstance(record, dict):
            continue
        score = record.get("score") or {}
        passed, total = score.get("passed"), score.get("total")
        print(
            "\t".join(
                clean(x)
                for x in (
                    record.get("trial_id") or record.get("trial"),
                    record.get("condition") or "",
                    record.get("task") or "",
                    record.get("status"),
                    f"{passed}/{total}" if passed is not None and total is not None else "none",
                    "incomplete" if record.get("cleanup_completed") is False else "complete",
                )
            )
        )


def main(argv):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    runs_parser = sub.add_parser("runs")
    runs_parser.add_argument("--results", required=True)
    runs_parser.add_argument("--limit", type=int, default=10)
    summary_parser = sub.add_parser("summary")
    summary_parser.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    if args.command == "catalog":
        catalog()
    elif args.command == "runs":
        runs(args.results, max(1, min(args.limit, 100)))
    else:
        summary(args.run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
