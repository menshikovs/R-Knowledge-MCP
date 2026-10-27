"""Independent offline fixtures for the opt-in D/E scorer v2."""

import json
from types import SimpleNamespace

from benchmarks.codex_r import knowledge_pilot as pilot
from benchmarks.codex_r import knowledge_pilot_v2 as v2
from benchmarks.codex_r import run_simple

BIOC_RELEASE = "https://bioconductor.org/about/release-announcements/"
DESEQ2_DOCS = "https://bioconductor.org/packages/3.22/bioc/html/DESeq2.html"


def _score(tmp_path, task_id, answer, *, scorer="knowledge-pilot-v2"):
    path = tmp_path / f"{task_id}-{len(list(tmp_path.iterdir()))}"
    path.mkdir()
    (path / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
    return pilot.score(task_id, path, "unused", scorer_version=scorer)


def d_answer(package="termr", task_id="D01"):
    termr = {
        "package": "termr",
        "version": "1.0.1",
        "source_url": "https://cran.r-project.org/package=termr",
        "documentation_url": "https://stat.ethz.ch/CRAN/web/packages/termr/refman/termr.html",
        "feature_ids": ["reactive_terminal_ui", "headless_app_tests", "stable_return_values"],
        "caveat_ids": ["real_terminal_required", "some_apis_experimental"],
    }
    if package != "termr":
        features, caveats = {
            "D01": (["keyboard_single_multi_select"], ["menu_focused"]),
            "D02": (["request_stubbing"], ["client_coverage_varies"]),
            "D03": (["declarative_rules"], ["lightweight_rule_engine"]),
        }[task_id]
        termr.update(
            package=package,
            version="1.0",
            source_url=f"https://cran.r-project.org/package={package}",
            documentation_url=f"https://cran.r-project.org/web/packages/{package}/index.html",
            feature_ids=features,
            caveat_ids=caveats,
        )
    return {
        "r_version": "4.5.2",
        "rationale": (
            "This package fits the requested terminal interaction while keeping its documented "
            "tradeoffs visible."
        ),
        "recommendations": [termr],
    }


def e01_answer():
    return {
        "classification": "incompatible",
        "r_version": "4.5.2",
        "bioconductor": "3.22",
        "packages": [
            {"name": "DESeq2", "version": "1.50.2", "repository": "Bioconductor 3.22"},
            {"name": "SummarizedExperiment", "version": "1.40.0", "repository": "Bioconductor"},
            {"name": "ggplot2", "version": "4.0.3", "repository": "CRAN"},
        ],
        "dependency_edges": [
            {"package": "DESeq2", "depends_on": "SummarizedExperiment", "constraint": ">= 1.1.6"},
            {"package": "DESeq2", "depends_on": "ggplot2", "minimum_version": "3.4.0"},
        ],
        "changed_fields": "r_version",
        "rationale": (
            "Bioconductor 3.22 maps to R 4.5; setting R 4.5.2 fixes the release conflict "
            "while preserving package pins."
        ),
        "sources": [
            {"url": BIOC_RELEASE, "claim": "release mapping"},
            DESEQ2_DOCS,
        ],
    }


def e04_answer():
    return {
        "r_version": "4.5.2",
        "bioconductor": "3.22",
        "packages": [
            {"name": "DESeq2", "repository": "Bioconductor"},
            {"name": "SummarizedExperiment", "repository": "Bioconductor 3.22"},
            {"name": "BiocGenerics", "repository": "Bioconductor"},
            {"name": "ggplot2", "repository": "CRAN"},
        ],
        "versions": {
            "DESeq2": "1.50.2",
            "SummarizedExperiment": "1.40.0",
            "BiocGenerics": "0.56.0",
            "ggplot2": "4.0.3",
        },
        "dependency_edges": [
            {"package": "DESeq2", "depends_on": "SummarizedExperiment", "constraint": ">= 1.1.6"}
        ],
        "install_strategy": (
            "Use install.packages('BiocManager', repos='CRAN') if needed, then "
            "BiocManager::install('DESeq2') so the Bioconductor graph and CRAN dependencies "
            "are resolved by their repositories."
        ),
        "rationale": (
            "These are frozen repository metadata facts; no installation was run or claimed."
        ),
        "sources": [BIOC_RELEASE, DESEQ2_DOCS],
    }


def e05_answer():
    return {
        "cases": [
            {
                "id": "release_322_r452",
                "classification": "compatible",
                "evidence": ["release table"],
            },
            {"id": "release_322_r443", "classification": "incompatible"},
            {"id": "unlisted_package_version", "classification": "unverified"},
        ],
        "positive_package": "DESeq2@1.50.2",
        "rationale": (
            "The official release mapping supports the first two classifications; absence of "
            "the package snapshot is not evidence of incompatibility."
        ),
        "sources": [BIOC_RELEASE, DESEQ2_DOCS],
    }


def test_v2_contracts_are_public_machine_readable_and_scoped_to_export(tmp_path):
    for task_id in ("D01", "D02", "D03", "E01", "E04", "E05"):
        contract = json.loads(v2.contract_path(task_id).read_text(encoding="utf-8"))
        assert contract["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        workspace = tmp_path / task_id
        exported = pilot.prepare(task_id, workspace, "knowledge-pilot-v2")
        names = {path.relative_to(workspace).as_posix() for path in workspace.rglob("*")}
        assert names == {"TASK.md", "renv.lock", "OUTPUT_SCHEMA.json"}
        assert json.loads((workspace / "OUTPUT_SCHEMA.json").read_text()) == contract
        assert "OUTPUT_SCHEMA.json" in exported["files"]
        assert not any("verifier" in name or "metadata" in name for name in names)


def test_v2_dimensions_and_equivalent_public_shapes(tmp_path):
    d = _score(tmp_path, "D01", d_answer())
    assert d["status"] == "scored" and d["fully_correct"] is True
    assert d["overall_score"] is None and d["passed"] is None and d["total"] is None
    assert d["dimensions"]["schema_validity"]["status"] == "pass"
    assert d["dimensions"]["version_repository_identity"]["status"] == "pass"
    assert d["dimensions"]["source_quality"]["status"] == "pass"

    e01 = _score(tmp_path, "E01", e01_answer())
    assert e01["status"] == "scored" and e01["fully_correct"] is True
    assert e01["dimensions"]["dependency_correctness"]["status"] == "pass"

    e04 = _score(tmp_path, "E04", e04_answer())
    assert e04["fully_correct"] is True
    assert e04["dimensions"]["version_repository_identity"]["status"] == "pass"

    e05 = _score(tmp_path, "E05", e05_answer())
    assert e05["fully_correct"] is True
    assert e05["dimensions"]["factual_correctness"]["status"] == "pass"


def test_open_world_alternatives_are_unsupported_not_auto_failed_or_passed(tmp_path):
    for task_id, package in (("D01", "utils"), ("D02", "httptest")):
        result = _score(tmp_path, task_id, d_answer(package, task_id))
        assert result["status"] == "unsupported_for_automatic_scoring"
        assert result["fully_correct"] is None
        assert result["dimensions"]["schema_validity"]["status"] == "pass"
        assert result["dimensions"]["factual_correctness"]["status"] == "unsupported"
        assert result["dimensions"]["version_repository_identity"]["status"] == "unsupported"


def test_d_claims_outside_candidate_facts_remain_unsupported(tmp_path):
    answer = d_answer("webmockr", "D02")
    recommendation = answer["recommendations"][0]
    recommendation.update(
        version="2.2.0",
        source_url="https://cran.r-project.org/package=webmockr",
        documentation_url="https://cran.r-project.org/web/packages/webmockr/webmockr.pdf",
        feature_ids=["request_stubbing", "request_expectations", "recorded_fixtures"],
        caveat_ids=["client_coverage_varies"],
    )
    result = _score(tmp_path, "D02", answer)
    assert result["status"] == "unsupported_for_automatic_scoring"
    assert result["fully_correct"] is None
    assert result["dimensions"]["factual_correctness"]["status"] == "pass"
    assert result["dimensions"]["unsupported_claims"]["status"] == "unsupported"


def test_v2_experiment_manifest_records_scorer_and_contract_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        run_simple,
        "registered_tools",
        lambda _toolset: list(run_simple.hard.manifest()["mcp"]["tools"]),
    )
    args = SimpleNamespace(
        run_id="v2-manifest-fixture",
        knowledge_pilot_scorer="knowledge-pilot-v2",
        effort="medium",
        instructions="standard",
        modes=["without-mcp", "with-mcp"],
        repetitions=1,
        timeout=60,
        executor_image="executor:test",
        scorer_image="scorer:test",
        mcp_image="mcp:test",
        runtime_versions=None,
    )
    manifest = run_simple.write_experiment_manifest(
        tmp_path, args, {"executor": "executor:test", "scorer": "scorer:test"}, ["D01"], write=False
    )
    versions = manifest["scorer_versions"]
    assert manifest["configuration_id"] == "consolidated-v2"
    assert manifest["knowledge_pilot_scorer"] == v2.SCORER_VERSION
    assert versions["knowledge_pilot_v2_evaluator_sha256"] == v2.evaluator_digest()
    assert versions["knowledge_pilot_v2_contracts_sha256"] == v2.contract_digest()
    assert manifest["task_inputs_sha256"]["D01"]["output_contract"] == pilot.bench.digest(
        v2.contract_path("D01")
    )


def test_v2_separates_bad_facts_from_contract_errors_and_flags_unknown_claims(tmp_path):
    bad_edge = e01_answer()
    bad_edge["dependency_edges"][0]["constraint"] = ">= 1.11.12"
    result = _score(tmp_path, "E01", bad_edge)
    assert result["dimensions"]["schema_validity"]["status"] == "pass"
    assert result["dimensions"]["dependency_correctness"]["status"] == "fail"
    assert result["dimensions"]["version_repository_identity"]["status"] == "pass"

    extra = e01_answer()
    extra["packages"].append({"name": "UnfrozenPackage", "version": "9.9.9", "repository": "CRAN"})
    unsupported = _score(tmp_path, "E01", extra)
    assert unsupported["status"] == "unsupported_for_automatic_scoring"
    assert unsupported["fully_correct"] is None
    assert unsupported["dimensions"]["unsupported_claims"]["status"] == "unsupported"

    malformed = d_answer()
    malformed["unexpected"] = "not part of the published contract"
    invalid = _score(tmp_path, "D01", malformed)
    assert invalid["dimensions"]["schema_validity"]["status"] == "fail"
    assert invalid["dimensions"]["factual_correctness"]["status"] == "not_evaluated"
    assert invalid["status"] == "scored" and invalid["fully_correct"] is False


def test_v2_does_not_hide_conflicting_duplicate_package_or_edge_claims(tmp_path):
    duplicate_package = e01_answer()
    duplicate_package["packages"].append(
        {"name": "DESeq2", "version": "1.50.1", "repository": "Bioconductor 3.22"}
    )
    package_result = _score(tmp_path, "E01", duplicate_package)
    assert package_result["dimensions"]["version_repository_identity"]["status"] == "fail"

    duplicate_edge = e01_answer()
    duplicate_edge["dependency_edges"].append(
        {"package": "DESeq2", "depends_on": "ggplot2", "minimum_version": "3.4.0"}
    )
    edge_result = _score(tmp_path, "E01", duplicate_edge)
    assert edge_result["dimensions"]["dependency_correctness"]["status"] == "fail"

    duplicate_case = e05_answer()
    duplicate_case["cases"].append({"id": "release_322_r452", "classification": "incompatible"})
    case_result = _score(tmp_path, "E05", duplicate_case)
    assert case_result["dimensions"]["factual_correctness"]["status"] == "fail"


def test_v2_malformed_official_url_port_is_scored_as_bad_source_not_crash(tmp_path):
    answer = e01_answer()
    answer["sources"][0] = "https://bioconductor.org:bad/about/release-announcements/"
    result = _score(tmp_path, "E01", answer)
    assert result["dimensions"]["source_quality"]["status"] == "fail"


def test_scorer_v1_is_default_and_unchanged_when_v2_is_opted_in(tmp_path):
    artifact = tmp_path / "same-answer"
    artifact.mkdir()
    (artifact / "answer.json").write_text(json.dumps(e05_answer()), encoding="utf-8")
    legacy = pilot.score("E05", artifact, "unused")
    versioned = pilot.score("E05", artifact, "unused", scorer_version="knowledge-pilot-v2")
    assert legacy["scorer_version"] == pilot.E_SCORER_VERSION
    assert "dimensions" not in legacy
    assert versioned["scorer_version"] == "knowledge-pilot-v2"
    assert "dimensions" in versioned


def test_v2_duplicate_json_keys_and_non_json_constants_fail_closed(tmp_path):
    for source in ('{"r_version":"4.5.2","r_version":"4.4.3"}', '{"r_version":NaN}'):
        workspace = tmp_path / f"bad-{len(list(tmp_path.iterdir()))}"
        workspace.mkdir()
        (workspace / "answer.json").write_text(source, encoding="utf-8")
        result = pilot.score("D01", workspace, "unused", scorer_version="knowledge-pilot-v2")
        assert result["status"] == "candidate_error"
        assert result["reason"] == "invalid_json_answer"
