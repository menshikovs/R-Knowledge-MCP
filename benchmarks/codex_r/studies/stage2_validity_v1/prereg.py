"""Render PREREGISTRATION.md from experiment_manifest.json (single source of truth)."""

from __future__ import annotations


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def render(m: dict) -> str:
    arms = _table(
        ["arm", "label", "MCP available", "encouragement sentence", "instruction SHA-256"],
        [
            [
                key,
                a["label"],
                "yes" if a["mcp_available"] else "no",
                "yes" if a["encouraged"] else "no",
                f"`{a['instructions_sha256'][:16]}...`",
            ]
            for key, a in m["arms"].items()
        ],
    )
    pilot = _table(
        ["task", "role", "suite", "scorer", "pinned files (SHA-256 prefix)"],
        [
            [
                t["task"],
                t["role"],
                t["suite"],
                t["scorer"],
                "<br>".join(f"`{n.split('/')[-1]}` {h[:12]}" for n, h in t["files"].items()),
            ]
            for t in m["pilot_tasks"]
        ],
    )
    designs = _table(
        ["design", "tasks", "repetitions", "arms", "trials"],
        [
            [
                name,
                d["tasks"],
                d["repetitions"],
                "".join(d["arms"]),
                d["tasks"] * d["repetitions"] * len(d["arms"]),
            ]
            for name, d in m["designs"].items()
        ],
    )
    eligibility = "\n".join(f"* {item}" for item in m["confirmatory_task_rule"]["eligibility"])
    violations = ", ".join(f"`{c}`" for c in m["exclusions"]["invalidating_violations"])
    exploratory = "\n".join(f"* {item}" for item in m["exploratory_analyses"])
    tools = ", ".join(f"`{t}`" for t in m["tools"]["mcp"]["tools"])
    return f"""# Preregistration - {m["study_id"]} v{m["version"]}

> Generated from `experiment_manifest.json` (`python -m benchmarks.codex_r.studies.stage2_validity_v1.cli render-prereg`).
> **Status: {m["status"]}.** Core manifest SHA-256 `{m["core_sha256"]}`.
> This document becomes binding only when the final manifest and this rendering are committed as the
> registration commit and the randomization seed is derived from that commit. Until then every
> value is a proposal. No confirmatory run may start before registration.

## 1. Question and hypothesis

{m["research_question"]}

* H0: {m["primary_hypothesis"]["H0"]}.
* H1: {m["primary_hypothesis"]["H1"]}.
* A negative or inconclusive result is a valid outcome and will be reported as such.

## 2. Estimand and outcome

* Primary estimand: {m["primary_estimand"]}
* Primary metric: {m["primary_outcome"]["metric"]}.
* Aggregation: {m["primary_outcome"]["aggregation"]}.
* Candidate failures are scored {m["primary_outcome"]["candidate_failure"]}; missing outcomes: {", ".join(m["primary_outcome"]["missing"])}.
* Secondary outcomes: {", ".join(m["secondary_outcomes"])}.

## 3. Arms

{arms}

Arms A and B receive byte-identical instructions (SHA-256 `{m["shared_instruction_sha256"]}`); arm C adds exactly
one sentence: *"{m["encouragement_sentence"]}"* The MCP tool descriptions in B and C are part of the treatment.
MCP tools ({len(m["tools"]["mcp"]["tools"])}): {tools}. Surface digest `{m["tools"]["mcp"]["surface_sha256"][:16]}...`.

Model: `{m["model"]["identity"]}`, effort `{m["model"]["effort"]}` ({m["model"]["note"]}).
Every other executor tool, image, limit and the scorer are identical across arms.

## 4. Information channels (egress policy)

* All arms: {m["egress_policy"]["all_arms"]}.
* Allowed destinations: arm A {m["egress_policy"]["arm_A"]}, arms B/C {m["egress_policy"]["arms_B_C"]}.
* Violations: {", ".join(f"`{c}`" for c in m["egress_policy"]["violation_codes"])}.
* Implementation status: **{m["egress_policy"]["implementation_status"]}** - a confirmatory run is not allowed until this is implemented and tested.

## 5. Tasks

Pilot tasks (feasibility only; not an effect test):

{pilot}

Confirmatory task rule (minimum {m["confirmatory_task_rule"]["minimum_tasks"]} tasks; tasks meeting it today: **{m["confirmatory_task_rule"]["current_eligible_tasks"]}**):

{eligibility}

## 6. Design and randomization

{designs}

* Algorithm `{m["randomization"]["algorithm"]}`; block = {m["randomization"]["block"]}; every arm once per block, in a seeded random order; blocks shuffled globally; fresh context per trial.
* Seed: {m["randomization"]["seed_rule"]} (not yet derived).

## 7. Analysis

* Primary: {m["analysis"]["primary_test"]}; interval: {m["analysis"]["interval"]}; alpha {m["analysis"]["alpha"]}.
* Secondary family: {m["analysis"]["secondary_correction"]}.
* Monte Carlo permutations {m["analysis"]["monte_carlo_permutations"]}; bootstrap resamples {m["analysis"]["bootstrap_resamples"]}.
* Full plan: `{m["analysis"]["plan"]}`.

## 8. Exclusions, failures, stopping, budget

* Trials with an invalidating protocol violation are excluded from the primary analysis, reported, and bounded by sensitivity analyses: {violations}.
* Failures: {m["failure_handling"]["retry_allowance"]}. {m["failure_handling"]["never"]}.
* Stopping: {m["stopping"]}.
* Budget: model spend limit `{m["budget"]["model_spend_limit"]}` - {m["budget"]["status"]}. Timeout per trial {m["budget"]["timeout_seconds_per_trial"]} s.
* Scorers: {", ".join(m["scorers"]["versions"])}; module digests are in the manifest. Historical results are never rescored with a new scorer.

## 9. Exploratory analyses (no confirmatory claims)

{exploratory}
"""
