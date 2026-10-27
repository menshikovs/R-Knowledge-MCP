"""Deterministic offline comparison of D01 answers, pinned facts and observed evidence."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from benchmarks.codex_r import knowledge_pilot
from benchmarks.codex_r.telemetry import schema as telemetry_schema

HISTORICAL_RUNS = {
    "enabled": "20261027T080622Z-16d73779",
    "disabled": "20261027T080923Z-f0bf06a8",
}
MAX_JSON_BYTES = 2 << 20
MAX_JSONL_BYTES = 64 << 20
MAX_JSONL_LINES = 200_000
MAX_JSONL_LINE_BYTES = 1 << 20
OFFICIAL_HOSTS = frozenset(
    {"cran.r-project.org", "stat.ethz.ch", "bioconductor.org", "docs.posit.co", "docs.rstudio.com"}
)


def _read_json(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("audit_input_missing_symlink_or_oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_url(value):
    if not isinstance(value, str) or len(value) > 512 or "?" in value or "#" in value:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return None
        if parts.port is not None:
            return None
    except ValueError:
        return None
    host = parts.hostname.casefold()
    if host not in OFFICIAL_HOSTS or not parts.path.startswith("/"):
        return None
    return f"https://{host}{parts.path}"


def _read_telemetry(path: Path):
    if not path.is_file() or path.is_symlink():
        return []
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise ValueError("audit_telemetry_limit_exceeded")
    events = []
    with path.open(encoding="utf-8") as stream:
        for index in range(MAX_JSONL_LINES + 1):
            line = stream.readline(MAX_JSONL_LINE_BYTES + 1)
            if not line:
                break
            if index >= MAX_JSONL_LINES or len(line.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
                raise ValueError("audit_telemetry_limit_exceeded")
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and not telemetry_schema.validate_event(event):
                events.append(event)
    return events


def _answer_claims(answer):
    recommendations = answer.get("recommendations") if isinstance(answer, dict) else None
    if not isinstance(recommendations, list):
        return []
    claims = []
    for item in recommendations[:16]:
        if not isinstance(item, dict):
            continue
        claims.append(
            {
                "package": item.get("package")
                if isinstance(item.get("package"), str)
                and telemetry_schema.PACKAGE.fullmatch(item["package"])
                else None,
                "stated_version": item.get("version")
                if isinstance(item.get("version"), str)
                and telemetry_schema.VERSION.fullmatch(item["version"])
                else None,
                "source_url": _normalize_url(item.get("source_url")),
                "source_url_present": isinstance(item.get("source_url"), str),
                "documentation_url": _normalize_url(item.get("documentation_url")),
                "documentation_url_present": isinstance(item.get("documentation_url"), str),
                "feature_ids": [
                    value
                    for value in item.get("feature_ids", [])[:32]
                    if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
                ]
                if isinstance(item.get("feature_ids"), list)
                else [],
                "caveat_ids": [
                    value
                    for value in item.get("caveat_ids", [])[:32]
                    if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
                ]
                if isinstance(item.get("caveat_ids"), list)
                else [],
            }
        )
    return claims


def _audit_claim(claim, pinned, result, events):
    package = claim["package"]
    reference = pinned.get(package) if package else None
    reference_version = (
        reference.get("version")
        if isinstance(reference, dict)
        and isinstance(reference.get("version"), str)
        and telemetry_schema.VERSION.fullmatch(reference["version"])
        else None
    )
    stated = claim["stated_version"]
    version_match = (
        None
        if not isinstance(reference_version, str) or not isinstance(stated, str)
        else stated == reference_version
    )
    evidence = [
        event
        for event in events
        if event.get("event_type") == "agent.evidence.observed"
        and event.get("trial_id") == result.get("trial_id")
        and event.get("package") == package
    ]
    observed_versions = sorted(
        {
            event["package_version"]
            for event in evidence
            if isinstance(event.get("package_version"), str)
        }
    )
    if observed_versions:
        evidence_status = (
            "supported_by_observed_tool_result"
            if stated in observed_versions
            else "contradicted_by_observed_tool_result"
        )
    elif (result.get("mcp_usage") or {}).get("calls", 0) or result.get("mcp_usage", {}).get(
        "item_types", {}
    ).get("command_execution", 0):
        evidence_status = "insufficient_observability"
    else:
        evidence_status = "no_observed_tool_evidence"

    access_urls = {
        _normalize_url(event.get("source_url"))
        for event in events
        if event.get("event_type") == "agent.url.mentioned"
        and event.get("trial_id") == result.get("trial_id")
        and event.get("source_access_status") == "mcp_response_observed"
    }
    access_urls.discard(None)
    citations = []
    for role, url in (
        ("source", claim.get("source_url")),
        ("documentation", claim.get("documentation_url")),
    ):
        normalized = _normalize_url(url)
        url_present = claim.get(f"{role}_url_present", False)
        citations.append(
            {
                "role": role,
                "url_present_in_final_answer": url_present,
                "url": normalized,
                "matching_source_access_observed": bool(normalized and normalized in access_urls),
                "source_access_status": (
                    "matching_source_access_observed"
                    if normalized and normalized in access_urls
                    else "source_access_observability_unknown"
                    if url_present
                    else "not_present"
                ),
            }
        )
    reference_urls = reference or {}
    reference_source_url = _normalize_url(reference_urls.get("source_url"))
    reference_documentation_url = _normalize_url(reference_urls.get("documentation_url"))
    return {
        **claim,
        "pinned_version": reference_version,
        "reference_version_match": version_match,
        "reference_source_url": reference_source_url,
        "reference_documentation_url": reference_documentation_url,
        "source_identity_matches_reference": bool(
            claim.get("source_url")
            and reference_source_url
            and _normalize_url(claim.get("source_url")) == reference_source_url
        ),
        "documentation_identity_matches_reference": bool(
            claim.get("documentation_url")
            and reference_documentation_url
            and _normalize_url(claim.get("documentation_url")) == reference_documentation_url
        ),
        "observed_tool_versions_for_package": observed_versions,
        "evidence_consistency": evidence_status,
        "citations": citations,
    }


def audit_run(results_root, run_id, pinned_candidates):
    if not isinstance(run_id, str) or not telemetry_schema.ID.fullmatch(run_id):
        raise ValueError("invalid_audit_run_id")
    root = Path(results_root)
    run_dir = root / run_id
    if run_dir.is_symlink():
        raise ValueError("audit_run_directory_must_not_be_symlink")
    manifest = _read_json(run_dir / "experiment.json")
    records = _read_json(run_dir / "results.json")
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise ValueError("d01_audit_requires_one_saved_trial")
    result = records[0]
    if result.get("run_id") != run_id or result.get("task") != "D01":
        raise ValueError("d01_audit_identity_mismatch")
    trial_id = result.get("trial_id")
    if not isinstance(trial_id, str) or not telemetry_schema.ID.fullmatch(trial_id):
        raise ValueError("invalid_audit_trial_id")
    trial_dir = run_dir / trial_id
    if trial_dir.is_symlink():
        raise ValueError("audit_trial_directory_must_not_be_symlink")
    artifacts_dir = trial_dir / "artifacts"
    if artifacts_dir.is_symlink():
        raise ValueError("audit_artifacts_directory_must_not_be_symlink")
    answer = _read_json(artifacts_dir / "answer.json")
    events = [
        event
        for event in _read_telemetry(run_dir / "telemetry.jsonl")
        if event.get("run_id") == run_id
    ]
    usage = result.get("mcp_usage") or {}
    server_calls = (result.get("mcp_telemetry") or {}).get("calls") or []
    event_counts = Counter(
        (event.get("source", "unknown"), event.get("event_type", "unknown")) for event in events
    )
    error_codes = Counter(
        code
        for call in server_calls
        for code in (call.get("error_codes") or [])
        if isinstance(code, str)
    )
    call_tools = Counter(
        call.get("tool_name") for call in server_calls if isinstance(call.get("tool_name"), str)
    )
    task_id = "D01"
    mcp_manifest = manifest.get("mcp_server") or {}
    registered = mcp_manifest.get("registered_tools_by_task", {}).get(
        task_id, mcp_manifest.get("registered_tools", [])
    )
    allowed = mcp_manifest.get("allowed_tools_by_task", {}).get(
        task_id, mcp_manifest.get("allowed_tools", [])
    )
    discovery_policy = manifest.get("function_discovery_policy", "unknown")
    configuration = {
        "model": manifest.get("model"),
        "effort": manifest.get("effort"),
        "instructions": manifest.get("instructions"),
        "mode": result.get("mode"),
        "function_discovery_policy": discovery_policy,
        "registered_tool_count": len(registered) if isinstance(registered, list) else None,
        "registered_tools": sorted(registered) if isinstance(registered, list) else None,
        "policy_allowed_tools": sorted(allowed) if isinstance(allowed, list) else None,
        "remote_discovery_status": "unknown",
        "remote_discovered_tools": None,
        "session_config_echo_status": (
            "response_echo_observed"
            if any(event.get("event_type") == "mcp.exposure.response" for event in events)
            else "not_recorded_in_schema_1.0"
            if events and all(event.get("schema_version") == "1.0" for event in events)
            else "not_observed"
        ),
    }
    pins = pinned_candidates.get(task_id, {})
    claims = [_audit_claim(claim, pins, result, events) for claim in _answer_claims(answer)]
    return {
        "run_id": run_id,
        "trial_id": result.get("trial_id"),
        "condition": discovery_policy,
        "configuration": configuration,
        "status": result.get("status"),
        "score": {
            "passed": (result.get("score") or {}).get("passed"),
            "total": (result.get("score") or {}).get("total"),
            "failed_checks": (result.get("score") or {}).get("failed_checks", []),
        },
        "mcp_calls": {
            "client_observed": usage.get("calls"),
            "client_by_tool": usage.get("calls_by_tool", {}),
            "server_observed": len(server_calls),
            "server_by_tool": dict(sorted(call_tools.items())),
            "server_list_tools_requests": (result.get("mcp_server_audit") or {}).get(
                "list_tools_requests"
            ),
            "canonical_count": result.get("mcp_metrics", {})
            .get("overall", {})
            .get("mcp_calls_attempted", usage.get("calls")),
            "raw_lifecycle_observations": {
                event_type: sum(
                    count for (source, kind), count in event_counts.items() if kind == event_type
                )
                for event_type in ("mcp.tool.started", "mcp.tool.completed", "mcp.tool.failed")
            },
            "raw_lifecycle_by_source": {
                source: {
                    event_type: event_counts.get((source, event_type), 0)
                    for event_type in (
                        "mcp.tool.started",
                        "mcp.tool.completed",
                        "mcp.tool.failed",
                    )
                }
                for source in ("agent_stream", "mcp_server")
            },
            "correlation_confidence": (
                "ordinal_unconfirmed" if server_calls else "not_applicable_no_server_calls"
            ),
            "errors_by_code": dict(sorted(error_codes.items())),
        },
        "agent_items_completed_by_type": usage.get("item_types", {}),
        "answer_claims": claims,
        "observed_agent_evidence_count": sum(
            event.get("event_type") == "agent.evidence.observed"
            and event.get("trial_id") == result.get("trial_id")
            for event in events
        ),
        "telemetry_schema_versions": sorted(
            {event.get("schema_version") for event in events if event.get("schema_version")}
        ),
    }


def build_audit(results_root, run_ids=HISTORICAL_RUNS):
    pinned = _read_json(knowledge_pilot.PILOT / "verifier" / "candidates.json")
    runs = {label: audit_run(results_root, run_id, pinned) for label, run_id in run_ids.items()}
    enabled = runs["enabled"]
    disabled = runs["disabled"]
    return {
        "report": "p1d_evidence_audit",
        "schema_version": 1,
        "historical_runs": runs,
        "comparison": {
            "registered_tool_catalogs_match": enabled["configuration"]["registered_tools"]
            == disabled["configuration"]["registered_tools"],
            "allowed_tool_difference": sorted(
                set(enabled["configuration"]["policy_allowed_tools"] or [])
                - set(disabled["configuration"]["policy_allowed_tools"] or [])
            ),
            "control_only_allowed_tools": sorted(
                set(disabled["configuration"]["policy_allowed_tools"] or [])
                - set(enabled["configuration"]["policy_allowed_tools"] or [])
            ),
            "matching_model_effort_instructions": all(
                enabled["configuration"][key] == disabled["configuration"][key]
                for key in ("model", "effort", "instructions", "mode")
            ),
            "causal_conclusion": "not_supported_by_one_trial_per_condition",
        },
    }


def render_markdown(report):
    runs = report["historical_runs"]
    lines = [
        "# P1-D D01 evidence access audit",
        "",
        "Historical saved runs only. No source artifacts or scores were modified.",
        "",
        (
            "| Condition | Run ID | Discovery | Score | Client MCP calls | Server MCP calls | "
            "`list_package_functions` | Final package/version | Evidence status |"
        ),
        "|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for label in ("enabled", "disabled"):
        run = runs[label]
        claims = run["answer_claims"]
        claim = claims[0] if claims else {}
        tool_count = run["mcp_calls"]["client_by_tool"].get("list_package_functions", 0)
        row = (
            "| {label} | `{run_id}` | {discovery} | {score} | {client} | {server} | "
            "{function_calls} | {package} {version} | {evidence} |"
        )
        lines.append(
            row.format(
                label=label,
                run_id=run["run_id"],
                discovery=run["configuration"]["function_discovery_policy"],
                score=f"{run['score']['passed']}/{run['score']['total']}",
                client=run["mcp_calls"]["client_observed"],
                server=run["mcp_calls"]["server_observed"],
                function_calls=tool_count,
                package=claim.get("package", "unknown"),
                version=claim.get("stated_version", "unknown"),
                evidence=claim.get("evidence_consistency", "unavailable"),
            )
        )
    lines.extend(
        [
            "",
            "## Findings",
            "",
            (
                "- The treatment configured 13 tools; the server registered 16. The control "
                "configured 12 tools with the same 16-name registry. `list_package_functions` "
                "was configured only in the enabled run, but its observed call count was zero."
            ),
            (
                "- The enabled answer selected `termr 0.1.0` against pinned `termr 1.0.1`; "
                "the source identity matches after host-case normalization, while the "
                "documentation identity differs from the pinned URL. Its recorded scorer "
                "result is 2/4."
            ),
            (
                "- The disabled answer selected `climenu 0.2.0`, matching the pinned version "
                "and documentation identity. Its source is a version-specific official CRAN "
                "tarball URL, not the pinned package-page identity. Its recorded scorer "
                "result is 4/4."
            ),
            (
                "- Historical response-level MCP records do not expose package versions and "
                "source/documentation URLs delivered to the agent. The enabled run has no "
                "observed MCP call; command execution and citations do not establish external "
                "page access. Source-access conclusions remain unknown."
            ),
            (
                "- The optional session-configuration echo was added in telemetry schema 1.1 "
                "and was not present in the historical schema 1.0 records. Historical exposure "
                "is confirmed only from saved request/configuration metadata."
            ),
            (
                "- Disabled raw counts are 15 client starts, 11 client successes + 4 client "
                "errors, and 11 server successes + 4 server errors: 15 attempts with 22 "
                "terminal successes and 8 terminal errors across two sources. The canonical "
                "count remains 15; client/server correlation is ordinal and unconfirmed."
            ),
            (
                "- One observation per condition is exploratory and does not support a causal "
                "claim about discovery or scorer quality."
            ),
            "",
            "## Access classification",
            "",
        ]
    )
    for label in ("enabled", "disabled"):
        run = runs[label]
        for claim in run["answer_claims"]:
            for citation in claim["citations"]:
                lines.append(
                    f"- {label} `{claim['package']}` {citation['role']} URL present: "
                    f"{str(citation['url_present_in_final_answer']).lower()}; access: "
                    f"`{citation['source_access_status']}`."
                )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path(__file__).with_name("results"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("reports"))
    args = parser.parse_args(argv)
    report = build_audit(args.results_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "p1d_evidence_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "p1d_evidence_audit.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
