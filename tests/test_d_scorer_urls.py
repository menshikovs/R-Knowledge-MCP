"""D scorer v2: frozen official CRAN URLs, reproducible offline, strict on identity."""

import hashlib
import json
import socket

import pytest

from benchmarks.codex_r import knowledge_pilot as pilot

CLIMENU = "https://cran.r-project.org"
D01_B_ANSWER = {
    "r_version": "4.5.2",
    "rationale": "climenu directly provides keyboard driven single and checkbox multi-select, "
    "and named choices return stable values separately from displayed labels.",
    "recommendations": [
        {
            "package": "climenu",
            "version": "0.2.0",
            "source_url": "https://cran.r-project.org/src/contrib/climenu_0.2.0.tar.gz",
            "documentation_url": (
                "https://cran.r-project.org/web/packages/climenu/refman/climenu.html"
            ),
            "feature_ids": ["keyboard_single_multi_select", "stable_return_values"],
            "caveat_ids": ["menu_focused"],
        }
    ],
}
D01_A_ANSWER = {
    "r_version": "4.5.2",
    "rationale": "termr fits a compact interactive terminal menu with keyboard navigation, "
    "headless app testing and values returned independently of display labels.",
    "recommendations": [
        {
            "package": "termr",
            "version": "0.1.0",
            "source_url": "https://cran.r-project.org/src/contrib/termr_0.1.0.tar.gz",
            "documentation_url": "https://cran.r-project.org/web/packages/termr/termr.pdf",
            "feature_ids": [
                "reactive_terminal_ui",
                "headless_app_tests",
                "keyboard_single_multi_select",
                "stable_return_values",
            ],
            "caveat_ids": ["real_terminal_required", "some_apis_experimental", "menu_focused"],
        }
    ],
}


def _score(answer, tmp_path, task_id="D01"):
    workspace = tmp_path / f"answer-{len(list(tmp_path.iterdir()))}"
    workspace.mkdir()
    (workspace / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
    return pilot.score(task_id, workspace, "unused-for-json-scorer")


def _with(answer, **changes):
    recommendation = {**answer["recommendations"][0], **changes}
    return {**answer, "recommendations": [recommendation]}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the D scorer must not open connections")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_d01_b_climenu_with_existing_official_urls_now_passes(tmp_path):
    result = _score(D01_B_ANSWER, tmp_path)
    assert result["fully_correct"] is True and result["passed"] == result["total"] == 4
    assert result["failed_checks"] == []
    assert result["scorer_version"] == pilot.D_SCORER_VERSION == "d-recommendation-2"


def test_d01_a_termr_0_1_0_with_nonexistent_archive_still_fails(tmp_path):
    result = _score(D01_A_ANSWER, tmp_path)
    assert result["passed"] == 2 and result["fully_correct"] is False
    assert set(result["failed_checks"]) == {
        "accepted_package_and_version",
        "official_source_and_docs",
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://cran.r-project.org/package=climenu",
        "https://cran.r-project.org/web/packages/climenu/index.html",
        "https://cran.r-project.org/src/contrib/climenu_0.2.0.tar.gz",
    ],
)
@pytest.mark.parametrize(
    "documentation",
    [
        "https://cran.r-project.org/web/packages/climenu/climenu.pdf",
        "https://cran.r-project.org/web/packages/climenu/refman/climenu.html",
        "https://stat.ethz.ch/CRAN/web/packages/climenu/climenu.pdf",
        "https://stat.ethz.ch/CRAN/web/packages/climenu/refman/climenu.html",
    ],
)
def test_alternative_official_forms_are_accepted(url, documentation, tmp_path):
    answer = _with(D01_B_ANSWER, source_url=url, documentation_url=documentation)
    assert _score(answer, tmp_path)["fully_correct"] is True


def test_termr_html_refman_and_pdf_are_both_accepted(tmp_path):
    base = {
        **D01_A_ANSWER["recommendations"][0],
        "version": "1.0.1",
        "feature_ids": ["reactive_terminal_ui", "headless_app_tests", "stable_return_values"],
        "caveat_ids": ["real_terminal_required", "some_apis_experimental"],
        "source_url": "https://cran.r-project.org/src/contrib/termr_1.0.1.tar.gz",
    }
    for documentation in (
        "https://cran.r-project.org/web/packages/termr/termr.pdf",
        "https://cran.r-project.org/web/packages/termr/refman/termr.html",
        "https://stat.ethz.ch/CRAN/web/packages/termr/refman/termr.html",
    ):
        answer = {**D01_A_ANSWER, "recommendations": [{**base, "documentation_url": documentation}]}
        assert _score(answer, tmp_path)["fully_correct"] is True, documentation


