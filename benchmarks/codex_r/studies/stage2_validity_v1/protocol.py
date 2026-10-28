"""Experimental arms, instruction texts and protocol-violation checks for study stage2_validity_v1.

Arms differ in exactly two ways: whether the R-Knowledge-MCP server is reachable (A vs B, C) and
whether a standard encouragement sentence is added to the instructions (C vs B). Everything else
(model, effort, task text, runtime image, time budget, scorer, egress policy) is identical and is
checked per trial against recorded evidence. A failed check is a *protocol violation*: it is
recorded with the trial, never silently dropped, and its effect on the analysis is fixed in the
preregistration (PREREGISTRATION.md).

Nothing here runs a model, a container or R. The checks operate on evidence dictionaries (what the
runner recorded), so they can be unit-tested with synthetic evidence and applied to real runs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

STUDY_ID = "stage2_validity_v1"
STUDY_VERSION = "1.0.0"

# Shared by every arm, byte for byte. It is the repository's historical "standard" instruction,
# which is already tool-neutral ("Documentation tools, if connected, are optional"). The
# runner's own constant is the source of truth; `base_instructions()` reads it and the manifest
# pins its digest.
ENCOURAGEMENT = (
    " When R-Knowledge-MCP tools are connected, use them to verify package, function and version "
    "facts before relying on memory; do not call them when they cannot help."
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def base_instructions() -> str:
    """The tool-neutral instruction text shared by all arms (imported lazily from the runner)."""
    from benchmarks.codex_r import run_simple

    return run_simple.INSTRUCTION_VARIANTS["standard"]


@dataclass(frozen=True)
class Arm:
    id: str
    label: str
    mcp_available: bool
    encouraged: bool
    description: str

    def instructions(self, base: str | None = None) -> str:
        text = base_instructions() if base is None else base
        return text + (ENCOURAGEMENT if self.encouraged else "")


ARMS: dict[str, Arm] = {
    "A": Arm(
        "A",
        "baseline",
        False,
        False,
        "R-Knowledge-MCP unavailable: no MCP container, no MCP tool in the allow-list.",
    ),
    "B": Arm(
        "B",
        "mcp-voluntary",
        True,
        False,
        "R-Knowledge-MCP available; instructions byte-identical to arm A (primary treatment).",
    ),
    "C": Arm(
        "C",
        "mcp-encouraged",
        True,
        True,
        "As B plus one fixed sentence encouraging verification via the MCP tools; no call forced.",
    ),
}

# Where the agent may connect. Everything else is an egress violation. The model endpoint is the
# only destination common to all arms; the MCP endpoint is part of the treatment (arms B and C).
MODEL_ENDPOINT = "model-api"
MCP_ENDPOINT = "r-knowledge-mcp"


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str
    invalidating: (
        bool  # whether the preregistered rule excludes the trial from the primary analysis
    )

    def as_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "invalidating": self.invalidating}


def expected_egress(arm: Arm) -> frozenset[str]:
    return frozenset({MODEL_ENDPOINT, MCP_ENDPOINT} if arm.mcp_available else {MODEL_ENDPOINT})


def capability_violations(arm_id: str, evidence: dict, expected: dict) -> list[Violation]:
    """Compare what a trial recorded with what its arm requires.

    `evidence` keys (all produced by the runner or the egress proxy; a missing key is itself a
    finding, never assumed benign):
      allowed_tools            list of tool names the agent could see (None when not recorded)
      mcp_container_started    bool
      mcp_calls_observed       int, calls seen by the server
      instructions_sha256      digest of the instruction text actually sent
      model, effort            as recorded by the session
      scorer_version           scorer id/version used for the trial
      network_internal         bool, whether the trial network had no default route
      egress_destinations      list of destinations contacted, from an observing proxy (None when
                               no proxy log exists)
    `expected` carries the study-wide constants: model, effort, scorer_version, base instruction
    digest, MCP tool names, and `require_egress_log`.
    """
    arm = ARMS[arm_id]
    found: list[Violation] = []

    def add(code: str, detail: str, invalidating: bool = True) -> None:
        found.append(Violation(code, detail, invalidating))

    mcp_tools = set(expected["mcp_tools"])
    allowed = evidence.get("allowed_tools")
    exposed = set(allowed or ()) & mcp_tools
    if allowed is None:
        add("tool_allowlist_unrecorded", "the session did not record the visible tool list")
    if not arm.mcp_available:
        if exposed or evidence.get("mcp_container_started"):
            add("arm_a_mcp_reachable", "baseline arm had an MCP tool or container")
        if evidence.get("mcp_calls_observed"):
            add(
                "arm_a_mcp_called",
                f"{evidence['mcp_calls_observed']} MCP calls in the baseline arm",
            )
    else:
        if allowed is not None and not exposed:
            add("treatment_not_delivered", "no R-Knowledge-MCP tool in the allow-list")
        if not evidence.get("mcp_container_started"):
            add("treatment_not_delivered", "MCP container was not started")
        elif allowed is not None and exposed != mcp_tools and set(allowed) & mcp_tools:
            add(
                "toolset_differs",
                f"{len(exposed)} of {len(mcp_tools)} expected MCP tools exposed",
                invalidating=False,
            )

    digest = evidence.get("instructions_sha256")
    want = sha256_text(arm.instructions(expected["base_instructions"]))
    if digest != want:
        add("instructions_mismatch", f"instruction digest {digest!r} is not the arm's text")

    for key in ("model", "effort", "scorer_version"):
        if evidence.get(key) != expected[key]:
            add(f"{key}_mismatch", f"{evidence.get(key)!r} != {expected[key]!r}")

    if evidence.get("network_internal") is not True:
        add("egress_not_restricted", "the trial network was not internal / had a default route")
    destinations = evidence.get("egress_destinations")
    if destinations is None:
        if expected.get("require_egress_log", True):
            add(
                "egress_unverified", "no egress log: other information channels cannot be ruled out"
            )
    else:
        extra = sorted(set(destinations) - expected_egress(arm))
        if extra:
            add("egress_unexpected_destination", ", ".join(extra))
    return found
