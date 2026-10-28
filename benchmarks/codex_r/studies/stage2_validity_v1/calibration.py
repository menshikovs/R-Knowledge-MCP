"""Task catalogue and the preregistered calibration/selection rule for study stage2_validity_v1.

Two kinds of information are kept apart:

* DIMENSIONS - hand-classified from each task's statement and metadata, never from outcomes.
* SCREEN     - computed from calibration trials of the BASELINE ARM ONLY (arm A). Outcomes of arms
               that have MCP access are never used to include or exclude a task, so selection cannot
               manufacture an MCP effect. Historical results are used only as a *provisional*
               screen: they were produced with different software, scorer versions and instruction
               variants, on live upstream data, and are labelled as such.

Ordinal scale 0..3 (none, low, moderate, high) for every dimension.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

DIMENSIONS = (
    "r_knowledge_depth",
    "version_sensitivity",
    "documentation_dependence",
    "reasoning_complexity",
    "code_generation_complexity",
    "statistical_reasoning",
    "debugging_difficulty",
    "package_api_verification_need",
)

SCREEN_MIN_TRIALS = 3
SCREEN_LOW, SCREEN_HIGH = 0.10, 0.90


def _t(task, suite, title, dims, usefulness, notes, scorer):
    values = dict(zip(DIMENSIONS, dims, strict=True))
    return {
        "task": task,
        "suite": suite,
        "title": title,
        "dimensions": values,
        "expected_mcp_usefulness": usefulness,
        "scorer": scorer,
        "notes": notes,
    }


# dims order: knowledge depth, version sensitivity, documentation dependence, reasoning, code
# generation, statistical reasoning, debugging, package API verification need.
CATALOG = [
    _t(
        "R01",
        "legacy-R",
        "Base R validation (clean_records)",
        (1, 0, 0, 1, 2, 0, 0, 0),
        "none",
        "Base R; typed edge cases.",
        "legacy",
    ),
    _t("R02", "legacy-R", "dplyr grouped sales", (1, 0, 1, 1, 2, 0, 0, 1), "low", "", "legacy"),
    _t(
        "R03",
        "legacy-R",
        "readr malformed typed CSV",
        (1, 1, 1, 1, 2, 0, 1, 1),
        "low",
        "",
        "legacy",
    ),
    _t(
        "R04",
        "legacy-R",
        "ggplot2 grouped log plot",
        (1, 1, 1, 1, 2, 0, 0, 1),
        "low",
        "Plot semantics checked structurally, not by pixels.",
        "legacy",
    ),
    _t("R05", "legacy-R", "tidyr irregular visits", (1, 1, 1, 1, 2, 0, 0, 1), "low", "", "legacy"),
    _t(
        "R06",
        "legacy-R",
        "Parameterized SQLite lookup",
        (1, 0, 1, 1, 2, 0, 0, 0),
        "none",
        "",
        "legacy",
    ),
    _t("R07", "legacy-R", "Safe SQL aggregation", (1, 0, 1, 2, 2, 0, 0, 0), "none", "", "legacy"),
    _t(
        "R08", "legacy-R", "Shiny reactive filtering", (2, 1, 2, 2, 2, 0, 0, 2), "low", "", "legacy"
    ),
    _t("R09", "legacy-R", "Reusable Shiny module", (2, 1, 2, 2, 2, 0, 0, 2), "low", "", "legacy"),
    _t(
        "R10",
        "legacy-R",
        "Reproducible Quarto report",
        (2, 1, 2, 1, 2, 0, 0, 2),
        "low",
        "",
        "legacy",
    ),
    _t(
        "R11",
        "legacy-R",
        "IRanges interval summary (Bioc 3.22)",
        (2, 2, 2, 1, 2, 0, 0, 2),
        "plausible",
        "Pinned Bioconductor release.",
        "legacy",
    ),
    _t(
        "R12",
        "legacy-R",
        "CSV to validated report workflow",
        (1, 0, 1, 2, 3, 0, 1, 0),
        "none",
        "",
        "legacy",
    ),
    _t(
        "B01",
        "knowledge-B",
        "Repair ledger summary",
        (1, 1, 1, 2, 2, 0, 2, 1),
        "low",
        "",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "B02",
        "knowledge-B",
        "Carry device state across batches",
        (1, 1, 1, 2, 2, 0, 2, 1),
        "low",
        "",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "B03",
        "knowledge-B",
        "Repair invoice revision handling",
        (1, 1, 1, 2, 2, 0, 2, 1),
        "low",
        "",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "C01",
        "knowledge-C",
        "dplyr 1.2.1 closest-prior join",
        (2, 3, 3, 2, 2, 0, 2, 3),
        "high",
        "Documented-syntax task.",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "C02",
        "knowledge-C",
        "tidyr 1.3.2 widen with duplicates",
        (2, 2, 2, 2, 2, 0, 2, 3),
        "plausible",
        "",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "C03",
        "knowledge-C",
        "readr 2.2.0 European amounts",
        (2, 2, 2, 1, 2, 0, 2, 3),
        "plausible",
        "",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "C04",
        "knowledge-C",
        "cranlogs 2.1.1 date-range repair",
        (2, 3, 3, 1, 2, 0, 2, 3),
        "high",
        "Follows the official package documentation.",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "C05",
        "knowledge-C",
        "cranlogs total downloads",
        (2, 3, 3, 2, 2, 0, 1, 3),
        "high",
        "Injected fetch function; no network in scoring.",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "D01",
        "knowledge-D",
        "Choose a terminal-UI package",
        (2, 2, 3, 2, 0, 0, 0, 3),
        "high",
        "Names termr explicitly; accepts only candidates in a frozen list (BEN-002).",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "D02",
        "knowledge-D",
        "Choose an HTTP-testing package",
        (2, 2, 3, 2, 0, 0, 0, 3),
        "high",
        "Same scorer family and caveat as D01.",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "D03",
        "knowledge-D",
        "Choose a data-validation package",
        (2, 2, 3, 2, 0, 0, 0, 3),
        "high",
        "Same scorer family and caveat as D01.",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "E01",
        "knowledge-E",
        "Repair a CRAN/Bioconductor lock conflict",
        (3, 3, 3, 3, 1, 0, 2, 3),
        "high",
        "Hidden JSON contract (BEN-002): floor attributed to the scorer.",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "E02",
        "knowledge-E",
        "Small compatible RNA-seq workflow",
        (3, 2, 2, 2, 3, 2, 2, 2),
        "plausible",
        "DESeq2 on a pinned fixture; statistical method fixed by the task.",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "E03",
        "knowledge-E",
        "Repair a relocated Bioconductor API call",
        (3, 3, 3, 1, 2, 0, 2, 3),
        "high",
        "",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "E04",
        "knowledge-E",
        "Resolve mixed CRAN/Bioconductor dependencies",
        (3, 3, 3, 3, 0, 0, 1, 3),
        "high",
        "Exact-equality gates (BEN-002).",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "E05",
        "knowledge-E",
        "Classify compatibility with evidence",
        (3, 3, 3, 3, 0, 0, 1, 3),
        "high",
        "Exact-equality gates (BEN-002).",
        "knowledge-pilot-v2.1",
    ),
    _t(
        "H01",
        "hard",
        "Dynamic weighted group summaries (tidy evaluation)",
        (3, 1, 1, 3, 3, 0, 2, 1),
        "low",
        "Behavioural hidden-style verifier with wrong-strategy controls.",
        "hard-v1",
    ),
    _t(
        "H04",
        "hard",
        "Point-in-time quote matching",
        (3, 1, 1, 3, 3, 0, 2, 1),
        "low",
        "data.table substituted by dplyr in the pinned image.",
        "hard-v1",
    ),
    _t(
        "H10",
        "hard",
        "Rubin's rules pooling",
        (3, 0, 1, 3, 3, 3, 2, 1),
        "low",
        "Statistical inference; closest existing stand-in for ANOVA-style validity.",
        "hard-v1",
    ),
]


def screen(history_a: dict | None) -> dict:
    """Arm-A-only screen from calibration/historical trials (never uses arms with MCP)."""
    if not history_a or history_a["n"] < SCREEN_MIN_TRIALS:
        n = 0 if not history_a else history_a["n"]
        return {
            "status": "insufficient_data",
            "n": n,
            "mean_arm_a": history_a and history_a["mean"],
        }
    mean = history_a["mean"]
    status = "ceiling" if mean > SCREEN_HIGH else "floor" if mean < SCREEN_LOW else "in_range"
    return {"status": status, "n": history_a["n"], "mean_arm_a": mean}


def target_by_features(entry: dict) -> bool:
    """S1 eligibility by task text alone: MCP plausibly useful and a feature need >= 2."""
    features = entry["dimensions"]
    return entry["expected_mcp_usefulness"] in ("plausible", "high") and (
        max(
            features["version_sensitivity"],
            features["documentation_dependence"],
            features["package_api_verification_need"],
        )
        >= 2
    )


def stratum(entry: dict, screen_result: dict) -> str:
    """Provisional stratum from non-outcome features plus the arm-A screen.

    S1  target: MCP plausibly useful (version / documentation / API need >= 2, usefulness
        plausible or high), screen in_range.
    S2  control: MCP not expected to help; measures the cost of merely having tools.
    RC  needs re-calibration: S1 by features but ceiling/floor/insufficient arm-A data.
    Q   quarantined until the scorer is revised and revalidated (known contract issues).
    """
    if entry["task"] in ("E01", "E04", "E05", "D01", "D02", "D03"):
        # BEN-002: scorers accept only frozen constants / hidden JSON contracts. D-tasks may be
        # piloted to measure variance, but are not confirmatory until a scorer revision passes the
        # alternative-solution calibration in SCORING_VALIDITY.md.
        return "Q"
    if not target_by_features(entry):
        return "S2"
    return "S1" if screen_result["status"] == "in_range" else "RC"


def summarize_history(results_dir: Path, *, before_date: str = "20261028") -> dict:
    """Read-only aggregate of saved historical trial records (the directory is git-ignored).

    By default `before_date="20261028"` restricts timestamped run directories (`YYYYMMDDTHHMMSSZ-*`)
    to the pre-Stage-2 baseline history so later ad-hoc runs do not mutate the frozen calibration
    snapshot. Pass `before_date=""` to include every timestamped directory.
    """
    rows = []
    for path in sorted(Path(results_dir).glob("*/results.json")):
        run_name = path.parent.name
        if before_date and len(run_name) >= 9 and run_name[:8].isdigit() and run_name[8] == "T":
            if run_name[:8] >= before_date:
                continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            rows += [r for r in data if isinstance(r, dict) and "task" in r and "mode" in r]
    per_task: dict[str, dict] = {}
    durations = []
    for row in rows:
        score = row.get("score") if isinstance(row.get("score"), dict) else None
        scored = row.get("status") == "scored" and score and score.get("total")
        cell = per_task.setdefault(row["task"], {}).setdefault(row["mode"], [])
        if scored:
            cell.append(score["passed"] / score["total"])
            if isinstance(row.get("duration_seconds"), (int, float)):
                durations.append(row["duration_seconds"])
    arm_a = {}
    for task, modes in per_task.items():
        values = modes.get("without-mcp", [])
        arm_a[task] = {
            "n": len(values),
            "mean": round(sum(values) / len(values), 4) if values else None,
        }
    ordered = sorted(durations)
    return {
        "source": "benchmarks/codex_r/results/*/results.json (git-ignored; read-only)",
        "trial_records": len(rows),
        "status_counts": {
            k: sum(1 for r in rows if r.get("status") == k)
            for k in sorted({r.get("status") for r in rows} - {None})
        },
        "usage_observed": sum(1 for r in rows if r.get("usage_status") == "observed"),
        "scored_duration_seconds": {
            "n": len(ordered),
            "median": statistics.median(ordered) if ordered else None,
            "p90": ordered[int(0.9 * (len(ordered) - 1))] if ordered else None,
        },
        "arm_a_by_task": dict(sorted(arm_a.items())),
        "note": "Arm A only is used for screening; arms with MCP access are not summarised.",
    }


def build_catalog(summary: dict) -> dict:
    entries = []
    for entry in CATALOG:
        s = screen(summary["arm_a_by_task"].get(entry["task"]))
        entries.append(
            {**entry, "historical_arm_a_screen": s, "provisional_stratum": stratum(entry, s)}
        )
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["provisional_stratum"]] = counts.get(e["provisional_stratum"], 0) + 1
    return {
        "schema_version": 1,
        "classification_basis": "dimensions read from task statements/metadata, not outcomes",
        "screen_rule": {
            "uses": "arm A (baseline) trials only",
            "min_trials": SCREEN_MIN_TRIALS,
            "in_range": [SCREEN_LOW, SCREEN_HIGH],
        },
        "stratum_counts": dict(sorted(counts.items())),
        "tasks": entries,
    }