def test_termr_cran_index_is_source_but_not_documentation(tmp_path):
    recommendation = {
        **D01_A_ANSWER["recommendations"][0],
        "version": "1.0.1",
        "source_url": "https://cran.r-project.org/src/contrib/termr_1.0.1.tar.gz",
        "documentation_url": "https://cran.r-project.org/web/packages/termr/index.html",
        "feature_ids": ["reactive_terminal_ui", "headless_app_tests", "stable_return_values"],
        "caveat_ids": ["real_terminal_required", "some_apis_experimental"],
    }
    answer = {**D01_A_ANSWER, "recommendations": [recommendation]}
    frozen = pilot.official_resources()["D01"]["termr"]
    source_url = recommendation["source_url"]
    package_index_url = recommendation["documentation_url"]

    # Isolate the URL conjunct: package and version already match the frozen evidence,
    # and the source archive is recognized as a source resource.
    assert recommendation["version"] == frozen["resource_version"] == "1.0.1"
    assert pilot._is_frozen_url(source_url, frozen, "source") is True
    assert pilot._is_frozen_url(package_index_url, frozen, "source") is True
    assert pilot._is_frozen_url(package_index_url, frozen, "documentation") is False

    result = _score(answer, tmp_path)
    assert result["failed_checks"] == ["official_source_and_docs"]
    assert "accepted_package_and_version: pass" in result["details"]
    assert "official_source_and_docs: fail" in result["details"]

    # The same official index is accepted as a package/source page, but documentation
    # must be one of the frozen reference manuals.
    recommendation["source_url"] = "https://cran.r-project.org/web/packages/termr/index.html"
    recommendation["documentation_url"] = "https://cran.r-project.org/web/packages/termr/termr.pdf"
    assert _score(answer, tmp_path)["fully_correct"] is True


@pytest.mark.parametrize(
    "changes",
    [
        # wrong versions, with otherwise valid URLs
        {"version": "0.1.0"},
        {"version": "0.2"},
        {"version": "1.0.1"},
        {"version": None},
        # archive of another version or from the archive tree
        {"source_url": "https://cran.r-project.org/src/contrib/climenu_0.1.0.tar.gz"},
        {
            "source_url": "https://cran.r-project.org/src/contrib/Archive/climenu/climenu_0.2.0.tar.gz"
        },
        # another package's genuine CRAN resources
        {"source_url": "https://cran.r-project.org/package=termr"},
        {"documentation_url": "https://cran.r-project.org/web/packages/termr/termr.pdf"},
        {"documentation_url": "https://cran.r-project.org/web/packages/climenu2/climenu2.pdf"},
        # CRAN-hosted but not source/documentation of this version
        {"source_url": "https://cran.r-project.org/web/checks/check_results_climenu.html"},
        {"source_url": "https://cran.r-project.org/web/packages/climenu/NEWS"},
        {"documentation_url": "https://cran.r-project.org/web/packages/climenu/vignettes/x.html"},
        {"documentation_url": "https://cran.r-project.org/web/packages/climenu/climenu.pdf?x=1"},
        {"documentation_url": "https://cran.r-project.org/web/packages/climenu/climenu.pdf#page=2"},
        # wrong scheme, host, spelling or kind of value
        {"source_url": "http://cran.r-project.org/package=climenu"},
        {"source_url": "https://cran.r-project.org.evil.test/package=climenu"},
        {"source_url": "https://evil.test/cran.r-project.org/package=climenu"},
        {"source_url": "https://user@cran.r-project.org/package=climenu"},
        {"source_url": "https://CRAN.r-project.org/package=climenu"},
        {"source_url": "https://cran.r-project.org/package=climenu "},
        {"source_url": "https://github.com/PetrCala/climenu"},
        {"documentation_url": "https://example.invalid/climenu.pdf"},
        {"documentation_url": "https://cran.r-project.org/web/packages/fake/fake.pdf"},
        {"source_url": "", "documentation_url": ""},
        {"source_url": None},
        {"source_url": ["https://cran.r-project.org/package=climenu"]},
        {"documentation_url": {"url": "https://cran.r-project.org/web/packages/climenu/x.pdf"}},
    ],
)
def test_wrong_versions_packages_and_fictitious_links_are_rejected(changes, tmp_path):
    result = _score(_with(D01_B_ANSWER, **changes), tmp_path)
    assert result["fully_correct"] is False
    failed = set(result["failed_checks"])
    if "version" in changes:
        assert {"accepted_package_and_version", "official_source_and_docs"} <= failed
    else:
        assert "official_source_and_docs" in failed


@pytest.mark.parametrize(
    "package", ["unknownpkg", "CLIMENU", "", None, ["climenu"], {"name": "climenu"}, 7]
)
def test_unknown_or_malformed_package_fails_identity_and_urls(package, tmp_path):
    result = _score(_with(D01_B_ANSWER, package=package), tmp_path)
    assert result["fully_correct"] is False
    assert {"accepted_package_and_version", "official_source_and_docs"} <= set(
        result["failed_checks"]
    )


def test_urls_valid_for_one_task_do_not_pass_another_task(tmp_path):
    answer = _with(
        D01_B_ANSWER,
        package="webfakes",
        version="1.5.0",
        feature_ids=["local_fake_server", "real_http_roundtrip"],
        caveat_ids=["server_process_required"],
    )
    assert _score(answer, tmp_path, "D02")["failed_checks"] == ["official_source_and_docs"]
    assert _score(answer, tmp_path, "D01")["fully_correct"] is False


