"""Paired, counterbalanced, seeded allocation of trials for study stage2_validity_v1.

Unit of randomization: a *block* = one (task, repetition). Every arm of the design runs once in each
block, in an independent context (no history shared between trials). Randomization has two layers:

1. Within a block the arm order is a permutation of the arms. For each task the permutations are
   dealt from shuffled complete cycles of all permutations, so arm-by-position balance holds
   exactly whenever the repetitions are a multiple of the number of permutations and is within one
   otherwise.
2. The blocks are shuffled globally, so the arms of one block are adjacent in time (upstream drift
   is shared inside a pair) while task and repetition are not confounded with calendar time.

All randomness comes from `random.Random` seeded by SHA-256 of (study seed, purpose, key); the
algorithm id is part of the plan, so a plan can be regenerated and byte-compared.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random

ALGORITHM = "blocked-latin-permutations-v1"


def seeded(seed: int, purpose: str, key: str = "") -> random.Random:
    digest = hashlib.sha256(f"{seed}|{purpose}|{key}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def arm_orders(
    arms: tuple[str, ...], repetitions: int, rng: random.Random
) -> list[tuple[str, ...]]:
    """One arm order per repetition, dealt from shuffled complete cycles of all permutations."""
    permutations = list(itertools.permutations(arms))
    dealt: list[tuple[str, ...]] = []
    while len(dealt) < repetitions:
        cycle = permutations[:]
        rng.shuffle(cycle)
        dealt.extend(cycle)
    return dealt[:repetitions]


def build_plan(
    tasks: list[str], arms: tuple[str, ...], repetitions: int, seed: int, study_id: str
) -> dict:
    if len(set(tasks)) != len(tasks) or len(set(arms)) != len(arms):
        raise ValueError("tasks and arms must be unique")
    if repetitions < 1 or not tasks or len(arms) < 2:
        raise ValueError("need at least one task, one repetition and two arms")
    blocks = []
    for task in tasks:
        orders = arm_orders(arms, repetitions, seeded(seed, "arm-order", task))
        for repetition, order in enumerate(orders, start=1):
            blocks.append({"task": task, "repetition": repetition, "arm_order": list(order)})
    seeded(seed, "block-order").shuffle(blocks)
    trials, position = [], 0
    for block_index, block in enumerate(blocks, start=1):
        block_id = f"{block['task']}-r{block['repetition']}"
        block["block_id"], block["block_index"] = block_id, block_index
        for within, arm in enumerate(block["arm_order"], start=1):
            position += 1
            trials.append(
                {
                    "trial_id": f"{block_id}-{arm}",
                    "block_id": block_id,
                    "task": block["task"],
                    "repetition": block["repetition"],
                    "arm": arm,
                    "execution_index": position,
                    "position_in_block": within,
                    "fresh_context": True,
                    "trial_seed": seeded(seed, "trial", f"{block_id}-{arm}").getrandbits(32),
                }
            )
    plan = {
        "study_id": study_id,
        "algorithm": ALGORITHM,
        "seed": seed,
        "tasks": list(tasks),
        "arms": list(arms),
        "repetitions": repetitions,
        "blocks": blocks,
        "trials": trials,
    }
    plan["plan_sha256"] = plan_digest(plan)
    return plan


def plan_digest(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_plan(plan: dict) -> list[str]:
    """Structural problems of a plan (empty list = valid); used before any trial is run."""
    problems = []
    arms, tasks, reps = plan["arms"], plan["tasks"], plan["repetitions"]
    if plan.get("plan_sha256") != plan_digest(plan):
        problems.append("plan digest does not match content")
    ids = [t["trial_id"] for t in plan["trials"]]
    if len(ids) != len(set(ids)):
        problems.append("duplicate trial ids")
    if len(plan["trials"]) != len(tasks) * len(arms) * reps:
        problems.append("trial count differs from tasks x arms x repetitions")
    by_block: dict[str, list[dict]] = {}
    for trial in plan["trials"]:
        by_block.setdefault(trial["block_id"], []).append(trial)
    for block_id, rows in by_block.items():
        if sorted(r["arm"] for r in rows) != sorted(arms):
            problems.append(f"block {block_id} does not contain every arm exactly once")
        if sorted(r["position_in_block"] for r in rows) != list(range(1, len(arms) + 1)):
            problems.append(f"block {block_id} positions are not 1..{len(arms)}")
        executions = sorted(r["execution_index"] for r in rows)
        if executions != list(range(executions[0], executions[0] + len(arms))):
            problems.append(f"block {block_id} trials are not contiguous in execution order")
    if sorted(t["execution_index"] for t in plan["trials"]) != list(range(1, len(ids) + 1)):
        problems.append("execution indices are not 1..N")
    if not all(t["fresh_context"] for t in plan["trials"]):
        problems.append("a trial reuses a context")
    return problems


def position_balance(plan: dict) -> dict[str, dict[int, int]]:
    """How often each arm ran first, second, ... per whole plan (reported, not corrected)."""
    table: dict[str, dict[int, int]] = {arm: {} for arm in plan["arms"]}
    for trial in plan["trials"]:
        cell = table[trial["arm"]]
        cell[trial["position_in_block"]] = cell.get(trial["position_in_block"], 0) + 1
    return table
