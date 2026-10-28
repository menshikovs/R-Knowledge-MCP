"""Command line for study stage2_validity_v1.

Only ``execute-calibration --executor live`` and ``execute-study`` can call a real model. Both
run the existing benchmark runner (run_simple.run_trial), refuse to start without
``--authorize-spend`` *and* a complete spend ceiling, and then require Linux, Docker, the
OPENAI_API_KEY/OPENAI_EXECUTOR_API_KEY variables and the runner images. ``live-smoke`` and
``execute-calibration --executor docker-mock-model`` start containers with a local mock model.

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
calibration-pipeline, readiness-gates, execute-calibration, evaluate-baseline: Stage 2.7

execute-study: run a pinned A/B/C plan (plan --pin) for study1 through run_simple; study2 is
unsupported and refused.

Exit codes of execute-calibration / execute-study: 0 ok, 1 dataset problems, 2 refused input or
blocked environment, 3 live execution structurally unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STUDY = Path(__file__).resolve().parent
REPO_ROOT = STUDY.parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from . import (  # noqa: E402
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
    spend_control,
    study_configs,
)


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    p.add_argument(
        "--tasks", nargs="+", default=None, help="explicit task ids (overrides --design tasks)"
    )
    p.add_argument("--reps", type=int, default=None, help="repetitions with --tasks (default 3)")
    p.add_argument(
        "--pin", action="store_true", help="pin task/scorer digests (required by execute-study)"
    )
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
    am = sub.add_parser("amendment", help="write or verify preregistration_amendment_a1.json")
    am.add_argument("--write", action="store_true")
    am.add_argument("--verify", action="store_true")
    ec = sub.add_parser(
        "execute-calibration",
        help="Run the Arm-A calibration schedule (mock executors only; live is unavailable)",
    )
    ec.add_argument(
        "--schedule",
        type=Path,
        default=STUDY / "calibration_schedule.json",
        help="Path to calibration_schedule.json (default: study directory)",
    )
    ec.add_argument(
        "--out-dir",
        type=Path,
        default=STUDY / "calibration_runs",
        help="Directory to persist calibration records and journal",
    )
    ec.add_argument(
        "--executor",
        choices=calibration_pipeline.EXECUTOR_MODES,
        help=(
            "mock: in-process, no network; docker-mock-model: real Docker isolation with a "
            "local mock model; live: real model (currently UNAVAILABLE, exits 3)"
        ),
    )
    ec.add_argument("--mock", action="store_true", help="Deprecated alias for --executor mock")
    ec.add_argument(
        "--authorize-spend",
        action="store_true",
        help="Live only. Not sufficient on its own: an explicit spend ceiling is also required",
    )
    ec.add_argument("--max-spend-usd", type=float, help="Hard ceiling on accounted spend (USD)")
    ec.add_argument(
        "--input-usd-per-mtok", type=float, help="Owner-supplied price per 1M input tokens"
    )
    ec.add_argument(
        "--output-usd-per-mtok", type=float, help="Owner-supplied price per 1M output tokens"
    )
    ec.add_argument(
        "--per-trial-reserve-usd",
        type=float,
        help="Maximum cost one attempt may incur; charged in full when usage is unobservable",
    )
    es = sub.add_parser(
        "execute-study",
        help="Run a pinned A/B/C plan through run_simple (real model; authorization required)",
    )
    es.add_argument("--study", choices=sorted(("study1", "study2")), required=True)
    es.add_argument("--plan", type=Path, required=True)
    es.add_argument("--out-dir", type=Path, required=True)
    es.add_argument("--effort", choices=("medium", "high"), default="medium")
    es.add_argument("--timeout", type=int, default=900)
    es.add_argument("--executor-image", default=None)
    es.add_argument("--scorer-image", default=None)
    es.add_argument("--mcp-image", default="cran-knowledge-mcp:shiny-quarto")
    es.add_argument("--authorize-spend", action="store_true")
    es.add_argument("--max-spend-usd", type=float)
    es.add_argument("--input-usd-per-mtok", type=float)
    es.add_argument("--output-usd-per-mtok", type=float)
    es.add_argument("--per-trial-reserve-usd", type=float)
    eb = sub.add_parser(
        "evaluate-baseline",
        help="Evaluate baseline difficulty, variance, and uncertainty from Arm A trial records",
    )
    eb.add_argument(
        "--records",
        type=Path,
        required=True,
        help="Path to trial_records.jsonl from calibration run",
    )
    eb.add_argument(
        "--out",
        type=Path,
        default=STUDY / "baseline_difficulty_report.json",
        help="Output path for baseline difficulty report JSON",
    )
    eb.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="Evaluate synthetic records anyway; the report is labelled as not baseline evidence",
    )
    # Alias evaluate-calibration to evaluate-baseline for documented compatibility
    ec_eval = sub.add_parser(
        "evaluate-calibration",
        help="Alias for evaluate-baseline",
    )
    ec_eval.add_argument(
        "--records",
        type=Path,
        required=True,
        help="Path to trial_records.jsonl from calibration run",
    )
    ec_eval.add_argument(
        "--out",
        type=Path,
        default=STUDY / "baseline_difficulty_report.json",
        help="Output path for baseline difficulty report JSON",
    )
    ec_eval.add_argument("--allow-synthetic", action="store_true", help="See evaluate-baseline")
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
        if args.tasks:
            tasks, reps = list(dict.fromkeys(args.tasks)), args.reps or 3
        elif args.design == "pilot":
            tasks, reps = list(manifest.PILOT_TASKS), 3
        else:
            count, reps = power.DESIGNS[args.design]
            tasks = [f"NEW{i:02d}" for i in range(1, count + 1)]
        plan = design.build_plan(tasks, ("A", "B", "C"), reps, args.seed, protocol.STUDY_ID)
        problems = design.verify_plan(plan)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        if args.pin:
            from . import legacy_executor

            plan = legacy_executor.pin_plan_identities(plan)
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
    elif args.command == "amendment":
        from . import amendment

        built = amendment.build_amendment_record()
        if args.write:
            _dump(amendment.RECORD, built)
        recorded = json.loads(amendment.RECORD.read_text(encoding="utf-8"))
        same = recorded == built
        print(
            f"amendment {built['amendment_id']} (protocol {built['protocol_version']}): "
            + ("matches the originals and its document" if same else "DIFFERS")
        )
        return 0 if same else 1
    elif args.command == "readiness-gates":
        gates = calibration_pipeline.evaluate_readiness_gates()
        _dump(args.out, gates)
        for g in gates["gates"]:
            print(f"[{g['status']}] {g['gate_id']}: {g['name']}")
        return 0
    elif args.command == "execute-calibration":
        return _execute_calibration(args)
    elif args.command == "execute-study":
        return _execute_study(args)
    elif args.command in ("evaluate-baseline", "evaluate-calibration"):
        try:
            recs = calibration_pipeline.load_baseline_evidence(
                args.records, allow_synthetic=args.allow_synthetic
            )
            res = calibration_pipeline.evaluate_baseline_difficulty(
                recs, allow_synthetic=args.allow_synthetic
            )
        except calibration_pipeline.SyntheticEvidenceError as exc:
            print(
                f"REFUSED: {exc}. --allow-synthetic is for pipeline checks only.", file=sys.stderr
            )
            return 2
        _dump(args.out, res)
        print(
            f"Evaluated baseline difficulty for {res['evaluated_tasks']} tasks -> {args.out} "
            f"[{res['evidence_status']}]"
        )
        for tid, tinfo in res["tasks"].items():
            print(
                f"  {tid}: mean={tinfo['mean_score']} status={tinfo['uncertainty_status']} "
                f"class={tinfo['classification']}"
            )
        return 0
    return 0


def _ceiling(args: argparse.Namespace) -> tuple[bool, spend_control.SpendCeiling | None]:
    """(ok, ceiling): all four ceiling arguments or none of them."""
    prices = (
        args.max_spend_usd,
        args.input_usd_per_mtok,
        args.output_usd_per_mtok,
        args.per_trial_reserve_usd,
    )
    if all(v is None for v in prices):
        return True, None
    if any(v is None for v in prices):
        print(
            "REFUSED: a spend ceiling needs all of --max-spend-usd, --input-usd-per-mtok, "
            "--output-usd-per-mtok and --per-trial-reserve-usd",
            file=sys.stderr,
        )
        return False, None
    return True, spend_control.SpendCeiling(*prices)


def _execute_study(args: argparse.Namespace) -> int:
    from . import legacy_executor

    ok, ceiling = _ceiling(args)
    if not ok:
        return 2
    study = legacy_executor.STUDIES[args.study]
    if not study.supported:
        print(f"REFUSED: {study.id} is unsupported: {study.unsupported_reason}", file=sys.stderr)
        return 2
    if not args.authorize_spend or ceiling is None or ceiling.problems():
        print(
            "REFUSED: execute-study calls a real model; it requires --authorize-spend and a "
            "valid, complete spend ceiling",
            file=sys.stderr,
        )
        return 2
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    problems = design.verify_plan(plan) + legacy_executor.plan_identity_problems(plan)
    if problems:
        print("REFUSED: " + "; ".join(problems[:10]), file=sys.stderr)
        return 2
    try:
        ctx = legacy_executor.preflight(
            plan["tasks"],
            study=study,
            effort=args.effort,
            timeout_seconds=args.timeout,
            need_mcp=any(protocol.ARMS[a].mcp_available for a in plan["arms"]),
            executor_image=args.executor_image,
            scorer_image=args.scorer_image,
            mcp_image=args.mcp_image,
        )
        res = legacy_executor.execute_study(plan, args.out_dir, ctx, spend_ceiling=ceiling)
    except legacy_executor.LegacyRunnerUnavailable as exc:
        print("BLOCKED: " + "; ".join(exc.reasons), file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(
        f"Executed {res['study_configuration']}: {res['finalized_count']}/{res['planned_count']} "
        f"trials; stopped_reason={res['stopped_reason']}; accounted spend "
        f"{res['spend']['accounted_spend_usd']} USD"
    )
    return 1 if res["dataset_problems"] else 0


def _execute_calibration(args: argparse.Namespace) -> int:
    mode = args.executor or ("mock" if args.mock else None)
    if mode is None or (args.mock and args.executor not in (None, "mock")):
        print(
            "REFUSED: choose exactly one --executor {mock,docker-mock-model,live}", file=sys.stderr
        )
        return 2
    ok, ceiling = _ceiling(args)
    if not ok:
        return 2
    from . import legacy_executor, live_network

    try:
        res = calibration_pipeline.execute_calibration(
            schedule=args.schedule,
            out_dir=args.out_dir,
            executor_mode=mode,
            authorize_spend=args.authorize_spend,
            spend_ceiling=ceiling,
        )
    except calibration_pipeline.LiveExecutionUnavailable as exc:
        print("UNAVAILABLE: the schedule cannot run on the real execution path; nothing ran.")
        for blocker in exc.blockers:
            print(f"  - {blocker['id']}: {blocker.get('tasks')}")
        return 3
    except legacy_executor.LegacyRunnerUnavailable as exc:
        print("BLOCKED: " + "; ".join(exc.reasons), file=sys.stderr)
        return 2
    except live_network.DockerUnavailable as exc:
        print(f"BLOCKED: live Docker verification unavailable: {exc}", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(
        f"Executed calibration [{res['executor_mode']}, {res['evidence_status']}]: "
        f"{res['finalized_count']}/{res['total_planned']} trials persisted to "
        f"{res['records_path']}; stopped_reason={res['stopped_reason']}"
    )
    if res["spend"] is not None:
        print(f"  accounted spend: {res['spend']['accounted_spend_usd']} USD")
    if res["dataset_problems"]:
        for prob in res["dataset_problems"][:10]:
            print(f"  [ERROR] {prob}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
