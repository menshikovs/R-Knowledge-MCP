"""Preregistered analysis of paired, repeated, task-clustered trials (stage2_validity_v1).

Estimand: the average, over the tasks of the preregistered population, of the within-task mean
difference in score between two arms, for example B - A = the effect of *making R-Knowledge-MCP
available* (assignment-based, intention-to-treat: never conditioned on whether a tool was called).
Tasks are the units of inference; repetitions of one task are not independent samples.

Statistic   T = mean over tasks of ( mean over complete blocks of  score_x - score_y ).
            A block is one (task, repetition) in which both arms produced an analysable value.
Test        Task-level sign-flip test (primary): the sign of each task's mean difference is flipped,
            because tasks, not repetitions, are the units of inference. Exact enumeration up to
            2**EXACT_LIMIT tasks, otherwise Monte Carlo with a recorded seed. A block-level flip
            (the sharp null "no effect in any task", which is what the within-block randomization
            justifies) is reported as a sensitivity analysis: it over-rejects when task effects
            are heterogeneous and repetitions are many.
Interval    Two-stage percentile bootstrap: resample tasks with replacement, then blocks within each
            selected task (captures task heterogeneity and repetition variability).
Multiplicity The primary contrast has its own alpha. The secondary family is Holm-adjusted.
Everything is pure Python and seeded, so results regenerate byte for byte from the same data.
"""

from __future__ import annotations

import math
import statistics

from .design import seeded
from .records import analysis_value

EXACT_LIMIT = 16
ALPHA = 0.05


def outcome_value(record: dict, outcome: str = "score", exclude_invalidating: bool = True):
    value, reason = analysis_value(record, exclude_invalidating)
    if value is None or outcome == "score":
        return value, reason
    if outcome == "fully_correct":
        return (1.0 if record["outcome_kind"] == "scored" and value == 1.0 else 0.0), reason
    raise ValueError(f"unknown outcome {outcome!r}")


def block_differences(
    records: list[dict],
    arm_x: str,
    arm_y: str,
    outcome: str = "score",
    exclude_invalidating: bool = True,
) -> tuple[dict[str, list[float]], dict]:
    """task -> list of block differences (x - y), plus a ledger of every dropped block and why."""
    cells: dict[tuple[str, int], dict[str, tuple]] = {}
    for record in records:
        if record["arm"] in (arm_x, arm_y):
            cells.setdefault((record["task"], record["repetition"]), {})[record["arm"]] = (
                outcome_value(record, outcome, exclude_invalidating)
            )
    diffs: dict[str, list[float]] = {}
    ledger = {"blocks_planned": len(cells), "blocks_analysed": 0, "dropped": {}}
    for (task, _), pair in sorted(cells.items()):
        x, y = pair.get(arm_x, (None, "no_record")), pair.get(arm_y, (None, "no_record"))
        if x[0] is None or y[0] is None:
            reason = x[1] if x[0] is None else y[1]
            ledger["dropped"][reason] = ledger["dropped"].get(reason, 0) + 1
            continue
        diffs.setdefault(task, []).append(x[0] - y[0])
        ledger["blocks_analysed"] += 1
    return diffs, ledger


def statistic(diffs: dict[str, list[float]]) -> float | None:
    means = [sum(v) / len(v) for v in diffs.values() if v]
    return sum(means) / len(means) if means else None


