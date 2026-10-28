"""Command line for study stage2_validity_v1. None of these commands runs a model or a container.

python -m benchmarks.codex_r.studies.stage2_validity_v1.cli <command> [options]

summarize-history  aggregate saved historical results (read-only) -> calibration summary + catalogue
build-manifest     regenerate experiment_manifest.json from the pinned inputs
render-prereg      regenerate PREREGISTRATION.md from the manifest
frozen             write (--write) or verify (--verify) frozen_evidence_digests.json
plan               write a seeded allocation plan for a design (pilot / confirmatory)
dry-run            run the synthetic scenarios end to end and write the evidence directory
reanalyze          recompute a dry-run analysis from its preserved inputs and compare digests
power              run the design-sensitivity simulation
analyze            run the preregistered analysis on a plan + trial_records.jsonl of a real study
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (
    calibration,
    calibration_pipeline,
    design,
    dryrun,
    isolation,
    manifest,
    power,
    prereg,
    protocol,
    scorer_calibration,
    study_configs,
)

STUDY = Path(__file__).resolve().parent


def _dump(path: Path, data) -> None:
    path.write_text(
        json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("summarize-history")
    s.add_argument("--results", type=Path, default=manifest.CODEX / "results")
    sub.add_parser("build-manifest")
    sub.add_parser("render-prereg")
    f = sub.add_parser("frozen")
    f.add_argument("--write", action="store_true")
    f.add_argument("--verify", action="store_true")
    p = sub.add_parser("plan")
    p.add_argument("--design", choices=sorted(power.DESIGNS) + ["pilot"], default="pilot")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    d = sub.add_parser("dry-run")
    d.add_argument("--out", type=Path, default=STUDY / "synthetic_validation")
    d.add_argument("--tasks", type=int, default=30)
    d.add_argument("--reps", type=int, default=3)
    d.add_argument("--seed", type=int, default=20261028)
    r = sub.add_parser("reanalyze")
    r.add_argument("directory", type=Path)
    r.add_argument("--seed", type=int, default=20261028)
    w = sub.add_parser("power")
    w.add_argument("--n-sim", type=int, default=300)
    w.add_argument("--n-perm", type=int, default=399)
    w.add_argument("--seed", type=int, default=20261028)
    w.add_argument("--out", type=Path, default=STUDY / "power_simulation.json")
    a = sub.add_parser("analyze")
    a.add_argument("--plan", type=Path, required=True)
    a.add_argument("--records", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    sc = sub.add_parser("scorer-calibration")
    sc.add_argument("--out", type=Path, default=STUDY / "scorer_calibration_report.json")
    ss = sub.add_parser("study-specs")
    ss.add_argument("--out", type=Path, default=STUDY / "study_specifications.json")
    ip = sub.add_parser("isolation-probes")
    ip.add_argument("--out", type=Path, default=STUDY / "isolation_probes_report.json")
    sr = sub.add_parser("smoke-runner")
    sr.add_argument("--out", type=Path, required=True)
    sr.add_argument("--seed", type=int, default=20261028)
    dp = sub.add_parser("docker-preflight")
    dp.add_argument("--out", type=Path, default=None)
    ls = sub.add_parser("live-smoke")
    ls.add_argument("--out", type=Path, required=True)
    ls.add_argument("--seed", type=int, default=20261028)
    ls.add_argument("--tasks", nargs="+", default=["D01", "D02", "D03"])
    ls.add_argument("--reps", type=int, default=1)
    cp = sub.add_parser("calibration-pipeline")
    cp.add_argument("--out-dir", type=Path, default=STUDY)
    rg = sub.add_parser("readiness-gates")
    rg.add_argument("--out", type=Path, default=STUDY / "readiness_gates_report.json")
    args = parser.parse_args(argv)

    if args.command == "summarize-history":
        summary = calibration.summarize_history(args.results)
        _dump(STUDY / "historical_calibration_summary.json", summary)
        _dump(STUDY / "task_catalog.json", calibration.build_catalog(summary))
    elif args.command == "build-manifest":
        _dump(STUDY / "experiment_manifest.json", manifest.build_manifest())
    elif args.command == "render-prereg":
        built = json.loads((STUDY / "experiment_manifest.json").read_text(encoding="utf-8"))
        (STUDY / "PREREGISTRATION.md").write_text(
            prereg.render(built), encoding="utf-8", newline="\n"
        )
    elif args.command == "frozen":
        if args.write:
            _dump(STUDY / "frozen_evidence_digests.json", manifest.frozen_digests())
        recorded = json.loads((STUDY / "frozen_evidence_digests.json").read_text(encoding="utf-8"))
        problems = manifest.verify_frozen(recorded)
        print(f"{len(recorded['files'])} frozen files; {len(problems)} differences")
        for line in problems[:20]:
            print(" ", line)
        return 1 if problems else 0
    elif args.command == "plan":
        if args.design == "pilot":
            tasks, reps = list(manifest.PILOT_TASKS), 3
        else:
            count, reps = power.DESIGNS[args.design]
            tasks = [f"NEW{i:02d}" for i in range(1, count + 1)]
        plan = design.build_plan(tasks, ("A", "B", "C"), reps, args.seed, protocol.STUDY_ID)
        problems = design.verify_plan(plan)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        _dump(args.out, plan)
    elif args.command == "dry-run":
        summary = {}
        for name in dryrun.SCENARIOS:
            outcome = dryrun.run_scenario(args.out / name, name, args.tasks, args.reps, args.seed)
            primary = outcome["result"]["analysis"]["primary"]
            summary[name] = {
                "digest": outcome["digest"],
                "estimate_B_minus_A": primary["estimate"],
                "ci95": [primary["ci"]["low"], primary["ci"]["high"]],
                "p_value": primary["p_value"],
                "violations": outcome["result"]["violation_codes"],
                "outcome_kinds": outcome["result"]["outcome_kinds"],
            }
        _dump(
            args.out / "SUMMARY.json", {"synthetic": True, "seed": args.seed, "scenarios": summary}
        )
    elif args.command == "reanalyze":
        plan, recs = dryrun.read_inputs(args.directory)
        fresh = dryrun.result_digest(dryrun.analyse(plan, recs, args.seed))
        stored = dryrun.result_digest(
            json.loads((args.directory / "analysis.json").read_text("utf-8"))
        )
        print("reproduced" if fresh == stored else "DIFFERENT", fresh)
        return 0 if fresh == stored else 1
    elif args.command == "power":
        table = power.power_table(power.Assumptions(), args.n_sim, args.n_perm, args.seed)
        _dump(args.out, table)
    elif args.command == "analyze":
        from . import analysis, records

        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        recs = [json.loads(x) for x in args.records.read_text(encoding="utf-8").splitlines() if x]
        problems = design.verify_plan(plan) + records.validate_dataset(
            recs, [t["trial_id"] for t in plan["trials"]]
        )
        if problems:
            print("\n".join(problems[:20]), file=sys.stderr)
            return 1
        _dump(args.out, analysis.run_preregistered_analysis(recs, plan["seed"]))
    elif args.command == "scorer-calibration":
        report = scorer_calibration.run_scorer_calibration_suite()
        _dump(args.out, report)
        return 0 if report["all_probes_matched_expected_behavior"] else 1
    elif args.command == "study-specs":
        _dump(args.out, study_configs.build_study_specifications())
    elif args.command == "isolation-probes":
        probes = isolation.run_synthetic_isolation_probes()
        legacy = isolation.inspect_legacy_runner_isolation()
        _dump(args.out, {"synthetic_probes": probes, "legacy_runner_audit": legacy})
        return 0 if probes["all_policy_invariants_satisfied"] else 1
    elif args.command == "smoke-runner":
        res = study_configs.run_smoke_mock_study(args.out, seed=args.seed)
        return 1 if res["dataset_problems"] else 0
    elif args.command == "docker-preflight":
        from . import live_network

        status = live_network.docker_status()
        print(json.dumps(status, indent=2))
        if args.out:
            _dump(args.out, status)
        return 0 if status["ready"] else 1
    elif args.command == "live-smoke":
        # Opt-in: real Docker containers and networks, local mock model, no credentials.
        from . import live_network, live_runner, runner

        plan = design.build_plan(
            args.tasks, ("A", "B", "C"), args.reps, args.seed, protocol.STUDY_ID
        )
        cfg = runner.StudyExecutionConfig(
            stage="live_smoke_mock_model",
            timeout_seconds=120,
            max_infra_retries=1,
            stop_on_invalidating_violation=True,
            synthetic=True,
        )
        try:
            res = live_runner.execute_live_study(plan, cfg, args.out)
        except live_network.DockerUnavailable as exc:
            print(f"BLOCKED: live Docker verification unavailable: {exc}", file=sys.stderr)
            return 2
        kinds = sorted({r["outcome_kind"] for r in res["records"]})
        clean = res["resource_cleanup"]["remaining_after"]
        print(
            f"finalized={res['finalized_count']}/{res['planned_count']} kinds={kinds} "
            f"problems={res['dataset_problems']} cleanup={clean}"
        )
        ok = not res["dataset_problems"] and not clean["containers"] and not clean["networks"]
        return 0 if ok else 1
    elif args.command == "calibration-pipeline":
        eligibility = calibration_pipeline.audit_task_eligibility()
        _dump(args.out_dir / "calibration_eligibility_report.json", eligibility)
        schedule = calibration_pipeline.build_calibration_schedule()
        _dump(args.out_dir / "calibration_schedule.json", schedule)
        pilot_spec = calibration_pipeline.build_pilot_specification()
        _dump(args.out_dir / "pilot_specification.json", pilot_spec)
        print(
            f"Generated eligibility report ({eligibility['total_benchmark_tasks']} tasks), "
            f"schedule ({schedule['total_planned_trials']} trials), and pilot spec"
        )
        return 0
    elif args.command == "readiness-gates":
        gates = calibration_pipeline.evaluate_readiness_gates()
        _dump(args.out, gates)
        for g in gates["gates"]:
            print(f"[{g['status']}] {g['gate_id']}: {g['name']}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
