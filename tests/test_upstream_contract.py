"""The nightly contract runner, exercised offline against the real-archive corpus.

Passing, failing (a real regression) and inconclusive (upstream outage) outcomes must be
distinguishable, and the machine-readable report must be complete and free of anything sensitive.
"""

import json

from archive_corpus import corpus_service

from cran_knowledge_mcp import http as http_module
from cran_knowledge_mcp import upstream_contract as contract

SAMPLE = (("cran", "cluster"), ("cran", "R6"), ("bioconductor", "BiocGenerics"))


async def test_passes_on_authentic_archives_and_records_upstream_identity():
    async with corpus_service() as (api, _, _):
        report = await contract.run(api, SAMPLE)
    assert report["outcome"] == "pass" and contract.exit_status(report) == 0
    assert report["summary"] == {"pass": 3, "fail": 0, "inconclusive": 0}
    by_package = {r["package"]: r for r in report["results"]}
    assert by_package["cluster"]["package_version"] == "2.1.8.3"
    assert by_package["BiocGenerics"]["bioc_version"] == "3.23"
    for result in report["results"]:
        assert len(result["archive_sha256"]) == 64 and result["source_urls"]
        assert all(result["discovery_checked_at"]) and result["seconds"] >= 0
        assert all(item["ok"] for item in result["checks"]), result["checks"]
    names = {item["name"] for item in by_package["cluster"]["checks"]}
    assert {"historical_version_refused:docs", "equivalent_spelling_accepted"} <= names
    assert "cluster_mixed_encoding_resolved" in names


async def test_report_is_machine_readable_and_contains_no_environment_values(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-appear-0123456789")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_must_never_appear_0123456789")
    async with corpus_service() as (api, _, _):
        report = await contract.run(api, SAMPLE[:1])
    text = json.dumps(report)
    assert json.loads(text) == report
    assert report["git_sha"] == "a" * 40 and report["schema_version"] == contract.SCHEMA_VERSION
    assert {"started_utc", "finished_utc", "python", "sample", "summary", "outcome"} <= set(report)
    assert "must-never-appear" not in text and "ghs_" not in text
    assert "### Upstream contract: pass" in contract.markdown_summary(report)


async def test_an_upstream_outage_is_inconclusive_not_a_failure():
    async with corpus_service() as (api, routes, _):
        routes.pop(("cran.r-project.org", "/src/contrib/R6_2.6.1.tar.gz"))
        report = await contract.run(api, SAMPLE)
    assert report["outcome"] == "inconclusive" and contract.exit_status(report) == 2
    broken = next(r for r in report["results"] if r["package"] == "R6")
    assert broken["status"] == "inconclusive" and broken["inconclusive"]["code"] == "not_found"
    assert {r["status"] for r in report["results"] if r["package"] != "R6"} == {"pass"}


async def test_a_package_that_vanished_upstream_is_inconclusive():
    async with corpus_service() as (api, _, _):
        report = await contract.run(api, (("cran", "NoSuchPackageAnywhere"),))
    (result,) = report["results"]
    assert result["status"] == "inconclusive"
    assert result["inconclusive"]["code"] in {"package_not_found", "not_found"}


async def test_a_regression_is_a_failure_with_the_violated_invariant_named(monkeypatch):
    """Re-introduce KC-003 (strict string comparison) and the contract must notice."""
    async with corpus_service() as (api, _, _):
        provider = await api.provider("cran")
        original = provider.list_package_functions

        async def strict(
            package, query=None, limit=20, offset=0, package_version=None, snapshot=None
        ):
            if package_version is not None and package_version != "2.1.8.3":
                from cran_knowledge_mcp.errors import KnowledgeError

                raise KnowledgeError("requested_version_unavailable", "strict string comparison")
            return await original(package, query, limit, offset, package_version, snapshot)

        monkeypatch.setattr(provider, "list_package_functions", strict)
        report = await contract.run(api, SAMPLE[:1])
    assert report["outcome"] == "fail" and contract.exit_status(report) == 1
    checks = {i["name"]: i for i in report["results"][0]["checks"]}
    assert report["results"][0]["status"] == "fail"
    # The strict mutant still refuses, but without the contract's reason/substituted fields.
    assert not checks["historical_version_refused:discovery"]["ok"]
    assert checks["historical_version_refused:docs"]["ok"]


async def test_a_misclassified_harmless_diagnostic_fails_the_contract(monkeypatch):
    """Re-introduce KC-002: useDynLib registration downgrades the package again."""
    from cran_knowledge_mcp import parsers

    monkeypatch.setitem(parsers.DIAGNOSTIC_CLASS, "namespace_native_library_declared", "incomplete")
    async with corpus_service() as (api, _, _):
        report = await contract.run(api, SAMPLE[:1])
    assert report["outcome"] == "fail"
    failed = {i["name"] for i in report["results"][0]["checks"] if not i["ok"]}
    assert "cluster_registration_is_not_limiting" in failed


async def test_exit_codes_prefer_failure_over_outage():
    report = {"outcome": "fail", "summary": {"pass": 0, "fail": 1, "inconclusive": 1}}
    assert contract.exit_status(report) == 1


def test_runner_uses_only_the_projects_bounded_http_layer():
    assert contract.make_client is http_module.make_client
    assert contract.ALLOWED_HOSTS == {"cran.r-project.org", "bioconductor.org"}
    assert contract.PACKAGE_DEADLINE_SECONDS <= 300 and contract.MAX_PAGES <= 200
    assert len(contract.SAMPLE) <= 8


async def test_conditions_our_own_parsers_produce_are_failures_not_outages():
    """A corrupt archive points at this code's parser or limits: a failure, never inconclusive."""
    import gzip
    import hashlib

    from archive_corpus import body, entries

    (r6,) = [e for e in entries("cran") if e["package"] == "R6"]
    garbage = gzip.compress(b"this is not a tar archive")
    md5 = hashlib.md5(garbage, usedforsecurity=False).hexdigest()
    index = f"Package: R6\nVersion: {r6['version']}\nMD5sum: {md5}\nLicense: MIT\n".encode()
    extra = {
        ("cran.r-project.org", "/src/contrib/PACKAGES"): index,
        ("cran.r-project.org", f"/src/contrib/R6_{r6['version']}.tar.gz"): garbage,
    }
    assert body(r6) != garbage
    async with corpus_service(extra) as (api, _, _):
        report = await contract.run(api, (("cran", "R6"),))
    (result,) = report["results"]
    assert result["status"] == "fail" and contract.exit_status(report) == 1
    assert "invalid_source" in [i["detail"] for i in result["checks"] if not i["ok"]][0]
    assert not {"invalid_source", "source_too_large"} & contract.UPSTREAM_CODES
    assert {"source_unavailable", "rate_limited", "not_found"} <= contract.UPSTREAM_CODES