def sign_flip_p(
    diffs: dict[str, list[float]], seed: int, n_perm: int = 19_999, unit: str = "task"
) -> dict:
    """Two-sided sign-flip p-value; exact for few units, else Monte Carlo (+1 corrected).

    unit="task"   flips the sign of each task's mean difference (PRIMARY). Tasks are the units of
                  inference, so repetitions of one task are not treated as independent samples.
    unit="block"  flips each (task, repetition) block: a test of the *sharp* null "no effect in any
                  task". With task-specific effects of mean zero it rejects more often as
                  repetitions grow (simulated type-I error 0.087-0.103 vs 0.040-0.047 at 40 tasks x
                  5 repetitions, see POWER_AND_BUDGET.md), so it is a sensitivity analysis only.
    """
    tasks = [v for v in diffs.values() if v]
    observed = statistic(diffs)
    if observed is None:
        return {"p": None, "method": "none", "unit": unit, "n_units": 0}
    if unit == "task":
        groups = [[sum(v) / len(v)] for v in tasks]
    elif unit == "block":
        groups = [list(v) for v in tasks]
    else:
        raise ValueError("unit must be 'task' or 'block'")
    flat = [(i, d) for i, g in enumerate(groups) for d in g]
    n = len(flat)

    def stat(signs) -> float:
        sums = [0.0] * len(groups)
        for (i, d), sign in zip(flat, signs, strict=True):
            sums[i] += sign * d
        return sum(sums[i] / len(groups[i]) for i in range(len(groups))) / len(groups)

    tol = 1e-12
    base = {"unit": unit, "n_units": n}
    if n <= EXACT_LIMIT:
        extreme = 0
        for mask in range(1 << n):
            signs = [1 if mask >> k & 1 else -1 for k in range(n)]
            extreme += abs(stat(signs)) >= abs(observed) - tol
        return {"p": extreme / (1 << n), "method": "exact", "n_permutations": 1 << n, **base}
    rng = seeded(seed, f"sign-flip-{unit}")
    extreme = sum(
        abs(stat([rng.choice((-1, 1)) for _ in range(n)])) >= abs(observed) - tol
        for _ in range(n_perm)
    )
    return {
        "p": (1 + extreme) / (1 + n_perm),
        "method": "monte_carlo",
        "n_permutations": n_perm,
        **base,
    }


def bootstrap_ci(
    diffs: dict[str, list[float]], seed: int, n_boot: int = 5000, level: float = 0.95
) -> dict:
    tasks = [v for v in diffs.values() if v]
    if not tasks:
        return {"low": None, "high": None, "n_boot": 0}
    rng = seeded(seed, "bootstrap")
    stats = []
    for _ in range(n_boot):
        means = []
        for _ in tasks:
            sample = rng.choice(tasks)
            means.append(sum(rng.choice(sample) for _ in sample) / len(sample))
        stats.append(sum(means) / len(means))
    stats.sort()
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    return {
        "low": stats[int(lo * (n_boot - 1))],
        "high": stats[math.ceil(hi * (n_boot - 1))],
        "level": level,
        "method": "two-stage percentile bootstrap (tasks, then blocks within task)",
        "n_boot": n_boot,
    }


def estimate(
    records: list[dict],
    arm_x: str,
    arm_y: str,
    seed: int,
    outcome: str = "score",
    exclude_invalidating: bool = True,
    n_perm: int = 19_999,
    n_boot: int = 5000,
) -> dict:
    diffs, ledger = block_differences(records, arm_x, arm_y, outcome, exclude_invalidating)
    task_effects = {t: sum(v) / len(v) for t, v in diffs.items() if v}
    point = statistic(diffs)
    test = sign_flip_p(diffs, seed, n_perm, unit="task")
    block_test = sign_flip_p(diffs, seed, min(n_perm, 4999), unit="block")
    sd = statistics.stdev(task_effects.values()) if len(task_effects) > 1 else None
    return {
        "contrast": f"{arm_x}-{arm_y}",
        "outcome": outcome,
        "estimate": point,
        "ci": bootstrap_ci(diffs, seed, n_boot),
        "p_value": test["p"],
        "test": test,
        "test_block_level_sharp_null": block_test,
        "n_tasks": len(task_effects),
        "task_effects": task_effects,
        "task_effect_sd": sd,
        "standardized_effect": (point / sd) if (sd and point is not None) else None,
        "ledger": ledger,
    }


def holm(p_values: dict[str, float | None]) -> dict[str, float | None]:
    items = sorted(((p, k) for k, p in p_values.items() if p is not None))
    adjusted, running, m = {}, 0.0, len(items)
    for rank, (p, key) in enumerate(items):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[key] = running
    return {k: adjusted.get(k) for k in p_values}


