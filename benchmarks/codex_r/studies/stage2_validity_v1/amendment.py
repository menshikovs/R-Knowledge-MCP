"""Preregistration amendment A1 (protocol 1.1.0): capability equivalence replaces network topology.

The original preregistration (PREREGISTRATION.md, experiment_manifest.json, protocol 1.0.0) is not
modified. A1 is registered before any real experimental trial and applies only to trials whose run
configuration declares it (``StudyExecutionConfig.protocol_amendment == "A1"``) *and* that started
at or after ``EFFECTIVE_FROM_UTC``. Everything else, including every historical record, keeps the
1.0.0 evaluation unchanged.

Under A1:

* ``egress_not_restricted`` and ``egress_unverified`` (a network-topology requirement the runner
  never implemented) are still recorded, unchanged in code and detail, but marked
  ``invalidating: false`` with ``superseded_by: "A1"``. They are not deleted.
* Capability equivalence is checked per trial against the run's capability policy; any deviation
  is an invalidating violation (codes in ``NEW_VIOLATIONS``). The 1.0.0 checks for MCP
  availability, instructions, model, effort and scorer still apply unchanged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import manifest, protocol

AMENDMENT_ID = "A1"
PROTOCOL_VERSION = "1.1.0"
BASE_PROTOCOL_VERSION = protocol.STUDY_VERSION
REGISTERED_ON = "2026-10-28"
EFFECTIVE_FROM_UTC = "2026-10-28T00:00:00Z"
STUDY = Path(__file__).resolve().parent
DOCUMENT = STUDY / "PREREGISTRATION_AMENDMENT_A1.md"
RECORD = STUDY / "preregistration_amendment_a1.json"

SUPERSEDED_VIOLATIONS = ("egress_not_restricted", "egress_unverified")
NEW_VIOLATIONS = {
    "capability_configuration_unrecorded": "the trial did not log its capability configuration",
    "non_mcp_capabilities_differ": (
        "configured non-MCP tools or executor runtime differ from the run's policy (A/B equality)"
    ),
    "execution_environment_differs": "network or model transport differs from the run's policy",
    "web_access_policy_differs": "the trial's web-access policy is not the study's policy",
    "web_access_policy_deviation": "web-access tool use observed although the policy forbids it",
    "scorer_material_exposed": "scorer or reference files were reachable from candidate mounts",
    "reference_access_suspected": (
        "heuristic: agent tool items reference the benchmark's scorer/reference locations"
    ),
    "pre_amendment_trial": "the trial started before the amendment's effective time",
}
RULES = {
    "capability_equivalence": [
        "Arms A and B have identical non-MCP capabilities (configured agent tools, executor "
        "runtime image, network and model transport) and byte-identical instructions.",
        "MCP is unavailable in A and available in B and C; C adds only the registered "
        "encouragement sentence.",
        "All arms may use the same required model API transport; network topology is not itself "
        "a validity requirement.",
        "Scorers and reference answers are not reachable from candidate mounts during execution; "
        "observed references to them are recorded as a heuristic violation.",
        "Study 1 and Study 2 each record an explicit web-access policy; web use contrary to the "
        "policy is a deviation.",
        "The actual capability configuration, observed tool use and all deviations are logged "
        "per trial.",
    ],
    "superseded_violation_codes": list(SUPERSEDED_VIOLATIONS),
    "new_violation_codes": NEW_VIOLATIONS,
    "unchanged": [
        "primary estimand (B - A, intention to treat, equal task weights)",
        "randomization and assignment",
        "outcome definitions and missing-data rules",
        "statistical inference and multiplicity control",
        "all other 1.0.0 violation codes and their invalidating status",
    ],
}
COMPATIBILITY = {
    "applies_to": "trials of runs whose run_config declares protocol_amendment A1 and that "
    f"started at or after {EFFECTIVE_FROM_UTC}",
    "historical_records": "unchanged; evaluated under protocol 1.0.0; never made eligible "
    "retroactively",
    "recorded_violations": "never removed; superseded codes remain in each A1 record, marked "
    "invalidating false with superseded_by A1",
    "resume": "a run directory is bound to its protocol version; resuming under a different one "
    "is rejected",
    "pooling": "records evaluated under 1.0.0 and A1 are reported separately, never pooled",
}


def sha256_file(path: Path) -> str:
    # Line-ending canonical digest (as for frozen evidence), identical on every platform.
    return manifest.digest(Path(path))


def rules_sha256() -> str:
    body = {
        "rules": RULES,
        "compatibility": COMPATIBILITY,
        "effective_from_utc": EFFECTIVE_FROM_UTC,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_amendment_record() -> dict[str, Any]:
    """Machine-readable amendment, pinning the unchanged originals it amends."""
    saved = json.loads((STUDY / "experiment_manifest.json").read_text(encoding="utf-8"))
    return {
        "amendment_id": AMENDMENT_ID,
        "study_id": protocol.STUDY_ID,
        "protocol_version": PROTOCOL_VERSION,
        "amends_protocol_version": BASE_PROTOCOL_VERSION,
        "registered_on": REGISTERED_ON,
        "effective_from_utc": EFFECTIVE_FROM_UTC,
        "registered_before_any_real_trial": True,
        "base": {
            "experiment_manifest_core_sha256": saved["core_sha256"],
            "experiment_manifest_json_sha256": sha256_file(STUDY / "experiment_manifest.json"),
            "preregistration_md_sha256": sha256_file(STUDY / "PREREGISTRATION.md"),
        },
        "rules": RULES,
        "compatibility": COMPATIBILITY,
        "rules_sha256": rules_sha256(),
        "document": DOCUMENT.name,
        "document_sha256": sha256_file(DOCUMENT),
    }


def _started_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def evaluate(
    base_violations: list[dict[str, Any]],
    capability: dict[str, Any] | None,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """1.0.0 violations re-marked under A1, plus A1's capability-equivalence violations."""
    found = []
    for violation in base_violations:
        if violation["code"] in SUPERSEDED_VIOLATIONS:
            violation = {**violation, "invalidating": False, "superseded_by": AMENDMENT_ID}
        found.append(violation)

    def add(code: str, detail: str) -> None:
        found.append({"code": code, "detail": detail, "invalidating": True, "rule": AMENDMENT_ID})

    if not isinstance(capability, dict):
        add(
            "capability_configuration_unrecorded",
            NEW_VIOLATIONS["capability_configuration_unrecorded"],
        )
        return found
    started = _started_at(capability.get("started_at_utc"))
    if started is None or started < _started_at(EFFECTIVE_FROM_UTC):
        add("pre_amendment_trial", f"started_at_utc={capability.get('started_at_utc')!r}")
    for key in ("non_mcp_tools", "executor_image"):
        if capability.get(key) != policy.get(key):
            add(
                "non_mcp_capabilities_differ",
                f"{key}: {capability.get(key)!r} != {policy.get(key)!r}",
            )
    for key in ("network", "model_transport"):
        if capability.get(key) != policy.get(key):
            add(
                "execution_environment_differs",
                f"{key}: {capability.get(key)!r} != {policy.get(key)!r}",
            )
    if capability.get("web_access_policy") != policy.get("web_access_policy"):
        add(
            "web_access_policy_differs",
            f"{capability.get('web_access_policy')!r} != {policy.get('web_access_policy')!r}",
        )
    observed = capability.get("observed") or {}
    if policy.get("web_access_policy") == "none" and observed.get("web_access_calls"):
        add("web_access_policy_deviation", f"{observed['web_access_calls']} web-access item(s)")
    exposed = (capability.get("scorer_isolation") or {}).get("exposed_files")
    if exposed is None:
        add("capability_configuration_unrecorded", "scorer isolation evidence missing")
    elif exposed:
        add("scorer_material_exposed", ", ".join(exposed[:5]))
    hits = observed.get("reference_access_hits")
    if hits:
        add("reference_access_suspected", ", ".join(hits[:5]))
    return found
