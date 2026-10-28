"""Fail-closed monetary spend ceiling for model-backed trial execution.

A boolean "authorize spend" flag is not budget control. Model execution additionally needs an
explicit ``SpendCeiling``: a maximum in USD, caller-supplied token prices (never assumed here;
no price table for any model is shipped) and a per-trial reserve, i.e. the most one attempt is
allowed to cost.

Enforcement happens at attempt granularity, because nothing in the runner can cut a model
request off mid-flight:

* Before an attempt starts, ``spent + reserve`` must not exceed the ceiling; otherwise the
  attempt is refused and the run stops (remaining trials become ``not_executed``).
* After an attempt, observed usage is priced. When usage is unavailable or partial the full
  reserve is charged instead (the attempt may have reached the model).
* If observed cost exceeds the reserve, the pre-check guarantee no longer holds and the run
  stops. The run also stops if cumulative spend exceeds the ceiling.
* On resume, the ledger journal is replayed: every started attempt without an accounting entry
  (an interruption) is charged the full reserve.

This is accounting over reported usage, not provider billing; the provider's invoice remains
the authority, and the reserve must be chosen with the provider's own limits in mind.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

STOP_CEILING_REACHED = "spend_ceiling_reached"
STOP_CEILING_EXCEEDED = "spend_ceiling_exceeded"
STOP_RESERVE_EXCEEDED = "per_trial_reserve_exceeded"


@dataclass(frozen=True)
class SpendCeiling:
    max_spend_usd: float
    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float
    per_trial_reserve_usd: float

    def problems(self) -> list[str]:
        found = []
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                found.append(f"{name} must be a number")
            elif not math.isfinite(value) or value <= 0:
                found.append(f"{name} must be a finite number > 0")
        if not found and self.per_trial_reserve_usd > self.max_spend_usd:
            found.append("per_trial_reserve_usd exceeds max_spend_usd: no attempt could start")
        return found

    def price(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_usd_per_million_tokens
            + output_tokens * self.output_usd_per_million_tokens
        ) / 1_000_000

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


class SpendGuard:
    """``runner.AttemptController`` enforcing a ``SpendCeiling``."""

    def __init__(self, ceiling: SpendCeiling) -> None:
        problems = ceiling.problems()
        if problems:
            raise ValueError(f"invalid spend ceiling: {problems}")
        self.ceiling = ceiling
        self.spent_usd = 0.0
        self.reserve_charged_for_interruptions: list[str] = []

    def restore(self, journal: list[dict[str, Any]]) -> None:
        accounted = {e["attempt_id"]: e for e in journal if e.get("event") == "attempt_accounted"}
        self.spent_usd = sum(float(e.get("charged_usd") or 0.0) for e in accounted.values())
        for entry in journal:
            if entry.get("event") == "trial_attempt_started":
                if entry["attempt_id"] not in accounted:
                    self.spent_usd += self.ceiling.per_trial_reserve_usd
                    self.reserve_charged_for_interruptions.append(entry["attempt_id"])

    def before_attempt(self, trial_id: str, attempt_id: str) -> str | None:
        headroom = self.ceiling.max_spend_usd - self.spent_usd
        if self.ceiling.per_trial_reserve_usd > headroom + 1e-12:
            return STOP_CEILING_REACHED
        return None

    def after_attempt(
        self, trial_id: str, attempt_id: str, record: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        usage = record.get("usage") or {}
        if usage.get("status") == "observed":
            cost = self.ceiling.price(usage["input_tokens"], usage["output_tokens"])
            basis = "observed_usage"
        else:
            cost = self.ceiling.per_trial_reserve_usd
            basis = "usage_unobservable_reserve_charged"
        self.spent_usd += cost
        stop = None
        if basis == "observed_usage" and cost > self.ceiling.per_trial_reserve_usd:
            stop = STOP_RESERVE_EXCEEDED
        elif self.spent_usd > self.ceiling.max_spend_usd + 1e-12:
            stop = STOP_CEILING_EXCEEDED
        return (
            {
                "charged_usd": round(cost, 9),
                "charge_basis": basis,
                "cumulative_spend_usd": round(self.spent_usd, 9),
                "max_spend_usd": self.ceiling.max_spend_usd,
            },
            stop,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "ceiling": self.ceiling.to_dict(),
            "accounted_spend_usd": round(self.spent_usd, 9),
            "remaining_usd": round(self.ceiling.max_spend_usd - self.spent_usd, 9),
            "reserve_charged_for_interrupted_attempts": self.reserve_charged_for_interruptions,
            "basis": "reported token usage x caller-supplied prices; not provider billing",
        }
