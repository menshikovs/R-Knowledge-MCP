"""Version-isolated, offline D/E evaluator for the tool-value benchmark.

The evaluator consumes only bounded candidate JSON plus the local frozen facts used by
knowledge_pilot. It never reads candidate workspaces beyond ``answer.json`` and never uses
network or model calls.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from benchmarks.codex_r import knowledge_pilot as pilot
from benchmarks.codex_r.runner import bench

SCORER_VERSION = "knowledge-pilot-v2"
CONTRACTS = pilot.PILOT / "contracts" / "v2"
MAX_ANSWER_BYTES = pilot.MAX_ANSWER_BYTES
OFFICIAL_HOSTS = frozenset({"bioconductor.org", "cran.r-project.org", "stat.ethz.ch"})
PACKAGE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9.]{0,99}\Z")
VERSION = re.compile(r"[0-9]+(?:\.[0-9A-Za-z-]+)*\Z")
SAFE_URL_CREDENTIAL = re.compile(
    r"(?i)(?:token|api.?key|access.?token|secret|password)=|sk-[a-z0-9_-]{8,}"
)


def contract_path(task_id: str) -> Path:
    if task_id not in {"D01", "D02", "D03", "E01", "E04", "E05"}:
        raise ValueError("knowledge-pilot-v2 supports D/E JSON tasks only")
    return bench.safe_file(CONTRACTS, f"{task_id}.schema.json")


def contract_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(CONTRACTS.glob("*.schema.json")):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def evaluator_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non_json_constant")


def _read_answer(artifacts):
    source = bench.safe_file(Path(artifacts), "answer.json")
    if source.stat().st_size > MAX_ANSWER_BYTES:
        raise OverflowError("answer_too_large")
    raw = source.read_bytes()
    answer = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_no_duplicate_keys,
        parse_constant=_reject_constant,
    )
    return answer, {"answer.json": hashlib.sha256(raw).hexdigest()}


def _matches(value, schema, root_schema):
    """Small closed implementation of the JSON Schema keywords used by public contracts."""
    if "$ref" in schema:
        reference = schema["$ref"]
        if not reference.startswith("#/$defs/"):
            return False
        schema = root_schema.get("$defs", {}).get(reference.removeprefix("#/$defs/"), {})
        return _matches(value, schema, root_schema)
    if "oneOf" in schema:
        return sum(_matches(value, option, root_schema) for option in schema["oneOf"]) == 1
    expected = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
    }
    if expected in type_checks and not type_checks[expected](value):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
        if schema.get("format") == "uri":
            try:
                parts = urlsplit(value)
            except ValueError:
                return False
            if not parts.scheme or not parts.netloc:
                return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 1 << 30):
            return False
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(
            value
        ):
            return False
        if "items" in schema and not all(
            _matches(item, schema["items"], root_schema) for item in value
        ):
            return False
    if isinstance(value, dict):
        if len(value) < schema.get("minProperties", 0):
            return False
        if any(key not in value for key in schema.get("required", [])):
            return False
        properties = schema.get("properties", {})
        if any(
            key not in properties and schema.get("additionalProperties") is False for key in value
        ):
            return False
        for key, item in value.items():
            if key in properties and not _matches(item, properties[key], root_schema):
                return False
            additional = schema.get("additionalProperties")
            if key not in properties and isinstance(additional, dict):
                if not _matches(item, additional, root_schema):
                    return False
    return True


def schema_valid(task_id: str, answer) -> bool:
    contract = json.loads(contract_path(task_id).read_text(encoding="utf-8"))
    return _matches(answer, contract, contract)


def _dimension(
    checks: dict[str, bool | None], *, unsupported=False, applicable=True, evaluated=True
):
    known = [value for value in checks.values() if type(value) is bool]
    if not evaluated:
        status = "not_evaluated"
    elif not applicable:
        status = "not_applicable"
    elif unsupported or any(value is None for value in checks.values()):
        status = "unsupported"
    elif all(known):
        status = "pass"
    else:
        status = "fail"
    return {
        "status": status,
        "passed": sum(value is True for value in known) if applicable and evaluated else None,
        "total": len(known) if applicable and evaluated else None,
        "checks": {
            name: "unsupported" if value is None else "pass" if value else "fail"
            for name, value in checks.items()
        },
    }


def _urls(answer):
    sources = answer.get("sources") if isinstance(answer, dict) else None
    if not isinstance(sources, list):
        return []
    result = []
    for source in sources[:32]:
        value = source.get("url") if isinstance(source, dict) else source
        if isinstance(value, str):
            result.append(value)
    return result


def _official_sources(urls):
    if not urls:
        return False
    for url in urls:
        if len(url) > 512 or SAFE_URL_CREDENTIAL.search(url):
            return False
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        try:
            has_port = parts.port is not None
        except ValueError:
            return False
        if (
            parts.scheme != "https"
            or parts.hostname not in OFFICIAL_HOSTS
            or parts.username is not None
            or parts.password is not None
            or has_port
            or parts.query
            or parts.fragment
        ):
            return False
    return True


def _repository(value, release):
    if value == "CRAN":
        return "CRAN"
    if value in {"Bioconductor", f"Bioconductor {release}"}:
        return f"Bioconductor {release}"
    return value


def _package_map(value, release):
    if isinstance(value, dict):
        result = {}
        for name, item in value.items():
            if isinstance(item, dict):
                result[name] = {
                    "version": item.get("version"),
                    "repository": _repository(item.get("repository", item.get("source")), release),
                }
        return result
    if isinstance(value, list):
        return {
            item["name"]: {
                "version": item.get("version"),
                "repository": _repository(item.get("repository", item.get("source")), release),
            }
            for item in value
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
    return {}


def _edge_list(edges):
    if not isinstance(edges, list):
        return []
    normalized = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        minimum = edge.get("minimum_version")
        if minimum is None:
            constraint = edge.get("constraint")
            match = re.fullmatch(r">=\s*([0-9]+(?:\.[0-9]+)*)", constraint or "")
            minimum = match.group(1) if match else None
        normalized.append(
            {
                "package": edge.get("package"),
                "depends_on": edge.get("depends_on"),
                "minimum_version": minimum,
            }
        )
    return normalized


def _result(task_id, hashes, dimensions, *, unsupported_claims=False):
    substantive = [
        dimensions[name]["status"]
        for name in (
            "factual_correctness",
            "version_repository_identity",
            "dependency_correctness",
            "source_quality",
        )
        if name in dimensions
    ]
    unsupported = unsupported_claims or "unsupported" in substantive
    failed = "fail" in substantive or dimensions["schema_validity"]["status"] == "fail"
    fully_correct = False if failed else None if unsupported else True
    status = "unsupported_for_automatic_scoring" if unsupported else "scored"
    return {
        "status": status,
        "scorer_version": SCORER_VERSION,
        "task_id": task_id,
        "passed": None,
        "total": None,
        "fully_correct": fully_correct,
        "overall_score": None,
        "dimensions": dimensions,
        "unsupported_claims_present": unsupported,
        "artifacts": hashes,
    }


def _score_d(task_id, answer, hashes):
    recommendations = answer.get("recommendations") if isinstance(answer, dict) else None
    recommendation = (
        recommendations[0] if isinstance(recommendations, list) and recommendations else {}
    )
    package = recommendation.get("package") if isinstance(recommendation, dict) else None
    known = bench.read_json(bench.safe_file(pilot.PILOT / "verifier", "candidates.json"))[task_id]
    facts = known.get(package)
    rationale = answer.get("rationale") if isinstance(answer, dict) else None
    schema_ok = schema_valid(task_id, answer)
    dimensions = {"schema_validity": _dimension({"public_contract": schema_ok})}
    urls = [recommendation.get("source_url"), recommendation.get("documentation_url")]
    if not schema_ok:
        dimensions.update(
            factual_correctness=_dimension({}, evaluated=False),
            version_repository_identity=_dimension({}, evaluated=False),
            dependency_correctness=_dimension({}, applicable=False),
            source_quality=_dimension({}, evaluated=False),
        )
        return _result(task_id, hashes, dimensions)
    if facts is None:
        dimensions.update(
            factual_correctness=_dimension(
                {"task_fit_and_documented_limits": None}, unsupported=True
            ),
            version_repository_identity=_dimension(
                {"package_version": None, "repository": None}, unsupported=True
            ),
            dependency_correctness=_dimension({}, applicable=False),
            source_quality=_dimension(
                {"official_source_and_documentation": None}, unsupported=True
            ),
            unsupported_claims=_dimension({"candidate_in_frozen_evidence": None}, unsupported=True),
        )
        return _result(task_id, hashes, dimensions, unsupported_claims=True)
    frozen = pilot.official_resources()[task_id][package]
    resources = {kind: pilot._resource_urls(frozen, kind) for kind in ("source", "documentation")}
    supplied_features = set(recommendation.get("feature_ids", []))
    supplied_caveats = set(recommendation.get("caveat_ids", []))
    unfrozen_claims = bool(
        supplied_features - set(facts["required_features"])
        or supplied_caveats - set(facts["required_caveats"])
    )
    dimensions.update(
        factual_correctness=_dimension(
            {
                "r_version": answer.get("r_version") == pilot.manifest()["environment"]["r"],
                "documented_features": set(facts["required_features"]) <= supplied_features,
                "documented_limits": set(facts["required_caveats"]) <= supplied_caveats,
                "rationale_present": isinstance(rationale, str) and len(rationale.strip()) >= 40,
            }
        ),
        version_repository_identity=_dimension(
            {
                "package_version": recommendation.get("version") == facts["version"],
                "repository": recommendation.get("source_url")
                in pilot._resource_urls(frozen, "source"),
            }
        ),
        dependency_correctness=_dimension({}, applicable=False),
        source_quality=_dimension(
            {
                "official_source_url": recommendation.get("source_url") in resources["source"],
                "official_documentation_url": recommendation.get("documentation_url")
                in resources["documentation"],
                "source_shapes_are_official": _official_sources(urls),
            }
        ),
        unsupported_claims=_dimension(
            {"candidate_claims_in_frozen_evidence": not unfrozen_claims},
            unsupported=unfrozen_claims,
        ),
    )
    return _result(task_id, hashes, dimensions, unsupported_claims=unfrozen_claims)


def _score_e01(answer):
    release = answer.get("bioconductor")
    raw_packages = answer.get("packages")
    packages = _package_map(raw_packages, release)
    package_counts = {}
    if isinstance(raw_packages, list):
        for item in raw_packages:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                package_counts[item["name"]] = package_counts.get(item["name"], 0) + 1
    else:
        package_counts = {name: 1 for name in packages}
    edges = _edge_list(answer.get("dependency_edges"))
    required_packages = {
        "DESeq2": {"version": "1.50.2", "repository": "Bioconductor 3.22"},
        "SummarizedExperiment": {
            "version": "1.40.0",
            "repository": "Bioconductor 3.22",
        },
        "ggplot2": {"version": "4.0.3", "repository": "CRAN"},
    }
    expected_edges = {
        ("DESeq2", "SummarizedExperiment"): "1.1.6",
        ("DESeq2", "ggplot2"): "3.4.0",
    }
    edge_values = {}
    for edge in edges:
        key = (edge["package"], edge["depends_on"])
        edge_values.setdefault(key, []).append(edge["minimum_version"])
    edge_map = {key: values[-1] for key, values in edge_values.items()}
    extra_packages = set(packages) - set(required_packages)
    extra_edges = set(edge_map) - set(expected_edges)
    changed_fields = answer.get("changed_fields", [])
    changed_fields = [changed_fields] if isinstance(changed_fields, str) else changed_fields
    checks = {
        "release_conflict_identified": answer.get("classification") == "incompatible",
        "minimal_runtime_alignment": answer.get("r_version") == "4.5.2" and release == "3.22",
        "minimal_change_set": set(changed_fields) == {"r_version"},
        "rationale_present": len(answer.get("rationale", "").strip()) >= 30,
    }
    return {
        "factual_correctness": checks,
        "version_repository_identity": {
            f"{name}_identity": packages.get(name) == expected and package_counts.get(name) == 1
            for name, expected in required_packages.items()
        },
        "dependency_correctness": {
            f"{source}_minimum_{dependency}": edge_values.get((source, dependency)) == [minimum]
            for (source, dependency), minimum in expected_edges.items()
        },
        "unsupported_claims": bool(extra_packages or extra_edges),
    }


def _score_e04(answer):
    release = answer.get("bioconductor")
    repositories = answer.get("packages")
    package_counts = {}
    if isinstance(repositories, list):
        for item in repositories:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                package_counts[item["name"]] = package_counts.get(item["name"], 0) + 1
        repositories = {
            item.get("name"): item.get("repository")
            for item in repositories
            if isinstance(item, dict)
        }
    repositories = repositories if isinstance(repositories, dict) else {}
    if not package_counts:
        package_counts = {name: 1 for name in repositories}
    repositories = {key: _repository(value, release) for key, value in repositories.items()}
    versions = answer.get("versions") if isinstance(answer.get("versions"), dict) else {}
    edges = _edge_list(answer.get("dependency_edges"))
    edge_values = [
        item.get("minimum_version")
        for item in edges
        if item.get("package") == "DESeq2" and item.get("depends_on") == "SummarizedExperiment"
    ]
    strategy = answer.get("install_strategy")
    strategy_text = " ".join(strategy) if isinstance(strategy, list) else strategy or ""
    sources = _urls(answer)
    required_package_names = {"DESeq2", "SummarizedExperiment", "BiocGenerics", "ggplot2"}
    extra_packages = (set(repositories) | set(versions)) - required_package_names
    extra_edges = len(edges) > 1
    return {
        "factual_correctness": {
            "r_and_release_identity": answer.get("r_version") == "4.5.2" and release == "3.22",
            "repository_aware_strategy": "BiocManager::install" in strategy_text
            and "install.packages" in strategy_text
            and "CRAN" in strategy_text,
            "installation_not_claimed_as_tested": not bool(
                re.search(
                    r"(?i)\b(?:tested|successfully installed|installation succeeded)\b",
                    answer.get("rationale", ""),
                )
            ),
            "rationale_present": len(answer.get("rationale", "").strip()) >= 30,
        },
        "version_repository_identity": {
            "DESeq2": repositories.get("DESeq2") == "Bioconductor 3.22"
            and versions.get("DESeq2") == "1.50.2"
            and package_counts.get("DESeq2") == 1,
            "SummarizedExperiment": repositories.get("SummarizedExperiment") == "Bioconductor 3.22"
            and versions.get("SummarizedExperiment") == "1.40.0"
            and package_counts.get("SummarizedExperiment") == 1,
            "BiocGenerics": repositories.get("BiocGenerics") == "Bioconductor 3.22"
            and versions.get("BiocGenerics") == "0.56.0"
            and package_counts.get("BiocGenerics") == 1,
            "ggplot2": repositories.get("ggplot2") == "CRAN"
            and versions.get("ggplot2") == "4.0.3"
            and package_counts.get("ggplot2") == 1,
        },
        "dependency_correctness": {
            "DESeq2_to_SummarizedExperiment_minimum": edge_values == ["1.1.6"]
        },
        "unsupported_claims": bool(extra_packages or extra_edges),
        "source_urls": sources,
    }


def _score_e05(answer):
    raw_cases = answer.get("cases")
    case_counts = {}
    if isinstance(raw_cases, list):
        for item in raw_cases:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                case_counts[item["id"]] = case_counts.get(item["id"], 0) + 1
        cases = {
            item.get("id"): item.get("classification")
            for item in raw_cases
            if isinstance(item, dict)
        }
    else:
        cases = raw_cases if isinstance(raw_cases, dict) else {}
        case_counts = {name: 1 for name in cases}
    positive = answer.get("positive_package")
    if isinstance(positive, str):
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9.]*)@([0-9]+(?:\.[0-9A-Za-z-]+)*)", positive)
        positive = {"name": match.group(1), "version": match.group(2)} if match else {}
    positive = positive if isinstance(positive, dict) else {}
    extra_cases = set(cases) - {
        "release_322_r452",
        "release_322_r443",
        "unlisted_package_version",
    }
    return {
        "factual_correctness": {
            "r452_with_release_322": cases.get("release_322_r452") == "compatible"
            and case_counts.get("release_322_r452") == 1,
            "r443_with_release_322": cases.get("release_322_r443") == "incompatible"
            and case_counts.get("release_322_r443") == 1,
            "unlisted_package_stays_unknown": cases.get("unlisted_package_version") == "unverified"
            and case_counts.get("unlisted_package_version") == 1,
        },
        "version_repository_identity": {
            "positive_package_identity": positive == {"name": "DESeq2", "version": "1.50.2"}
        },
        "dependency_correctness": {},
        "unsupported_claims": bool(extra_cases),
        "source_urls": _urls(answer),
    }


def score(task_id: str, artifacts):
    """Return separately scored dimensions; never collapse unknown facts into a pass/fail."""
    hashes = {}
    try:
        answer, hashes = _read_answer(artifacts)
    except OverflowError:
        return {
            "status": "candidate_error",
            "scorer_version": SCORER_VERSION,
            "task_id": task_id,
            "reason": "answer_too_large",
            "passed": None,
            "total": None,
            "fully_correct": None,
            "overall_score": None,
            "dimensions": {},
            "artifacts": hashes,
        }
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
        }
    schema_ok = schema_valid(task_id, answer)
    if not isinstance(answer, dict):
        answer = {}
    dimensions = {"schema_validity": _dimension({"public_contract": schema_ok})}
    if not schema_ok:
        dimensions.update(
            factual_correctness=_dimension({}, evaluated=False),
            version_repository_identity=_dimension({}, evaluated=False),
            dependency_correctness=_dimension(
                {}, applicable=task_id in {"E01", "E04"}, evaluated=False
            ),
            source_quality=_dimension({}, evaluated=False),
            unsupported_claims=_dimension({}, evaluated=False),
        )
        return _result(task_id, hashes, dimensions)
    if task_id.startswith("D"):
        return _score_d(task_id, answer, hashes)
    scored = (
        _score_e01(answer)
        if task_id == "E01"
        else _score_e04(answer)
        if task_id == "E04"
        else _score_e05(answer)
    )
    sources = scored.pop("source_urls") if "source_urls" in scored else _urls(answer)
    source_scope = _official_sources(sources) and any(
        "3.22" in url or "release-announcements" in url for url in sources
    )
    dimensions.update(
        factual_correctness=_dimension(scored["factual_correctness"]),
        version_repository_identity=_dimension(scored["version_repository_identity"]),
        dependency_correctness=_dimension(
            scored["dependency_correctness"], applicable=task_id in {"E01", "E04"}
        ),
        source_quality=_dimension({"official_sources_in_scope": source_scope}),
        unsupported_claims=_dimension(
            {"no_additional_unfrozen_claims": not scored["unsupported_claims"]},
            unsupported=scored["unsupported_claims"],
        ),
    )
    return _result(task_id, hashes, dimensions, unsupported_claims=scored["unsupported_claims"])
