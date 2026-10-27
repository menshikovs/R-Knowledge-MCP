"""Offline checks for the versioned benchmark source catalog and prompt exporter."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from benchmarks.codex_r.expansion import registry


def test_registry_imports_all_source_specs_and_counts_by_suite():
    catalog = registry.build_registry()

    assert len(catalog["tasks"]) == 148
    assert {item["suite"]: item["specification_count"] for item in catalog["suites"]} == {
        "beginner": 20,
        "ggplot": 41,
        "ecosystem": 37,
        "ecosystem_addon": 25,
        "anova": 15,
        "hard_blueprint": 10,
    }
    assert len({item["id"] for item in catalog["tasks"]}) == 148
    assert all(item["candidate_prompt"].strip() for item in catalog["tasks"])
    assert catalog["existing_pilot_environment"] == {
        "r": "4.5.2",
        "bioconductor": "3.22",
        "lockfile": "configs/renv.lock",
        "ggplot2": "4.0.3",
    }
    assert {tuple(item["affected_tasks"]) for item in catalog["known_source_version_gaps"]} == {
        ("ADDON-C09",),
        ("ECO-GP01", "ECO-GP02", "ADDON-C02"),
    }


def test_hard_blueprint_mapping_is_explicit_and_does_not_overstate_revalidation():
    catalog = registry.build_registry()
    mapped = {
        item["source_id"]: item for item in catalog["tasks"] if item["status"] == "mapped_existing"
    }

    assert set(mapped) == {"H01", "H04", "H10"}
    assert mapped["H04"]["mapping"]["match"] == "semantic_with_package_substitution"
    assert mapped["H04"]["mapping"]["adaptation"]
    assert all(
        item["validation_state"] == "reported_offline_validated_2026-10-24_not_replayed"
        for item in mapped.values()
    )
    summary = registry.audit_summary(catalog)
    assert summary["new_r_tasks_offline_validated_in_this_change"] == 0
    assert summary["gross_inventory_if_all_source_specs_are_implemented_plus_legacy_r_tasks"] == 160
    assert summary["verified_unique_inventory"] is None
    assert summary["minimum_additional_unique_tasks_for_240_if_all_inventory_is_distinct"] == 80


def test_legacy_crosswalk_keeps_thematic_links_separate_from_duplicates():
    catalog = registry.build_registry()
    crosswalk = catalog["legacy_r01_r12_crosswalk"]

    assert [item["task_id"] for item in crosswalk] == [f"R{i:02d}" for i in range(1, 13)]
    assert crosswalk[3]["thematic_source_candidates"] == ["GGP-R02"]
    assert all(
        item["deduplication_status"] == "not_verified; thematic links are not duplicates"
        for item in crosswalk
    )


def test_registry_rejects_private_answer_key_sources():
    catalog = registry.build_registry()
    invalid = copy.deepcopy(catalog)
    invalid["tasks"][0]["source_document"] = "private/README_ANSWERS.md"

    with pytest.raises(registry.RegistryError, match="Non-public source"):
        registry.validate_registry(invalid)


def test_hard_blueprint_exports_only_the_agent_visible_contract():
    catalog = registry.build_registry()
    hard_tasks = [task for task in catalog["tasks"] if task["suite"] == "hard_blueprint"]

    assert len(hard_tasks) == 10
    assert all("**Agent-visible contract:**" in task["candidate_prompt"] for task in hard_tasks)
    assert all("**Hidden verification:**" not in task["candidate_prompt"] for task in hard_tasks)


def test_checked_in_json_artifacts_match_the_current_public_sources():
    catalog = registry.build_registry()
    root = registry.REPO_ROOT

    assert json.loads((root / registry.REGISTRY_PATH).read_text(encoding="utf-8")) == catalog
    assert json.loads((root / registry.MAPPING_PATH).read_text(encoding="utf-8")) == (
        registry.source_mapping(catalog)
    )
    assert json.loads((root / registry.AUDIT_PATH).read_text(encoding="utf-8")) == (
        registry.audit_summary(catalog)
    )


def test_prompt_export_contains_only_the_requested_public_task(tmp_path):
    catalog = registry.build_registry()
    task = next(item for item in catalog["tasks"] if item["id"] == "ADDON-C09")
    destination = tmp_path / "candidate-task"
    fake_repo = tmp_path / "source-repo"
    source_root = registry.REPO_ROOT / registry.SOURCE_ROOT
    (fake_repo / registry.SOURCE_ROOT).mkdir(parents=True)
    shutil.copy2(source_root / "SOURCE_MANIFEST.json", fake_repo / registry.SOURCE_ROOT)
    for group in registry.SOURCE_GROUPS:
        source = source_root / Path(*group["source"].split("/"))
        target = fake_repo / registry.SOURCE_ROOT / Path(*group["source"].split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    benchmark_root = fake_repo / "benchmarks/codex_r"
    (benchmark_root / "configs").mkdir(parents=True)
    shutil.copy2(
        registry.REPO_ROOT / "benchmarks/codex_r/manifest.json",
        benchmark_root / "manifest.json",
    )
    shutil.copy2(
        registry.REPO_ROOT / "benchmarks/codex_r/configs/renv.lock",
        benchmark_root / "configs/renv.lock",
    )
    hard_source = registry.REPO_ROOT / "benchmarks/codex_r/hard"
    hard_target = benchmark_root / "hard"
    hard_target.mkdir(parents=True)
    shutil.copy2(hard_source / "manifest.json", hard_target / "manifest.json")
    for task_id in ("H01", "H04", "H10"):
        for relative in (
            f"tasks/{task_id}/prompt.md",
            f"tasks/{task_id}/metadata.json",
            f"verifier/{task_id}.R",
        ):
            target = hard_target / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hard_source / relative, target)
    # pytest's Windows temp root is under the checkout; this synthetic repository
    # keeps the exporter boundary test inside the writable workspace.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(registry, "REPO_ROOT", fake_repo)

    try:
        result = registry.export_candidate_prompt(task["id"], destination)
    finally:
        monkeypatch.undo()

    assert set(path.name for path in destination.iterdir()) == {"TASK.md"}
    assert (destination / "TASK.md").read_text(encoding="utf-8") == task["candidate_prompt"]
    assert result["task_id"] == "ADDON-C09"
    assert "Reference Solutions" not in (destination / "TASK.md").read_text(encoding="utf-8")
    assert "private/" not in json.dumps(task, ensure_ascii=False)


def test_prompt_export_rejects_unknown_or_in_repository_destinations(tmp_path):
    with pytest.raises(registry.RegistryError, match="Unknown expansion task"):
        registry.export_candidate_prompt("PRIVATE-A01", tmp_path / "unknown")

    with pytest.raises(registry.RegistryError, match="outside the repository"):
        registry.export_candidate_prompt(
            "BEGINNER-001", registry.REPO_ROOT / "candidate-export-test"
        )
