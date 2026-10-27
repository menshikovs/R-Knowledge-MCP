"""Version-isolated D01/D03 scorer with explicit claim evidence states.

V2.1 keeps the public V2 answer contracts. Its versioned local claim registry separates
required facts from other supported, unknown and contradicted claims. Unknown claims cause
an automatic-scoring abstention; they are never treated as either true or false.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmarks.codex_r import knowledge_pilot_v2 as v2

SCORER_VERSION = "knowledge-pilot-v2.1"
SUPPORTED_TASKS = frozenset({"D01", "D03"})
EVIDENCE_PATH = (
    Path(__file__).resolve().parent / "scorer_evidence" / "knowledge_pilot_claims_v2_1.json"
)


def evaluator_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def evidence_digest() -> str:
    return hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest()


def contract_digest() -> str:
    return v2.contract_digest()


def _evidence():
    value = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    if value.get("evidence_version") != "knowledge-pilot-claims-v2.1":
        raise ValueError("unsupported_claim_evidence_version")
    return value


def _validate_package_facts(task_id, package, facts):
    task = _evidence()["tasks"][task_id]
    for kind in ("features", "caveats"):
        task_ids = set(task["feature_ids"] if kind == "features" else task["caveat_ids"])
        required = set(facts[f"required_{kind}"])
        supported = set(facts[f"supported_{kind}"])
        unknown = set(facts[f"unknown_{kind}"])
        contradicted = set(facts[f"contradicted_{kind}"])
        if (
            required - supported
            or (supported & unknown)
            or (supported & contradicted)
            or (unknown & contradicted)
            or (supported | unknown | contradicted) != task_ids
        ):
            raise ValueError(f"invalid_{kind}_evidence_for_{task_id}_{package}")
    return task, facts


def classify_claims(task_id: str, package: str, recommendation: dict) -> dict:
    """Classify explicit feature/caveat IDs using only the versioned local registry."""
    task, facts = _validate_package_facts(
        task_id, package, _evidence()["tasks"][task_id]["packages"][package]
    )
    result = {
        "required": [],
        "supported": [],
        "unknown": [],
        "contradicted": [],
        "required_missing": [],
    }
    for kind, value_key, _ids in (
        ("features", "feature_ids", task["feature_ids"]),
        ("caveats", "caveat_ids", task["caveat_ids"]),
    ):
        supplied = set(recommendation.get(value_key, []))
        required = set(facts[f"required_{kind}"])
        result["required"].extend(f"{kind}:{item}" for item in sorted(required))
        result["required_missing"].extend(f"{kind}:{item}" for item in sorted(required - supplied))
        for item in sorted(supplied):
            if item in facts[f"supported_{kind}"]:
                result["supported"].append(f"{kind}:{item}")
            elif item in facts[f"contradicted_{kind}"]:
                result["contradicted"].append(f"{kind}:{item}")
            elif item in facts[f"unknown_{kind}"]:
                result["unknown"].append(f"{kind}:{item}")
            else:
                # Schema validation should reject this. Keep a defensive unknown outcome.
                result["unknown"].append(f"{kind}:{item}")
    result["status"] = (
        "contradicted"
        if result["contradicted"]
        else "unknown"
        if result["unknown"]
        else "supported"
    )
    return result


def _claim_dimension(claim_audit):
    checks = {
        "all_asserted_claims_supported": (
            "fail"
            if claim_audit["contradicted"]
            else "unknown"
            if claim_audit["unknown"]
            else "pass"
        ),
        "required_claims_present": "fail" if claim_audit["required_missing"] else "pass",
    }
    if "fail" in checks.values():
        status = "fail"
    elif "unknown" in checks.values():
        status = "unknown"
    else:
        status = "pass"
    known = sum(value != "unknown" for value in checks.values())
    passed = sum(value == "pass" for value in checks.values())
    return {
        "status": status,
        "passed": passed,
        "total": known,
        "checks": checks,
        "supported_claims": claim_audit["supported"],
        "unknown_claims": claim_audit["unknown"],
        "contradicted_claims": claim_audit["contradicted"],
        "required_missing": claim_audit["required_missing"],
        "required_claims": claim_audit["required"],
    }


def _provenance():
    evidence = _evidence()
    return {
        "scorer_version": SCORER_VERSION,
        "evaluator_sha256": evaluator_digest(),
        "contracts_sha256": contract_digest(),
        "claim_evidence_sha256": evidence_digest(),
        "claim_evidence_version": evidence["evidence_version"],
        "basis": evidence["basis"],
    }


def _result(task_id, hashes, dimensions, claim_audit=None):
    substantive = [
        dimensions[name]["status"]
        for name in ("factual_correctness", "version_repository_identity", "source_quality")
        if name in dimensions
    ]
    contradicted = bool(claim_audit and claim_audit["contradicted"])
    unknown = bool(claim_audit and claim_audit["unknown"])
    failed = (
        "fail" in substantive
        or dimensions["schema_validity"]["status"] == "fail"
        or contradicted
        or bool(claim_audit and claim_audit["required_missing"])
    )
    status = "unsupported_for_automatic_scoring" if unknown else "scored"
    return {
        "status": status,
        "scorer_version": SCORER_VERSION,
        "task_id": task_id,
        "reason": "unsupported_claims_unknown" if unknown else None,
        "passed": None,
        "total": None,
        "fully_correct": None if unknown else False if failed else True,
        "overall_score": None,
        "dimensions": dimensions,
        "claim_audit": claim_audit,
        "unsupported_claims_present": unknown or contradicted,
        "artifacts": hashes,
        "provenance": _provenance(),
    }


def _score_d(task_id, answer, hashes):
    recommendation = (
        answer.get("recommendations", [None])[0]
        if isinstance(answer.get("recommendations"), list) and answer["recommendations"]
        else {}
    )
    recommendation = recommendation if isinstance(recommendation, dict) else {}
    package = recommendation.get("package")
    schema_ok = v2.schema_valid(task_id, answer)
    dimensions = {"schema_validity": v2._dimension({"public_contract": schema_ok})}
    if not schema_ok:
        dimensions.update(
            factual_correctness=v2._dimension({}, evaluated=False),
            version_repository_identity=v2._dimension({}, evaluated=False),
            dependency_correctness=v2._dimension({}, applicable=False),
            source_quality=v2._dimension({}, evaluated=False),
            unsupported_claims={
                "status": "not_evaluated",
                "passed": None,
                "total": None,
                "checks": {},
            },
        )
        return _result(task_id, hashes, dimensions)

    registry = _evidence()["tasks"][task_id]
    facts = registry["packages"].get(package)
    rationale = answer.get("rationale")
    if facts is None:
        unknown_claims = [f"features:{item}" for item in recommendation.get("feature_ids", [])] + [
            f"caveats:{item}" for item in recommendation.get("caveat_ids", [])
        ]
        claim_audit = {
            "status": "unknown",
            "supported": [],
            "required": [],
            "unknown": unknown_claims or ["package_or_documentation_evidence"],
            "contradicted": [],
            "required_missing": [],
        }
        dimensions.update(
            factual_correctness=v2._dimension({"task_fit_and_documented_limits": None}),
            version_repository_identity=v2._dimension(
                {"package_version": None, "repository": None}
            ),
            dependency_correctness=v2._dimension({}, applicable=False),
            source_quality=v2._dimension({"official_source_and_documentation": None}),
            unsupported_claims=_claim_dimension(claim_audit),
        )
        return _result(task_id, hashes, dimensions, claim_audit)

    _, facts = _validate_package_facts(task_id, package, facts)
    claim_audit = classify_claims(task_id, package, recommendation)
    frozen = v2.pilot.official_resources()[task_id][package]
    resources = {
        kind: v2.pilot._resource_urls(frozen, kind) for kind in ("source", "documentation")
    }
    supplied_features = set(recommendation.get("feature_ids", []))
    supplied_caveats = set(recommendation.get("caveat_ids", []))
    required_feature_ok = set(facts["required_features"]) <= supplied_features
    required_caveat_ok = set(facts["required_caveats"]) <= supplied_caveats
    urls = [recommendation.get("source_url"), recommendation.get("documentation_url")]
    dimensions.update(
        factual_correctness=v2._dimension(
            {
                "r_version": answer.get("r_version") == v2.pilot.manifest()["environment"]["r"],
                "documented_features": required_feature_ok,
                "documented_limits": required_caveat_ok,
                "rationale_present": isinstance(rationale, str) and len(rationale.strip()) >= 40,
            }
        ),
        version_repository_identity=v2._dimension(
            {
                "package_version": recommendation.get("version") == facts["version"],
                "repository": recommendation.get("source_url") in resources["source"],
            }
        ),
        dependency_correctness=v2._dimension({}, applicable=False),
        source_quality=v2._dimension(
            {
                "official_source_url": recommendation.get("source_url") in resources["source"],
                "official_documentation_url": recommendation.get("documentation_url")
                in resources["documentation"],
                "source_shapes_are_official": v2._official_sources(urls),
            }
        ),
        unsupported_claims=_claim_dimension(claim_audit),
    )
    return _result(task_id, hashes, dimensions, claim_audit)


def score(task_id: str, artifacts):
    if task_id not in SUPPORTED_TASKS:
        raise ValueError("knowledge-pilot-v2.1 supports D01 and D03 only")
    hashes = {}
    try:
        answer, hashes = v2._read_answer(artifacts)
    except OverflowError:
        result = v2.score(task_id, artifacts)
        result["scorer_version"] = SCORER_VERSION
        result["provenance"] = _provenance()
        return result
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return {
            "status": "candidate_error",
            "scorer_version": SCORER_VERSION,
            "task_id": task_id,
            "reason": "invalid_json_answer",
            "passed": None,
            "total": None,
            "fully_correct": None,
            "overall_score": None,
            "dimensions": {},
            "artifacts": hashes,
            "provenance": _provenance(),
        }
    if not isinstance(answer, dict):
        answer = {}
    return _score_d(task_id, answer, hashes)
