"""Simulation-based design sensitivity and resource arithmetic for study stage2_validity_v1.

The simulation uses the *same* test as the preregistered analysis (task-level sign-flip on the
within-task mean paired difference; block-level sign-flip is retained only in `type_i_comparison`
to demonstrate sharp-null Type I error inflation under task heterogeneity), so power and type-I
error describe the real procedure. Every parameter is an explicit assumption, not an estimate of
the real system; the historical calibration data are too small and too saturated to support more
(see TASK_CALIBRATION.md).

Generative model per simulated task t:
  saturated tasks (fraction `saturated`)   p_A = p_B = `ceiling_p`  (no room for any effect)
  other tasks                               p_A ~ Beta(mean `mean_a`, concentration `kappa`)
                                            p_B = clip(p_A + d_t),  d_t ~ Normal(delta, tau)
  per trial                                 logit p_trial = logit p + Normal(0, rep_sd);
                                            score = Binomial(checks, p_trial) / checks
`delta` is the true mean difference among the non-saturated tasks (so the diluted population effect
is delta * (1 - saturated)). All draws are seeded and reproducible.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .analysis import sign_flip_p
from .design import seeded


@dataclass(frozen=True)
class Assumptions:
    mean_a: float = 0.45
    kappa: float = 3.0
    saturated: float = 0.25
    ceiling_p: float = 0.97
    tau: float = 0.10
    rep_sd: float = 0.5
    checks: int = 5


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def simulate_dataset(tasks: int, reps: int, delta: float, a: Assumptions, rng) -> dict:
    diffs: dict[str, list[float]] = {}
    for t in range(tasks):
        if rng.random() < a.saturated:
            p_a = p_b = a.ceiling_p
        else:
            p_a = rng.betavariate(a.mean_a * a.kappa, (1 - a.mean_a) * a.kappa)
            p_a = min(max(p_a, 0.02), 0.98)
            p_b = min(max(p_a + rng.gauss(delta, a.tau), 0.02), 0.98)
        row = []
        for _ in range(reps):
            score = []
            for p in (p_b, p_a):
                q = _sigmoid(_logit(p) + rng.gauss(0, a.rep_sd))
                score.append(sum(rng.random() < q for _ in range(a.checks)) / a.checks)
            row.append(score[0] - score[1])
        diffs[f"t{t:03d}"] = row
    return diffs


def power_cell(
    tasks: int, reps: int, delta: float, a: Assumptions, n_sim: int, n_perm: int, seed: int
) -> dict:
    rejections = 0
    estimates = []
    for sim in range(n_sim):
        rng = seeded(seed, "power", f"{tasks}|{reps}|{delta}|{sim}")
        diffs = simulate_dataset(tasks, reps, delta, a, rng)
        means = [sum(v) / len(v) for v in diffs.values()]
        estimates.append(sum(means) / len(means))
        p = sign_flip_p(diffs, seed=seed + sim, n_perm=n_perm)["p"]
        rejections += p < 0.05
    mean = sum(estimates) / n_sim
    return {
        "tasks": tasks,
        "repetitions": reps,
        "delta_non_saturated": delta,
        "diluted_effect": delta * (1 - a.saturated),
        "rejection_rate": rejections / n_sim,
        "mean_estimate": mean,
        "n_sim": n_sim,
        "n_perm": n_perm,
    }


DESIGNS = {
    "pilot": (8, 3),
    "recommended_confirmatory": (30, 3),
    "higher_confidence": (40, 5),
}
DELTAS = (-0.20, -0.10, 0.0, 0.10, 0.20, 0.30)


def type_i_comparison(
    tasks: int, reps: int, a: Assumptions, n_sim: int, n_perm: int, seed: int
) -> dict:
    """Rejection rate at an average effect of 0 for the task-level (primary) and block-level test.

    Task effects are heterogeneous with mean zero (tau > 0), so the sharp null is false while the
    null about the *average* effect is true: the block-level test is not valid for the latter.
    """
    rejections = {"task": 0, "block": 0}
    for sim in range(n_sim):
        rng = seeded(seed, "type-i", f"{tasks}|{reps}|{sim}")
        diffs = simulate_dataset(tasks, reps, 0.0, a, rng)
        for unit in rejections:
            rejections[unit] += sign_flip_p(diffs, seed + sim, n_perm, unit=unit)["p"] < 0.05
    return {
        "tasks": tasks,
        "repetitions": reps,
        "n_sim": n_sim,
        "type_i_task_level": rejections["task"] / n_sim,
        "type_i_block_level": rejections["block"] / n_sim,
    }


def power_table(a: Assumptions, n_sim: int, n_perm: int, seed: int) -> dict:
    rows = []
    for name, (tasks, reps) in DESIGNS.items():
        for delta in DELTAS:
            rows.append({"design": name, **power_cell(tasks, reps, delta, a, n_sim, n_perm, seed)})
    type_i = [
        type_i_comparison(tasks, reps, a, n_sim, n_perm, seed) for tasks, reps in DESIGNS.values()
    ]
    return {
        "assumptions": asdict(a),
        "seed": seed,
        "n_sim": n_sim,
        "n_perm": n_perm,
        "rows": rows,
        "type_i_check": type_i,
    }


def resources(tasks: int, reps: int, arms: int, retry_allowance: float, durations: dict) -> dict:
    """Trial counts and wall-clock from *measured* historical durations; tokens left symbolic."""
    planned = tasks * reps * arms
    upper = math.ceil(planned * (1 + retry_allowance))
    out = {
        "tasks": tasks,
        "repetitions": reps,
        "arms": arms,
        "planned_trials": planned,
        "trials_with_retry_allowance": upper,
        "retry_allowance": retry_allowance,
        "model_sessions": upper,
        "tokens_total_formula": "trials_with_retry_allowance x tokens_per_trial (not observed)",
        "cost_total_formula": "tokens_total x price per token (supply a verified price)",
    }
    for key in ("median_seconds", "p90_seconds"):
        seconds = durations.get(key)
        if seconds is not None:
            out[f"sequential_hours_{key.split('_')[0]}"] = round(upper * seconds / 3600, 1)
    return out
