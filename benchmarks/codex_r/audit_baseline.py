"""Offline, read-only extraction for the 2026-10-25 baseline root cause audit.

Run with ``python -m benchmarks.codex_r.audit_baseline``. No runner,
network client, R process or model is invoked. Optional JSON-only re-evaluation
uses the existing pure offline scorer. Interpretation is in the report;
this module only combines saved observations and explicitly labelled annotations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
RUN_ID = "20261025T135949Z-9ff06c47"
MAX_FILE_BYTES = 16 << 20


def read_json(path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Oversized audit input: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def inventory(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"), key=lambda p: p.as_posix())
        if p.is_file()
    }


def tree_digest(root, suffix):
    # The baseline was created on Linux: Windows Path sorting folds case.
    digest = hashlib.sha256()
    for p in sorted(root.rglob(f"*{suffix}"), key=lambda p: p.as_posix()):
        if "__pycache__" not in p.parts:
            digest.update(p.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(p.read_bytes()).digest())
    return digest.hexdigest()


def names(value):
    return [value] if isinstance(value, str) else value if isinstance(value, list) else []


def event_calls(events):
    """Deduplicate added/done snapshots by item identity, retaining incomplete calls."""
    calls = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") not in {"mcp_call", "mcp_tool_call"}:
            continue
        identity = item.get("id") or item.get("call_id") or event.get("item_id")
        identity = identity or f"missing-identity-{index}"
        row = calls.setdefault(identity, {"item_id": identity, "event_indices": []})
        row["event_indices"].append(index)
        row["tool"] = item.get("name") or item.get("tool_name") or item.get("tool")
        row["event_status"] = item.get("status")
        row["payload_redacted"] = item.get("payload_redacted", False)
        row["done"] = row.get("done", False) or str(event.get("type", "")).endswith("item.done")
        if row["done"]:
            row["done_index"] = index
    return list(calls.values())


def tool_rows(record, events, prefix):
    calls = event_calls(events)
    telemetry = (record.get("mcp_telemetry") or {}).get("calls") or []
    completed = sorted((c for c in calls if c["done"]), key=lambda c: c["done_index"])
    # Logs contain no common client/server call ID. Only use the observed
    # completion-order/name match; never guess across missing or reordered calls.
    aligned = len(completed) == len(telemetry) and all(
        c["tool"] == t.get("tool_name") for c, t in zip(completed, telemetry, strict=True)
    )
    lookup = (
        {c["item_id"]: (n, t) for n, (c, t) in enumerate(zip(completed, telemetry, strict=True), 1)}
        if aligned
        else {}
    )
    if not calls:
        calls = [
            {"tool": t.get("tool_name"), "event_indices": [], "item_id": None} for t in telemetry
        ]
    rows = []
    for sequence, call in enumerate(calls, 1):
        number, data = lookup.get(call["item_id"], (None, {}))
        if not call["event_indices"]:
            number, data = sequence, telemetry[sequence - 1]
        code = data.get("error_code") or ";".join(data.get("error_codes") or []) or None
        status = {"ok": "success", "error": "error"}.get(data.get("status"), "unknown")
        repeat = data.get("repeat_kind")
        category = (
            "error"
            if status == "error"
            else (
                "repeated"
                if repeat in {"identical", "identical_after_error"}
                else "potentially_useful_use_unconfirmed"
                if status == "success"
                else "insufficient_data"
            )
        )
        rows.append(
            {
                "run_id": record["run_id"],
                "task": record["task"],
                "trial_id": record["trial_id"],
                "sequence": sequence,
                "telemetry_call_number": number,
                "tool": call["tool"],
                "arguments_json": None,
                "arguments_status": "unavailable_not_reconstructed",
                "event_status": call.get("event_status"),
                "status": status,
                "error_code": code,
                "observed_result_package": data.get("package"),
                "observed_result_repository": data.get("repository"),
                "verification_status": data.get("verification_status"),
                "response_bytes_recorded": data.get("response_bytes"),
                "response_bytes_basis": "server_measured_serialized_result_json",
                "response_payload_bytes_retained": None,
                "response_payload_status": "unavailable_redacted",
                "request_bytes_recorded": data.get("request_bytes"),
                "latency_ms": data.get("duration_ms"),
                "timestamp_utc": data.get("timestamp_utc"),
                "argument_fingerprint": data.get("argument_fingerprint"),
                "repeated": repeat,
                "repeat_count": data.get("repeat_count"),
                "semantic_repeat": "unknown",
                "relevance": "unknown_payload_unavailable",
                "category": category,
                "observed_use": "not_observable_at_response_level",
                "page_truncated": data.get("page_truncated"),
                "output_truncated": data.get("output_truncated"),
                "item_id": call["item_id"],
                "join_basis": "ordinal_unconfirmed_order_and_name"
                if aligned and number is not None
                else ("telemetry_only" if not call["event_indices"] else "unmatched"),
                "event_evidence": ";".join(
                    f"{prefix}/events.json#$[{i}].item" for i in call["event_indices"]
                ),
                "telemetry_evidence": f"{prefix}/result.json#$.mcp_telemetry.calls[{number - 1}]"
                if number
                else None,
            }
        )
    return rows, aligned


def check_catalog(task, records):
    """Read literal check names, without evaluating R or scorer expressions."""
    file = ROOT / ("hard" if task.startswith("H") else "knowledge_pilot")
    file = file / "verifier" / f"{task}.R"
    if file.is_file():
        return re.findall(r'^check\("([^"\n]+)"\s*,', file.read_text(encoding="utf-8"), re.M)
    details = [d for r in records for d in (r.get("score") or {}).get("details", [])]
    return list(
        dict.fromkeys(d.rsplit(": ", 1)[0] for d in details if d.endswith((": pass", ": fail")))
    )


def check_outcome(record, check):
    if not record or (record.get("score") or {}).get("status") != "scored":
        return "unknown"
    score = record["score"]
    if "failed_checks" not in score or score["failed_checks"] is None:
        return "unknown"
    return "fail" if check in names(score["failed_checks"]) else "pass"


def annotation(task, check):
    """Human audit annotations; confidence is about the stated mechanism, not causality."""
    if task in {"E01", "E05"}:
        return (
            "C7",
            "C9",
            "high",
            "Underspecified JSON contract and literal/type gates; "
            "see report check-by-check review.",
            "No; clarify benchmark schema first.",
        )
    if task == "E04":
        if check == "version_constraints":
            return (
                "C1",
                "C7",
                "high",
                "A states DESeq2 1.50.0 vs frozen 1.50.2; B corrects it without MCP.",
                "Metadata may help; effect untested.",
            )
        return (
            "C7",
            "C1;C9",
            "high",
            "Object/list/key type differs from hidden contract; "
            "A also misstates dependency field and minimum.",
            "Schema is outside MCP.",
        )
    if task == "D01":
        return (
            "C7",
            "C9",
            "high",
            "A recommends utils, outside the two-candidate allowlist; "
            "not proof that utils is an invalid practical alternative.",
            "B uses MCP and accepted termr; response-level attribution unknown.",
        )
    if task == "D02":
        return (
            "C7",
            "C1;C9",
            "high",
            "A uses httptest2 1.1.0 vs 1.2.2 and lacks httr2_specific; "
            "B chooses httptest, absent from candidate allowlist.",
            "Selection guidance may help; do not optimize to hidden allowlist.",
        )
    if task == "D03":
        return (
            "C1",
            "C7",
            "high",
            "pointblank 0.12.2 vs frozen 0.12.4; URL check also gates on version.",
            "get_package may help; effect untested.",
        )
    if task == "H10":
        return (
            "C6",
            "C9",
            "high",
            "B computes fmi=0.30 for zero total variance; "
            "oracle and task convention require 0.00. No MCP call.",
            "No demonstrated metadata remedy for numerical branch.",
        )
    return ("C9", "", "low", "Insufficient evidence.", "Unknown")


def failure_rows(records, run_prefix, tools):
    rows = []
    for task in sorted({r["task"] for r in records}):
        subset = [r for r in records if r["task"] == task]
        pair = {r["mode"]: r for r in subset}
        a, b = pair.get("without-mcp"), pair.get("with-mcp")
        for check in check_catalog(task, subset):
            sa, sb = check_outcome(a, check), check_outcome(b, check)
            failed = sa == "fail" or sb == "fail"
            cause, secondary, confidence, observed, remedy = (
                annotation(task, check)
                if failed
                else (
                    None,
                    None,
                    None,
                    "Saved scorer reports pass in both observed conditions.",
                    None,
                )
            )
            rows.append(
                {
                    "run_id": records[0]["run_id"],
                    "task": task,
                    "row_type": "scorer_check",
                    "check_id": check,
                    "trial_a": a["trial_id"] if a else None,
                    "trial_b": b["trial_id"] if b else None,
                    "result_a": sa,
                    "result_b": sb,
                    "failed_trials": ";".join(
                        r["trial_id"] for r in subset if check_outcome(r, check) == "fail"
                    ),
                    "primary_cause": cause,
                    "secondary_causes": secondary,
                    "confidence": confidence,
                    "evidence_level": "observed" if failed else None,
                    "observed": observed,
                    "mcp_remedy": remedy,
                    "additional_verification": "See report; no score correction performed.",
                    "evidence": ";".join(
                        f"{run_prefix}/{r['trial_id']}/result.json#$.score" for r in subset
                    ),
                    "artifact_evidence": ";".join(
                        f"{run_prefix}/{r['trial_id']}/artifacts/"
                        + (
                            "solution.R"
                            if task.startswith("H")
                            or task in {"E02", "E03"}
                            or task.startswith(("B", "C"))
                            else "answer.json"
                        )
                        for r in subset
                    ),
                }
            )
    for call in tools:
        if call["status"] == "error":
            rows.append(
                {
                    "run_id": call["run_id"],
                    "task": call["task"],
                    "row_type": "mcp_error",
                    "check_id": f"mcp_call_{call['sequence']}:{call['error_code']}",
                    "trial_a": None,
                    "trial_b": call["trial_id"],
                    "result_a": "not_applicable",
                    "result_b": "error",
                    "failed_trials": call["trial_id"],
                    "primary_cause": "C9",
                    "secondary_causes": "C3;C4;C5 (hypotheses)",
                    "confidence": "low",
                    "evidence_level": "observed_error_unknown_cause",
                    "observed": "docs_not_found observed; alias, arguments and body unavailable.",
                    "mcp_remedy": "Unverified; alias guidance may reduce failures.",
                    "additional_verification": (
                        "Retain redacted alias/offset and bounded result facts."
                    ),
                    "evidence": call["event_evidence"] + ";" + (call["telemetry_evidence"] or ""),
                    "artifact_evidence": None,
                }
            )
    return rows


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            # Keep numeric values numeric; protect text for spreadsheet consumers.
            writer.writerow(
                {
                    k: "'" + v
                    if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@"))
                    else v
                    for k, v in row.items()
                }
            )


def rescore_json(records, run):
    """Separate re-evaluation, never repaired/normalized inputs or replacement scores."""
    from benchmarks.codex_r import knowledge_pilot

    def forbid_executor(*args, **kwargs):
        raise AssertionError("Only existing JSON scorers are permitted in this audit")

    rows = []
    for record in records:
        if record["task"] not in {"D01", "D02", "D03", "E01", "E04", "E05"}:
            continue
        score = knowledge_pilot.score(
            record["task"],
            run / record["trial_id"] / "artifacts",
            image="unused-json-only",
            executor=forbid_executor,
        )
        fields = ("status", "passed", "total", "failed_checks", "artifacts")
        rows.append(
            {
                "trial_id": record["trial_id"],
                "original": {key: record["score"].get(key) for key in fields},
                "re_evaluated": {key: score.get(key) for key in fields},
            }
        )
    return {
        "type": "separate_current_json_scorer_re_evaluation",
        "historical_python_scorer_hash_recorded": False,
        "current_scorer_source_sha256": hashlib.sha256(
            (ROOT / "knowledge_pilot.py").read_bytes()
        ).hexdigest(),
        "normalized_or_corrected_inputs": False,
        "trials": rows,
        "all_match": all(row["original"] == row["re_evaluated"] for row in rows),
    }


def historical_input_matches(experiment):
    checks = {}
    for suite in ("hard", "knowledge_pilot"):
        directory = ROOT / suite
        manifest = read_json(directory / "manifest.json")
        tasks = {task["id"]: task for task in manifest["tasks"]}
        for task_id, expected in experiment.get("task_inputs_sha256", {}).items():
            if task_id not in tasks:
                continue
            task = tasks[task_id]
            files = {task["spec"]: expected["spec"]}
            source_by_target = {
                item["target"]: item["source"] for item in task.get("public_files", [])
            }
            for target, digest in expected["inputs"].items():
                files[source_by_target.get(target, target)] = digest
            for name, digest in files.items():
                path = directory / name
                checks[f"{suite}/{name}"] = (
                    path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
                )
    return checks


def analyze(run, output, *, re_evaluate_json=False):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output == run or output.is_relative_to(run) or run.is_relative_to(output):
        raise ValueError("Audit output must be separate from the source run")
    before = inventory(run)
    experiment = read_json(run / "experiment.json")
    input_matches = historical_input_matches(experiment)
    summary = read_json(run / "results.json")
    records, tools, integrity = [], [], []
    integrity.extend(f"source_input_hash:{name}" for name, ok in input_matches.items() if not ok)
    prefix = run.relative_to(REPO).as_posix() if run.is_relative_to(REPO) else run.name
    planned_ids = [p["trial_id"] for p in experiment["trial_plan"]]
    summary_ids = [r["trial_id"] for r in summary]
    if len(set(summary_ids)) != len(summary_ids) or set(summary_ids) != set(planned_ids):
        integrity.append("duplicate_or_missing_summary_trials")
    for planned in experiment["trial_plan"]:
        trial = planned["trial_id"]
        path = run / trial / "result.json"
        if not path.is_file():
            integrity.append(f"{trial}:missing_result")
            continue
        record = read_json(path)
        records.append(record)
        saved = next((r for r in summary if r["trial_id"] == trial), {})
        for key in (
            "run_id",
            "trial_id",
            "task",
            "mode",
            "model",
            "effort",
            "instructions",
            "score",
            "mcp_usage",
            "mcp_server_audit",
        ):
            if record.get(key) != saved.get(key):
                integrity.append(f"{trial}:summary_diff:{key}")
        for key in ("task", "mode", "repetition"):
            if record.get(key) != planned.get(key):
                integrity.append(f"{trial}:plan_diff:{key}")
        for key in ("run_id", "model", "effort", "instructions", "images", "timeout_seconds"):
            if record.get(key) != experiment.get(key):
                integrity.append(f"{trial}:configuration_diff:{key}")
        for filename, expected in (record.get("score") or {}).get("artifacts", {}).items():
            artifact = path.parent / "artifacts" / filename
            if (
                not artifact.is_file()
                or hashlib.sha256(artifact.read_bytes()).hexdigest() != expected
            ):
                integrity.append(f"{trial}:artifact_hash:{filename}")
        events_path = path.parent / "events.json"
        events = read_json(events_path) if events_path.is_file() else []
        if not events_path.is_file():
            integrity.append(f"{trial}:missing_events")
        rows, aligned = tool_rows(record, events, f"{prefix}/{trial}")
        tools.extend(rows)
        if not aligned:
            integrity.append(f"{trial}:event_telemetry_order_not_matched")
        if len(rows) != (record.get("mcp_usage") or {}).get("calls"):
            integrity.append(f"{trial}:event_call_count_diff")
        prompts = [
            part.get("text")
            for event in events
            if isinstance(event, dict)
            and isinstance(event.get("item"), dict)
            and event["item"].get("role") == "user"
            for part in event["item"].get("content", [])
            if isinstance(part, dict)
        ]
        spec_hash = experiment.get("task_inputs_sha256", {}).get(record["task"], {}).get("spec")
        if spec_hash and not any(
            isinstance(text, str) and hashlib.sha256(text.encode()).hexdigest() == spec_hash
            for text in prompts
        ):
            integrity.append(f"{trial}:event_prompt_hash_not_matched")
        checks = check_catalog(record["task"], [record])
        score = record.get("score") or {}
        if score.get("status") == "scored" and len(checks) != score.get("total"):
            integrity.append(f"{trial}:check_catalog_count_diff")
    scores = {}
    for mode in ("without-mcp", "with-mcp"):
        trials = [r for r in records if r["mode"] == mode]
        valid = [
            r
            for r in trials
            if (r.get("score") or {}).get("status") == "scored"
            and isinstance(r["score"].get("passed"), int)
        ]
        scores[mode] = {
            "trials": len(trials),
            "scored": len(valid),
            "passed": sum(r["score"]["passed"] for r in valid),
            "total": sum(r["score"]["total"] for r in valid),
            "fully_correct": sum(r["score"].get("fully_correct") is True for r in valid),
        }
    pairs = []
    for task in experiment["tasks"]:
        pair = {r["mode"]: r for r in records if r["task"] == task}
        a, b = pair.get("without-mcp"), pair.get("with-mcp")
        if not a or not b:
            integrity.append(f"{task}:missing_pair")
            continue
        sa, sb = a.get("score") or {}, b.get("score") or {}
        ap, bp = sa.get("passed"), sb.get("passed")
        delta = bp - ap if isinstance(ap, int) and isinstance(bp, int) else None
        audit = b.get("mcp_server_audit") or {}
        pairs.append(
            {
                "task": task,
                "a": ap,
                "b": bp,
                "total": sa.get("total"),
                "delta": delta,
                "mcp_available": "configured_list_requested"
                if audit.get("list_tools_requests", 0) > 0
                else "unknown",
                "mcp_calls": (b.get("mcp_usage") or {}).get("calls"),
                "mcp_tools": (b.get("mcp_usage") or {}).get("calls_by_tool"),
                "trial_a": a["trial_id"],
                "trial_b": b["trial_id"],
            }
        )
    catalog = failure_rows(records, prefix, tools)
    data = {
        "run_id": experiment["run_id"],
        "scores": scores,
        "pairs": pairs,
        "integrity_findings": integrity,
        "tool_count": len(tools),
        "tool_names": dict(Counter(r["tool"] for r in tools)),
        "tool_statuses": dict(Counter(r["status"] for r in tools)),
        "repeat_kinds": dict(Counter(r["repeated"] for r in tools)),
        "result_bytes_recorded": sum(r["response_bytes_recorded"] or 0 for r in tools),
        "audit_list_requests_b": sum(
            (r.get("mcp_server_audit") or {}).get("list_tools_requests", 0)
            for r in records
            if r["mode"] == "with-mcp"
        ),
        "server_call_requests_b": sum(
            (r.get("mcp_server_audit") or {}).get("call_tool_requests", 0)
            for r in records
            if r["mode"] == "with-mcp"
        ),
        "scored_check_rows": sum(row["row_type"] == "scorer_check" for row in catalog),
        "source_run_inventory_sha256": before,
        "historical_public_inputs_match": input_matches,
        "inputs_unchanged": inventory(run) == before,
        "source_tree_sha256": tree_digest(REPO / "src", ".py"),
        "hard_verifier_sha256": tree_digest(ROOT / "hard/verifier", ".R"),
        "pilot_verifier_sha256": tree_digest(ROOT / "knowledge_pilot/verifier", ".R"),
        "interpretation": "Original scores; null stays unknown; bytes are not API usage.",
    }
    output.mkdir(parents=True, exist_ok=True)
    if re_evaluate_json:
        (output / "baseline_json_rescore.json").write_text(
            json.dumps(rescore_json(records, run), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    write_csv(output / "baseline_failure_matrix.csv", catalog)
    write_csv(output / "baseline_tool_calls.csv", tools)
    (output / "baseline_audit_data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "| Task | Score A | Score B | Delta | MCP available | MCP calls | MCP tools | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in pairs:
        delta = p["delta"]
        result = (
            "unknown"
            if delta is None
            else ("B higher" if delta > 0 else "B lower" if delta < 0 else "equal")
        )
        lines.append(
            f"| {p['task']} | {p['a']}/{p['total']} | {p['b']}/{p['total']} | "
            f"{delta} | {p['mcp_available']} | {p['mcp_calls']} | "
            f"{json.dumps(p['mcp_tools'], sort_keys=True)} | {result} |"
        )
    (output / "baseline_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=ROOT / "results" / RUN_ID)
    parser.add_argument("--output", type=Path, default=ROOT / "reports")
    parser.add_argument("--rescore-json", action="store_true")
    args = parser.parse_args()
    result = analyze(args.run, args.output, re_evaluate_json=args.rescore_json)
    print(json.dumps({key: result[key] for key in ("scores", "tool_count", "integrity_findings")}))


if __name__ == "__main__":
    main()