def test_every_curated_candidate_is_in_the_frozen_allowlist():
    candidates = json.loads(
        (pilot.PILOT / "verifier" / "candidates.json").read_text(encoding="utf-8")
    )
    frozen = pilot.official_resources()
    assert set(frozen) == set(candidates)
    for task_id, packages in candidates.items():
        assert set(frozen[task_id]) == set(packages)
        for package, entry in frozen[task_id].items():
            assert entry["resource_version"] == entry["description_version"]
            assert entry["resource_version"] == packages[package]["version"]
            assert all(item["http_status"] in {200, 303} for item in entry["resources"])
            archive = f"/src/contrib/{package}_{entry['resource_version']}.tar.gz"
            assert any(item["url"].endswith(archive) for item in entry["resources"])
    pilot.manifest()  # validates URL hosts and curated-URL coverage


def test_manifest_rejects_allowlist_for_another_version_or_host(monkeypatch):
    real = pilot.official_resources()

    def altered(mutate):
        copy = json.loads(json.dumps(real))
        mutate(copy)
        monkeypatch.setattr(pilot, "official_resources", lambda: copy)
        with pytest.raises(ValueError):
            pilot.manifest()

    altered(lambda data: data["D01"]["climenu"].update(resource_version="0.1.0"))
    altered(
        lambda data: data["D01"]["climenu"]["resources"].append(
            {"kind": "source", "url": "https://evil.test/package=climenu", "http_status": 200}
        )
    )
    altered(
        lambda data: data["D01"]["climenu"]["resources"].append(
            {
                "kind": "source",
                "url": "https://cran.r-project.org/package=other",
                "http_status": 200,
            }
        )
    )
    altered(lambda data: data["D01"].pop("climenu"))


def _write_run(root):
    run = root / "20260101T000000Z-testrun"
    for trial, mode, answer, score in (
        (
            "D01-A-1",
            "without-mcp",
            D01_A_ANSWER,
            (2, ["accepted_package_and_version", "official_source_and_docs"]),
        ),
        ("D01-B-1", "with-mcp", D01_B_ANSWER, (3, ["official_source_and_docs"])),
    ):
        directory = run / trial / "artifacts"
        directory.mkdir(parents=True)
        payload = json.dumps(answer, indent=2).encode()
        (directory / "answer.json").write_bytes(payload)
        (run / trial / "result.json").write_text(
            json.dumps(
                {
                    "trial_id": trial,
                    "task": "D01",
                    "mode": mode,
                    "score": {
                        "passed": score[0],
                        "total": 4,
                        "failed_checks": score[1],
                        "details": [],
                        "artifacts": {"answer.json": hashlib.sha256(payload).hexdigest()},
                    },
                }
            ),
            encoding="utf-8",
        )
    return run


def _tree_hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_rescore_writes_separate_versioned_report_without_touching_the_run(tmp_path):
    run = _write_run(tmp_path)
    before = _tree_hashes(run)
    reports = tmp_path / "reports"
    report = pilot.rescore_run(run, reports)

    assert _tree_hashes(run) == before
    assert report["scorer_version"] == "d-recommendation-2" and report["network_used"] is False
    by_trial = {trial["trial_id"]: trial for trial in report["trials"]}
    assert (
        by_trial["D01-A-1"]["original"]["passed"],
        by_trial["D01-A-1"]["rescored"]["passed"],
    ) == (2, 2)
    assert (
        by_trial["D01-B-1"]["original"]["passed"],
        by_trial["D01-B-1"]["rescored"]["passed"],
    ) == (3, 4)
    assert by_trial["D01-B-1"]["rescored"]["failed_checks"] == []
    assert by_trial["D01-A-1"]["rescored"]["failed_checks"] == [
        "accepted_package_and_version",
        "official_source_and_docs",
    ]
    assert all(trial["answer_matches_original_record"] for trial in report["trials"])
    stem = "20260101T000000Z-testrun-d-recommendation-2-rescore"
    assert json.loads((reports / f"{stem}.json").read_text(encoding="utf-8")) == report
    assert "| D01-B-1 | climenu | 0.2.0 | 3/4 | 4/4 | - |" in (
        (reports / f"{stem}.md").read_text(encoding="utf-8")
    )


def test_rescore_flags_a_changed_answer_and_refuses_to_write_inside_the_run(tmp_path):
    run = _write_run(tmp_path)
    (run / "D01-B-1" / "artifacts" / "answer.json").write_text("{}", encoding="utf-8")
    report = pilot.rescore_run(run, tmp_path / "reports")
    changed = next(t for t in report["trials"] if t["trial_id"] == "D01-B-1")
    assert changed["answer_matches_original_record"] is False
    assert changed["rescored"]["passed"] == 0
    with pytest.raises(ValueError):
        pilot.rescore_run(run, run / "reports")
