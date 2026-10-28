"""Stage 2.5 separate, versioned scorer-calibration and reliability validation suite.

Reviews and exercises the frozen benchmark scorers (`knowledge-pilot-v2`,
`knowledge-pilot-v2.1`, `hard-v1`, and `legacy`) WITHOUT modifying any frozen
scorer, verifier, or reference file.

For each structured JSON task (`D01`, `D02`, `D03`, `E01`, `E04`, `E05`),
constructs isolated candidate `answer.json` fixtures representing:
  1. Gold reference solutions (verifying `status == "scored"` and `fully_correct is True`).
  2. Independently written valid alternatives or equivalent representations (e.g.
     array-form vs object-form in `E01`/`E04`/`E05`, `package@version` shorthand in `E05`,
     and alternative CRAN packages outside the frozen candidate list in `D01`–`D03`).
  3. Known incorrect strategies (wrong version, wrong compatibility classification,
     missing required feature/caveat claims, or claiming untested installation succeeded).
  4. Boundary cases (asserting `unknown` claims under `v2.1` vs `v2`, extra true
     packages/edges triggering `unsupported_for_automatic_scoring` under `BEN-002`,
     and malformed JSON / missing artifact handling).

Also audits the R-based verifiers (`C01`–`C05`, `B01`–`B03`, `E02`–`E03`, `H01`,
`H04`, `H10`, `R01`–`R12`) for check-count consistency, holdout separation, and
ceiling-saturation status.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from benchmarks.codex_r import knowledge_pilot, knowledge_pilot_v2, knowledge_pilot_v21
from benchmarks.codex_r.hard import suite as hard_suite
from benchmarks.codex_r.runner import bench
from benchmarks.codex_r.studies.stage2_validity_v1 import calibration

CALIBRATION_SUITE_VERSION = "stage25-scorer-calibration-v1.0"


def _run_scorer_on_json(
    scorer_fn: Any,
    task_id: str,
    payload: dict[str, Any] | str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"rkmcp-scal-{task_id}-") as tmp:
        art_dir = Path(tmp)
        text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
        (art_dir / "answer.json").write_text(text, encoding="utf-8")
        return scorer_fn(task_id, art_dir)


def build_json_scorer_probes() -> list[dict[str, Any]]:
    """Define and execute the deterministic probe matrix against frozen V2 and V2.1 scorers."""
    r_ver = knowledge_pilot.manifest()["environment"]["r"]  # "4.5.2"
    probes: list[dict[str, Any]] = []

    def add_probe(
        *,
        probe_id: str,
        task_id: str,
        scorer_name: str,
        category: str,
        description: str,
        payload: dict[str, Any] | str,
        expected_status: str,
        expected_fully_correct: bool | None,
        exposes_limitation: str | None = None,
    ) -> None:
        scorer_fn = (
            knowledge_pilot_v21.score
            if scorer_name == "knowledge-pilot-v2.1"
            else knowledge_pilot_v2.score
        )
        out = _run_scorer_on_json(scorer_fn, task_id, payload)
        passed_expectation = (
            out.get("status") == expected_status
            and out.get("fully_correct") == expected_fully_correct
        )
        probes.append(
            {
                "probe_id": probe_id,
                "task_id": task_id,
                "scorer_version": scorer_name,
                "category": category,
                "description": description,
                "observed_status": out.get("status"),
                "observed_fully_correct": out.get("fully_correct"),
                "expected_status": expected_status,
                "expected_fully_correct": expected_fully_correct,
                "expectation_met": passed_expectation,
                "exposes_limitation": exposes_limitation,
            }
        )

    # --- D01 probes (knowledge-pilot-v2.1) ---
    d01_gold_termr = {
        "r_version": r_ver,
        "rationale": (
            "termr 1.0.1 provides reactive terminal UI components, headless app test support, "
            "and stable return values while requiring a real terminal."
        ),
        "recommendations": [
            {
                "package": "termr",
                "version": "1.0.1",
                "source_url": "https://cran.r-project.org/package=termr",
                "documentation_url": "https://stat.ethz.ch/CRAN/web/packages/termr/refman/termr.html",
                "feature_ids": [
                    "reactive_terminal_ui",
                    "headless_app_tests",
                    "stable_return_values",
                ],
                "caveat_ids": ["real_terminal_required", "some_apis_experimental"],
            }
        ],
    }
    add_probe(
        probe_id="D01_v21_gold_termr",
        task_id="D01",
        scorer_name="knowledge-pilot-v2.1",
        category="reference_solution",
        description=(
            "Gold D01 answer recommending `termr` with exact required features and caveats."
        ),
        payload=d01_gold_termr,
        expected_status="scored",
        expected_fully_correct=True,
    )

    d01_gold_climenu = {
        "r_version": r_ver,
        "rationale": (
            "climenu 0.2.0 provides keyboard single/multi-select menus and stable return values "
            "with a menu-focused scope."
        ),
        "recommendations": [
            {
                "package": "climenu",
                "version": "0.2.0",
                "source_url": "https://cran.r-project.org/package=climenu",
                "documentation_url": "https://cran.r-project.org/web/packages/climenu/climenu.pdf",
                "feature_ids": ["keyboard_single_multi_select", "stable_return_values"],
                "caveat_ids": ["menu_focused"],
            }
        ],
    }
    add_probe(
        probe_id="D01_v21_valid_alternative_in_registry_climenu",
        task_id="D01",
        scorer_name="knowledge-pilot-v2.1",
        category="valid_alternative_in_registry",
        description="Second frozen candidate `climenu` in D01 registry.",
        payload=d01_gold_climenu,
        expected_status="scored",
        expected_fully_correct=True,
    )

    d01_unlisted_pkg = {
        "r_version": r_ver,
        "rationale": (
            "cli is a widely used CRAN package for terminal interfaces, semantic CLI elements, "
            "and progress reporting in R."
        ),
        "recommendations": [
            {
                "package": "cli",
                "version": "3.6.3",
                "source_url": "https://cran.r-project.org/package=cli",
                "documentation_url": "https://cran.r-project.org/web/packages/cli/cli.pdf",
                "feature_ids": ["stable_return_values"],
                "caveat_ids": ["real_terminal_required"],
            }
        ],
    }
    add_probe(
        probe_id="D01_v21_unlisted_package_cli",
        task_id="D01",
        scorer_name="knowledge-pilot-v2.1",
        category="valid_alternative_outside_frozen_set",
        description=(
            "Schema-valid D01 recommendation of CRAN `cli` (not in 2-package frozen registry)."
        ),
        payload=d01_unlisted_pkg,
        expected_status="unsupported_for_automatic_scoring",
        expected_fully_correct=None,
        exposes_limitation=(
            "BEN-002: D01 frozen registry only knows `termr` and `climenu`; "
            "any other package triggers automatic-scoring abstention."
        ),
    )

    d01_unknown_claim = {
        **d01_gold_termr,
        "recommendations": [
            {
                **d01_gold_termr["recommendations"][0],
                "feature_ids": [
                    "reactive_terminal_ui",
                    "headless_app_tests",
                    "stable_return_values",
                    "keyboard_single_multi_select",
                ],
            }
        ],
    }
    add_probe(
        probe_id="D01_v21_unknown_claim_abstention",
        task_id="D01",
        scorer_name="knowledge-pilot-v2.1",
        category="boundary_case",
        description=(
            "D01 `termr` with `keyboard_single_multi_select` "
            "(classified as `unknown` in v2.1 registry)."
        ),
        payload=d01_unknown_claim,
        expected_status="unsupported_for_automatic_scoring",
        expected_fully_correct=None,
        exposes_limitation=(
            "V2.1 abstains (`unsupported_for_automatic_scoring`) whenever a non-required "
            "claim is marked `unknown` in the frozen registry."
        ),
    )

    d01_wrong_version = {
        **d01_gold_termr,
        "recommendations": [
            {
                **d01_gold_termr["recommendations"][0],
                "version": "9.9.9",
            }
        ],
    }
    add_probe(
        probe_id="D01_v21_incorrect_version",
        task_id="D01",
        scorer_name="knowledge-pilot-v2.1",
        category="known_incorrect",
        description="D01 `termr` with fabricated version `9.9.9`.",
        payload=d01_wrong_version,
        expected_status="scored",
        expected_fully_correct=False,
    )

    # --- D02 probes (knowledge-pilot-v2) ---
    d02_gold_httptest2 = {
        "r_version": r_ver,
        "rationale": (
            "httptest2 1.2.2 provides recorded HTTP fixtures and first-class httr2 integration "
            "while being specific to httr2."
        ),
        "recommendations": [
            {
                "package": "httptest2",
                "version": "1.2.2",
                "source_url": "https://cran.r-project.org/package=httptest2",
                "documentation_url": "https://cran.r-project.org/web/packages/httptest2/httptest2.pdf",
                "feature_ids": ["recorded_fixtures", "httr2_support"],
                "caveat_ids": ["httr2_specific"],
            }
        ],
    }
    add_probe(
        probe_id="D02_v2_gold_httptest2",
        task_id="D02",
        scorer_name="knowledge-pilot-v2",
        category="reference_solution",
        description="Gold D02 answer recommending `httptest2`.",
        payload=d02_gold_httptest2,
        expected_status="scored",
        expected_fully_correct=True,
    )

    d02_unlisted_vcr = {
        "r_version": r_ver,
        "rationale": (
            "vcr is a standard CRAN package for recording and replaying HTTP test cassettes "
            "in R testthat suites."
        ),
        "recommendations": [
            {
                "package": "vcr",
                "version": "1.6.0",
                "source_url": "https://cran.r-project.org/package=vcr",
                "documentation_url": "https://cran.r-project.org/web/packages/vcr/vcr.pdf",
                "feature_ids": ["recorded_fixtures"],
                "caveat_ids": ["client_coverage_varies"],
            }
        ],
    }
    add_probe(
        probe_id="D02_v2_unlisted_package_vcr",
        task_id="D02",
        scorer_name="knowledge-pilot-v2",
        category="valid_alternative_outside_frozen_set",
        description=(
            "D02 recommendation of CRAN `vcr` "
            "(outside frozen set `{httptest2, webmockr, webfakes}`)."
        ),
        payload=d02_unlisted_vcr,
        expected_status="unsupported_for_automatic_scoring",
        expected_fully_correct=None,
        exposes_limitation=(
            "BEN-002: D02 frozen candidate list excludes `vcr` and is not "
            "supported by `knowledge-pilot-v2.1`."
        ),
    )

    # --- D03 probes (knowledge-pilot-v2.1) ---
    d03_gold_validate = {
        "r_version": r_ver,
        "rationale": (
            "validate 1.1.7 supports declarative rules, cross-record validation rules, and "
            "row-level failure reports in a lightweight rule engine."
        ),
        "recommendations": [
            {
                "package": "validate",
                "version": "1.1.7",
                "source_url": "https://cran.r-project.org/package=validate",
                "documentation_url": "https://cran.r-project.org/web/packages/validate/validate.pdf",
                "feature_ids": [
                    "declarative_rules",
                    "cross_record_rules",
                    "row_level_failure_reports",
                ],
                "caveat_ids": ["lightweight_rule_engine"],
            }
        ],
    }
    add_probe(
        probe_id="D03_v21_gold_validate",
        task_id="D03",
        scorer_name="knowledge-pilot-v2.1",
        category="reference_solution",
        description="Gold D03 answer recommending `validate`.",
        payload=d03_gold_validate,
        expected_status="scored",
        expected_fully_correct=True,
    )

    d03_gold_pointblank = {
        "r_version": r_ver,
        "rationale": (
            "pointblank 0.12.4 provides declarative rules, pipeline validation, and row-level "
            "failure reports as a broader validation framework."
        ),
        "recommendations": [
            {
                "package": "pointblank",
                "version": "0.12.4",
                "source_url": "https://cran.r-project.org/package=pointblank",
                "documentation_url": "https://cran.r-project.org/web/packages/pointblank/pointblank.pdf",
                "feature_ids": [
                    "declarative_rules",
                    "pipeline_validation",
                    "row_level_failure_reports",
                ],
                "caveat_ids": ["broader_validation_framework"],
            }
        ],
    }
    add_probe(
        probe_id="D03_v21_valid_alternative_pointblank",
        task_id="D03",
        scorer_name="knowledge-pilot-v2.1",
        category="valid_alternative_in_registry",
        description="Second frozen candidate `pointblank` in D03 registry.",
        payload=d03_gold_pointblank,
        expected_status="scored",
        expected_fully_correct=True,
    )

    d03_missing_required = {
        **d03_gold_validate,
        "recommendations": [
            {
                **d03_gold_validate["recommendations"][0],
                "feature_ids": ["declarative_rules"],
            }
        ],
    }
    add_probe(
        probe_id="D03_v21_missing_required_features",
        task_id="D03",
        scorer_name="knowledge-pilot-v2.1",
        category="known_incorrect",
        description=(
            "D03 `validate` omitting required features `cross_record_rules` "
            "and `row_level_failure_reports`."
        ),
        payload=d03_missing_required,
        expected_status="scored",
        expected_fully_correct=False,
    )

    # --- E01 probes (knowledge-pilot-v2) ---
    e01_gold_dict = {
        "classification": "incompatible",
        "r_version": "4.5.2",
        "bioconductor": "3.22",
        "packages": {
            "DESeq2": {"version": "1.50.2", "repository": "Bioconductor 3.22"},
            "SummarizedExperiment": {"version": "1.40.0", "repository": "Bioconductor 3.22"},
            "ggplot2": {"version": "4.0.3", "repository": "CRAN"},
        },
        "dependency_edges": [
            {
                "package": "DESeq2",
                "depends_on": "SummarizedExperiment",
                "minimum_version": "1.1.6",
            },
            {"package": "DESeq2", "depends_on": "ggplot2", "minimum_version": "3.4.0"},
        ],
        "changed_fields": ["r_version"],
        "rationale": (
            "Bioconductor 3.22 requires R 4.5.x; upgrading r_version to 4.5.2 "
            "resolves the conflict."
        ),
        "sources": ["https://bioconductor.org/packages/3.22/bioc/html/DESeq2.html"],
    }
    add_probe(
        probe_id="E01_v2_gold_object_form",
        task_id="E01",
        scorer_name="knowledge-pilot-v2",
        category="reference_solution",
        description=(
            "Gold E01 answer using object map for `packages` and `minimum_version` edges."
        ),
        payload=e01_gold_dict,
        expected_status="scored",
        expected_fully_correct=True,
    )

    e01_equiv_array_form = {
        **e01_gold_dict,
        "packages": [
            {"name": "DESeq2", "version": "1.50.2", "repository": "Bioconductor"},
            {"name": "SummarizedExperiment", "version": "1.40.0", "repository": "Bioconductor"},
            {"name": "ggplot2", "version": "4.0.3", "repository": "CRAN"},
        ],
        "dependency_edges": [
            {"package": "DESeq2", "depends_on": "SummarizedExperiment", "constraint": ">= 1.1.6"},
            {"package": "DESeq2", "depends_on": "ggplot2", "constraint": ">= 3.4.0"},
        ],
        "changed_fields": "r_version",
    }
    add_probe(
        probe_id="E01_v2_equivalent_array_and_constraint_syntax",
        task_id="E01",
        scorer_name="knowledge-pilot-v2",
        category="equivalent_syntax",
        description=(
            "E01 using array-of-objects `packages`, `>= X.Y.Z` constraint syntax, "
            "and scalar `changed_fields`."
        ),
        payload=e01_equiv_array_form,
        expected_status="scored",
        expected_fully_correct=True,
    )

    e01_extra_true_package = {
        **e01_gold_dict,
        "packages": {
            **e01_gold_dict["packages"],
            "BiocGenerics": {"version": "0.56.0", "repository": "Bioconductor 3.22"},
        },
    }
    add_probe(
        probe_id="E01_v2_extra_true_package_penalized",
        task_id="E01",
        scorer_name="knowledge-pilot-v2",
        category="valid_alternative_outside_frozen_set",
        description="E01 gold answer that also lists true dependency `BiocGenerics 0.56.0`.",
        payload=e01_extra_true_package,
        expected_status="unsupported_for_automatic_scoring",
        expected_fully_correct=None,
        exposes_limitation=(
            "BEN-002: Listing any additional package or dependency edge beyond the exact "
            "3 packages / 2 edges triggers `unsupported_for_automatic_scoring`."
        ),
    )

    # --- E04 probes (knowledge-pilot-v2) ---
    e04_gold = {
        "r_version": "4.5.2",
        "bioconductor": "3.22",
        "packages": {
            "DESeq2": "Bioconductor 3.22",
            "SummarizedExperiment": "Bioconductor 3.22",
            "BiocGenerics": "Bioconductor 3.22",
            "ggplot2": "CRAN",
        },
        "versions": {
            "DESeq2": "1.50.2",
            "SummarizedExperiment": "1.40.0",
            "BiocGenerics": "0.56.0",
            "ggplot2": "4.0.3",
        },
        "dependency_edges": [
            {
                "package": "DESeq2",
                "depends_on": "SummarizedExperiment",
                "minimum_version": "1.1.6",
            }
        ],
        "install_strategy": (
            "Use install.packages from CRAN for ggplot2 and BiocManager::install "
            "for Bioconductor 3.22 packages."
        ),
        "rationale": (
            "Metadata-only compatibility plan for R 4.5.2 and Bioconductor 3.22 "
            "without executing installation."
        ),
        "sources": ["https://bioconductor.org/packages/3.22/bioc/html/DESeq2.html"],
    }
    add_probe(
        probe_id="E04_v2_gold",
        task_id="E04",
        scorer_name="knowledge-pilot-v2",
        category="reference_solution",
        description=(
            "Gold E04 answer satisfying all exact package, version, edge, and strategy checks."
        ),
        payload=e04_gold,
        expected_status="scored",
        expected_fully_correct=True,
    )

    e04_extra_edge = {
        **e04_gold,
        "dependency_edges": [
            *e04_gold["dependency_edges"],
            {"package": "DESeq2", "depends_on": "BiocGenerics", "minimum_version": "0.51.0"},
        ],
    }
    add_probe(
        probe_id="E04_v2_extra_valid_edge_penalized",
        task_id="E04",
        scorer_name="knowledge-pilot-v2",
        category="valid_alternative_outside_frozen_set",
        description=(
            "E04 answer including a second true dependency edge (`DESeq2 -> BiocGenerics`)."
        ),
        payload=e04_extra_edge,
        expected_status="unsupported_for_automatic_scoring",
        expected_fully_correct=None,
        exposes_limitation=(
            "BEN-002: E04 sets `extra_edges = len(edges) > 1`, so reporting more than 1 "
            "dependency edge causes automatic-scoring abstention."
        ),
    )

    e04_claimed_tested = {
        **e04_gold,
        "rationale": "We tested installation and installation succeeded on R 4.5.2.",
    }
    add_probe(
        probe_id="E04_v2_false_tested_installation_claim",
        task_id="E04",
        scorer_name="knowledge-pilot-v2",
        category="known_incorrect",
        description=("E04 answer falsely claiming that package installation was tested/succeeded."),
        payload=e04_claimed_tested,
        expected_status="scored",
        expected_fully_correct=False,
    )

    # --- E05 probes (knowledge-pilot-v2) ---
    e05_gold = {
        "cases": {
            "release_322_r452": "compatible",
            "release_322_r443": "incompatible",
            "unlisted_package_version": "unverified",
        },
        "positive_package": {"name": "DESeq2", "version": "1.50.2"},
        "rationale": (
            "Bioconductor 3.22 maps to R 4.5.2, is incompatible with R 4.4.3, "
            "and unlisted versions remain unverified."
        ),
        "sources": ["https://bioconductor.org/packages/3.22/bioc/html/DESeq2.html"],
    }
    add_probe(
        probe_id="E05_v2_gold",
        task_id="E05",
        scorer_name="knowledge-pilot-v2",
        category="reference_solution",
        description="Gold E05 answer with object `cases` and object `positive_package`.",
        payload=e05_gold,
        expected_status="scored",
        expected_fully_correct=True,
    )

    e05_equiv = {
        **e05_gold,
        "cases": [
            {"id": "release_322_r452", "classification": "compatible"},
            {"id": "release_322_r443", "classification": "incompatible"},
            {"id": "unlisted_package_version", "classification": "unverified"},
        ],
        "positive_package": "DESeq2@1.50.2",
    }
    add_probe(
        probe_id="E05_v2_equivalent_shorthand",
        task_id="E05",
        scorer_name="knowledge-pilot-v2",
        category="equivalent_syntax",
        description="E05 using array `cases` and `DESeq2@1.50.2` string shorthand.",
        payload=e05_equiv,
        expected_status="scored",
        expected_fully_correct=True,
    )

    e05_wrong = {
        **e05_gold,
        "cases": {
            "release_322_r452": "compatible",
            "release_322_r443": "compatible",
            "unlisted_package_version": "compatible",
        },
    }
    add_probe(
        probe_id="E05_v2_incorrect_compatibility_claims",
        task_id="E05",
        scorer_name="knowledge-pilot-v2",
        category="known_incorrect",
        description="E05 falsely marking R 4.4.3 and an unlisted version as `compatible`.",
        payload=e05_wrong,
        expected_status="scored",
        expected_fully_correct=False,
    )

    add_probe(
        probe_id="D01_v21_malformed_json_boundary",
        task_id="D01",
        scorer_name="knowledge-pilot-v2.1",
        category="boundary_case",
        description="Malformed JSON syntax in `answer.json`.",
        payload="{not valid json",
        expected_status="candidate_error",
        expected_fully_correct=None,
    )

    return probes


def audit_r_verifiers() -> list[dict[str, Any]]:
    """Audit R verifier scripts across `legacy-R`, `knowledge-B/C/E`, and `hard-v1`."""
    hard_manifest = hard_suite.manifest()
    hard_map = {t["id"]: t for t in hard_manifest["tasks"]}
    legacy_manifest = bench.manifest()
    legacy_map = {t["id"]: t for t in legacy_manifest["tasks"]}
    kp_manifest = knowledge_pilot.manifest()
    kp_map = {t["id"]: t for t in kp_manifest["tasks"]}

    rows: list[dict[str, Any]] = []
    for entry in calibration.CATALOG:
        tid = entry["task"]
        suite = entry["suite"]
        if tid in legacy_map:
            t_spec = legacy_map[tid]
            v_path = bench.ROOT / t_spec["oracle"]
            v_text = v_path.read_text(encoding="utf-8")
            observed_checks = len(re.findall(r'(?m)^\s*test_that\("', v_text))
            declared_checks = t_spec["groups"]
            oracle_independence = "high"
            quarantine_reason = None
        elif tid in hard_map:
            t_spec = hard_map[tid]
            v_path = hard_suite.HARD / t_spec["verifier"]
            v_text = v_path.read_text(encoding="utf-8")
            observed_checks = len(re.findall(r'(?m)^check\("', v_text))
            declared_checks = t_spec["checks"]
            oracle_independence = "high"
            quarantine_reason = None
        else:
            t_spec = kp_map[tid]
            if "verifier" in t_spec:
                v_path = knowledge_pilot.PILOT / t_spec["verifier"]
                v_text = v_path.read_text(encoding="utf-8")
                observed_checks = len(re.findall(r'(?m)^\s*check\("', v_text))
            else:
                v_path = (
                    Path(knowledge_pilot_v21.__file__)
                    if tid in {"D01", "D03"}
                    else Path(knowledge_pilot_v2.__file__)
                )
                observed_checks = t_spec["checks"]
            declared_checks = t_spec["checks"]
            if tid in {"D01", "D02", "D03"}:
                oracle_independence = "low_frozen_candidate_set"
                quarantine_reason = "BEN-002_frozen_candidate_registry"
            elif tid in {"E01", "E04", "E05"}:
                oracle_independence = "low_strict_json_extras_abstention"
                quarantine_reason = "BEN-002_strict_json_contract_and_extra_claim_abstention"
            else:
                oracle_independence = "high"
                quarantine_reason = None

        rows.append(
            {
                "task": tid,
                "suite": suite,
                "scorer": entry["scorer"],
                "verifier_file": str(v_path.relative_to(bench.REPO)).replace("\\", "/"),
                "declared_checks": declared_checks,
                "observed_r_check_calls": observed_checks,
                "check_count_consistent": declared_checks == observed_checks
                or tid in {"D01", "D02", "D03", "E01", "E04", "E05"},
                "oracle_independence": oracle_independence,
                "quarantined_for_scorer_coupling": quarantine_reason is not None,
                "quarantine_reason": quarantine_reason,
            }
        )
    return rows


def run_scorer_calibration_suite() -> dict[str, Any]:
    """Run the full Stage 2.5 scorer-calibration suite and return a structured report."""
    probes = build_json_scorer_probes()
    verifier_audit = audit_r_verifiers()
    all_probes_met = all(p["expectation_met"] for p in probes)
    all_verifiers_consistent = all(r["check_count_consistent"] for r in verifier_audit)
    quarantined_tasks = sorted(
        r["task"] for r in verifier_audit if r["quarantined_for_scorer_coupling"]
    )
    return {
        "calibration_suite_version": CALIBRATION_SUITE_VERSION,
        "frozen_scorers_modified": False,
        "all_probes_matched_expected_behavior": all_probes_met,
        "all_verifier_check_counts_consistent": all_verifiers_consistent,
        "probe_count": len(probes),
        "quarantined_tasks_due_to_scorer_limitations": quarantined_tasks,
        "probes": probes,
        "verifier_audit": verifier_audit,
    }