def sensitivity(records: list[dict], seed: int, arm_x: str = "B", arm_y: str = "A") -> dict:
    """Preregistered sensitivity analyses; none of them replaces the primary result."""
    base = estimate(records, arm_x, arm_y, seed, n_perm=4999, n_boot=1000)
    out: dict = {"primary_point_estimate": base["estimate"]}
    incl = estimate(
        records, arm_x, arm_y, seed, exclude_invalidating=False, n_perm=4999, n_boot=1000
    )
    out["include_protocol_violation_trials"] = incl["estimate"]

    # Bounds for missing outcomes: pessimistic for the treatment, then optimistic.
    def bounded(treat_missing_as: float, control_missing_as: float) -> float | None:
        filled = []
        for record in records:
            value, _ = outcome_value(record)
            if value is None and record["arm"] in (arm_x, arm_y):
                fill = treat_missing_as if record["arm"] == arm_x else control_missing_as
                record = {**record, "outcome_kind": "scored", "score": fill, "violations": []}
            filled.append(record)
        diffs, _ = block_differences(filled, arm_x, arm_y)
        return statistic(diffs)

    out["missing_worst_case_for_treatment"] = bounded(0.0, 1.0)
    out["missing_best_case_for_treatment"] = bounded(1.0, 0.0)
    effects = base["task_effects"]
    leave_one = {}
    for task in effects:
        rest = [r for r in records if r["task"] != task]
        leave_one[task] = statistic(block_differences(rest, arm_x, arm_y)[0])
    values = [v for v in leave_one.values() if v is not None]
    out["leave_one_task_out_range"] = [min(values), max(values)] if values else None
    return out


def descriptive_by_use(records: list[dict], arm: str = "B") -> dict:
    """Mean score of an MCP-enabled arm split by whether the agent called a tool.

    DESCRIPTIVE ONLY. Use is chosen by the agent after seeing the task, so this comparison is
    confounded by task difficulty and agent state and carries no causal reading.
    """
    groups: dict[str, list[float]] = {"used": [], "not_used": []}
    for record in records:
        if record["arm"] != arm:
            continue
        value, _ = outcome_value(record)
        if value is None:
            continue
        groups["used" if record["mcp"]["attempted"] > 0 else "not_used"].append(value)
    return {
        "arm": arm,
        "label": "descriptive, confounded, not an estimate of the effect of tool use",
        **{k: {"n": len(v), "mean": (sum(v) / len(v)) if v else None} for k, v in groups.items()},
    }


def run_preregistered_analysis(
    records: list[dict], seed: int, n_perm: int = 19_999, n_boot: int = 5000
) -> dict:
    """The complete preregistered analysis (primary, secondary family, sensitivity, descriptive)."""
    primary = estimate(records, "B", "A", seed, n_perm=n_perm, n_boot=n_boot)
    secondary = {
        name: estimate(records, x, y, seed, n_perm=n_perm, n_boot=n_boot)
        for name, (x, y) in {"C-B": ("C", "B"), "C-A": ("C", "A")}.items()
    }
    secondary["B-A:fully_correct"] = estimate(
        records, "B", "A", seed, outcome="fully_correct", n_perm=n_perm, n_boot=n_boot
    )
    adjusted = holm({k: v["p_value"] for k, v in secondary.items()})
    for key, value in secondary.items():
        value["p_holm"] = adjusted[key]
    return {
        "primary": primary,
        "secondary": secondary,
        "secondary_family_correction": "Holm over C-B, C-A, B-A:fully_correct",
        "sensitivity": sensitivity(records, seed),
        "descriptive_use_B": descriptive_by_use(records, "B"),
        "alpha": ALPHA,
        "primary_decision": (
            None
            if primary["p_value"] is None
            else "reject_null_at_alpha"
            if primary["p_value"] < ALPHA
            else "do_not_reject_null"
        ),
    }
