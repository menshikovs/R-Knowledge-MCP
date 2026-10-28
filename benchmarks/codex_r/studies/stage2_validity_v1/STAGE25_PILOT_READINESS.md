# Stage 2.5 — Pilot Readiness and Scientific Hardening Report (`stage2_validity_v1`)

## 1. Executive Decision

- **Final Verification Status**: **`STAGE 2.5 PARTIALLY COMPLETE`** (with **`STAGE 2 INFRASTRUCTURE READY`** fully achieved).
- **Why `STAGE 2.5 PILOT READY` is NOT claimed**:
  Per Step 5 and Step 17 rules (*"Do not claim `PILOT READY` unless the actual runner has passed end-to-end tests under the intended isolation policy. A mock environment alone does not establish real network isolation."*):
  1. All Stage 2.5 software components — the three-arm study runner adapter ([`runner.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/runner.py)), fault-tolerant resume ledger (`TrialLedger`), network isolation policy evaluator ([`isolation.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/isolation.py)), separate scorer-calibration suite ([`scorer_calibration.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/scorer_calibration.py)), and three executable study specifications ([`study_configs.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/study_configs.py)) — are implemented and verified end-to-end offline.
  2. However, static and contract inspection (`isolation.inspect_legacy_runner_isolation()`) proves that the live Docker execution path in [`benchmarks/codex_r/run_simple.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/run_simple.py#L2497) still runs `docker("network", "create", network)` (a plain Docker bridge network with default outbound internet access) and does not wire [`benchmarks/codex_r/exploratory/egress_proxy.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/exploratory/egress_proxy.py) into an `--internal` container network. Furthermore, live Docker + OpenAI Managed Agents sessions cannot be executed under the current offline/no-spend authorization boundary.

---

## 2. Recovery of Unfinished Stage 2 Work & Implementation Inventory

### 2.1 Stage 2 Modules (Recovered, Repaired, and Verified)

| File | Responsibility | Status |
| :--- | :--- | :--- |
| [`__init__.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/__init__.py) | Package exports (`__all__`) | Repaired (was 0-byte empty file) |
| [`protocol.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/protocol.py) | Three arms (`A`, `B`, `C`), instruction digests, `capability_violations()` | Complete & verified |
| [`design.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/design.py) | `blocked-latin-permutations-v1` randomization, `build_plan()`, `verify_plan()` | Complete & verified |
| [`records.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/records.py) | Schema validation (`validate_record`, `validate_dataset`), ITT rules (`analysis_value`), runner bridge (`from_runner_result`) | Extended with `from_runner_result()` & verified |
| [`telemetry.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/telemetry.py) | 7-level observability projection, `correlate_calls()`, `_dedup_by_call_id()`, unstarted terminal event invariant | Repaired for duplicate/unstarted events & verified |
| [`analysis.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/analysis.py) | Task-level sign-flip primary inference, block-level sensitivity, 2-stage bootstrap CI, Holm adjustment, Manski bounds, LOTO | Complete & verified |
| [`power.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/power.py) | Power & Type I error simulation across $\delta \in \{-0.20, -0.10, 0.0, 0.10, 0.20, 0.30\}$ and task vs block sign-flip check | Extended to negative deltas & verified |
| [`calibration.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/calibration.py) | Read-only historical results aggregation (`before_date="20261028"`) and Arm-A-only screening (`S1`, `S2`, `RC`, `Q`) | Stabilized with `before_date` cutoff & verified |
| [`manifest.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/manifest.py) | `build_manifest()`, synchronous `mcp_tool_surface()`, 279-file `frozen_digests()` / `verify_frozen()` | Repaired Windows sandbox socketpair hang & verified |
| [`prereg.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/prereg.py) | Pure rendering of `PREREGISTRATION.md` from `experiment_manifest.json` | Complete & verified |
| [`dryrun.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/dryrun.py) | 5 deterministic synthetic scenarios (`null`, `positive`, `negative_tool_tax`, `heavy_missingness`, `leaky_control`) | Complete & verified |

### 2.2 New Stage 2.5 Modules & Artifacts

| File | Responsibility | Status |
| :--- | :--- | :--- |
| [`runner.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/runner.py) | 3-arm execution adapter (`build_trial_invocation_spec`, `execute_study_plan`), fault-tolerant `TrialLedger`, `make_mock_trial_executor()` | Implemented & tested |
| [`isolation.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/isolation.py) | Arm network policies (`policy_for_arm`), `egress_proxy` connection evaluator (`evaluate_connection_attempt`), `run_synthetic_isolation_probes()`, `inspect_legacy_runner_isolation()` | Implemented & tested |
| [`scorer_calibration.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/scorer_calibration.py) | 16-probe JSON scorer calibration battery (`D01–D03`, `E01`, `E04`, `E05`) + 31-task R verifier check-count audit | Implemented & tested |
| [`study_configs.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/study_configs.py) | Three executable study specifications (`smoke_mock`, `pilot_real_spec`, `confirmatory_spec`) + task graduation backlog | Implemented & tested |
| [`scorer_calibration_report.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/scorer_calibration_report.json) | Committed output of `cli.py scorer-calibration` | Generated & verified |
| [`study_specifications.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/study_specifications.json) | Committed output of `cli.py study-specs` | Generated & verified |
| [`isolation_probes_report.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/isolation_probes_report.json) | Committed output of `cli.py isolation-probes` | Generated & verified |

---

## 3. Real-Runner Integration & Fault-Tolerant Resume (`runner.py`)

### 3.1 Three-Arm Execution Adapter

`runner.build_trial_invocation_spec()` constructs an isolated execution specification for each planned trial in `plan["trials"]`:

- **Arm A (`without-mcp`)**: `mcp_container_started = False`, `allowed_tools = []`, `instructions = base_instructions()` (`sha256: b39ef2bc...`).
- **Arm B (`with-mcp`)**: `mcp_container_started = True`, `allowed_tools = <10 consolidated tools>`, `instructions = base_instructions()` (`sha256: b39ef2bc...`).
- **Arm C (`with-mcp-encouraged`)**: `mcp_container_started = True`, `allowed_tools = <10 consolidated tools>`, `instructions = base_instructions() + ENCOURAGEMENT` (`sha256: d23e0842...`).
- Every trial receives a unique `session_isolation_id`, fresh workspace directory (`workspaces/<trial_id>__att<NN>`), and pinned `task_sha256` and `scorer_sha256`.

### 3.2 Reproducible Interruption Recovery (`TrialLedger`)

`runner.TrialLedger` manages `plan.json`, `run_config.json`, `trial_records.jsonl`, `ledger_journal.jsonl`, and per-trial `staging/<trial_id>.staging.json` files:

1. **Interruption before trial start**: Unreached trials have no staging or finalized record and are materialized as explicit `not_executed` records in the dataset.
2. **Interruption during model execution**: Detected via `stage == "executing"` in `.staging.json`; logged in `ledger_journal.jsonl` as `interrupted_attempt_detected`. On resume, if retries are exhausted, the trial is materialized as `not_executed` without repeating completed trials.
3. **Interruption after scoring before final persistence**: Detected via `stage == "scored_pending_commit"` in `.staging.json`; `TrialLedger.recover()` atomically commits the validated record into `trial_records.jsonl` (`recovered_scored_pending_commit`) **without re-running the trial**.
4. **Partially written / truncated JSONL records**: `TrialLedger.recover()` parses `trial_records.jsonl` line-by-line, quarantines any corrupt/truncated tail line into `ledger_journal.jsonl` (`corrupt_jsonl_line_quarantined`), and atomically rewrites `trial_records.jsonl` with all valid finalized records.
5. **Duplicate trial observations**: Deduplicated idempotently during recovery (`duplicate_trial_record_detected`), retaining the first finalized record.
6. **Explicit retry linkage**: Only `infrastructure_failure` outcomes may be retried (up to `max_infra_retries`). Every retry logs `attempt_index > 1` and `retry_of_attempt_id` in `ledger_journal.jsonl`. Candidate failures (`candidate_failure`) are scored as `0.0` (ITT) and are **never retried**.

---

## 4. Information-Channel Isolation Evidence (`isolation.py`)

### 4.1 Synthetic Isolation Probe Matrix (`isolation_probes_report.json`)

`isolation.run_synthetic_isolation_probes()` validates 39 connection probes across Arms A, B, and C plus 2 fault-injection probes against `exploratory/egress_proxy.py::parse_connect_authority`:

- **MCP internal reachability (`r-knowledge-mcp:8000`)**: Denied in Arm A (`mcp_not_attached_in_arm_a`); permitted in Arms B and C (`mcp_internal_allowed`). When the MCP server is unhealthy in Arm B, `evaluate_connection_attempt()` flags `treatment_arm_mcp_unavailable`.
- **Permitted model endpoints (`CONNECT`)**: `api.openai.com:443` and `codex-cloud-environments.chatgpt.com:443` permitted across all arms.
- **Unauthorized outbound traffic rejection**: `cloud.r-project.org:443`, `cran.r-project.org:443`, `bioconductor.org:443`, `api.github.com:443`, `github.com:443`, `example.com:443`, IP literal `93.184.216.34:443`, non-443 port `api.openai.com:444`, and non-`CONNECT` HTTP methods are all rejected (`permitted = False`).
- **Gateway bypass detection**: Direct unproxied traffic on a non-internal bridge network is flagged with `violation_code = "egress_not_restricted"`.

### 4.2 Hard Blocker in Live `run_simple.py` Docker Topology

`isolation.inspect_legacy_runner_isolation()` confirms:

- `arm_a_omits_mcp_container`: `True` (Arm A does not start the MCP container).
- `creates_plain_docker_bridge`: `True` (`docker("network", "create", network)` at line 2497).
- `uses_docker_internal_network_flag`: `False`.
- `wires_egress_proxy_container`: `False`.
- `live_egress_isolation_enforced`: `False`.

Because a mock environment alone does not establish real container network isolation, live Pilot Readiness requires wiring `docker network create --internal` + `egress_proxy.py` into the container launch path and verifying it on a Linux/WSL2 Docker host.

---

## 5. Scorer Calibration & Reliability Findings (`scorer_calibration_report.json`)

Without modifying any frozen scorer, `scorer_calibration.run_scorer_calibration_suite()` executed **16 structured JSON probes** across `D01`, `D02`, `D03`, `E01`, `E04`, and `E05` and audited all **31 task verifiers**:

1. **Reference Solutions (`D01` `termr`/`climenu`, `D02` `httptest2`, `D03` `validate`/`pointblank`, `E01`, `E04`, `E05`)**: All score `status = "scored"`, `fully_correct = True`.
2. **Equivalent Syntax (`E01` array-of-objects + `>= X.Y.Z` constraints, `E05` array `cases` + `DESeq2@1.50.2` shorthand)**: Properly accepted by `knowledge-pilot-v2` (`status = "scored"`, `fully_correct = True`).
3. **Confirmed `BEN-002` Limitations (Quarantined Tasks)**:
   - `D01_v21_unlisted_package_cli` and `D02_v2_unlisted_package_vcr`: Valid CRAN packages outside the 2–3 package frozen candidate list return `status = "unsupported_for_automatic_scoring"`.
   - `D01_v21_unknown_claim_abstention`: Including a valid enum feature (`keyboard_single_multi_select` on `termr`) marked `unknown` in `knowledge_pilot_claims_v2_1.json` causes automatic-scoring abstention.
   - `E01_v2_extra_true_package_penalized` and `E04_v2_extra_valid_edge_penalized`: Including an additional true package (`BiocGenerics` in `E01`) or a second true dependency edge (`DESeq2 -> BiocGenerics` in `E04`) triggers `unsupported_for_automatic_scoring`.
4. **Known Incorrect & Boundary Solutions**: Fabricated versions (`9.9.9`), missing required features, false compatibility classifications, false claims of tested installation, and malformed JSON are all caught deterministically (`fully_correct = False` or `status = "candidate_error"`).
5. **R Verifier Check-Count Audit**: All 31 tasks across `legacy-R`, `knowledge-B/C/E`, and `hard-v1` have consistent check counts between their manifest declarations and `check("...")` calls in their R verifier scripts.

---

## 6. Three Executable Study Specifications (`study_specifications.json`)

| Config ID | Mode | Tasks ($K$) | Reps ($R$) | Arms | Planned Trials | Timeout / Trial | Expected Serial Hours (`76.4s` med) | Conservative Hours (`186.0s` p90) | Ready Now? |
| :--- | :--- | ---: | ---: | :--- | ---: | ---: | ---: | ---: | :--- |
| **`smoke_mock`** | Offline mock (`cli.py smoke-runner`) | 4 (`R03, C03, D01, H10`) | 1 | `A, B, C` | 12 | `60s` | `0.00h` (instant) | `0.00h` | **YES** |
| **`pilot_real_spec`** | Live model (requires auth) | 10 (`D01–D03, C01, C04, E02, E03, E05, R01, H10`) | 2 | `A, B, C` | 60 | `300s` | `1.27h` | `3.10h` | **NO** (blocked by live Docker `--internal` proxy & spend auth) |
| **`confirmatory_spec`** | Live confirmatory (requires reg + auth) | 0 eligible today (target 30 `S1` tasks) | 3 | `A, B, C` | 0 today (target 270) | `600s` | `5.73h` (at 270 trials) | `13.95h` (at 270 trials) | **NO** (blocked by `0 / 20` eligible `S1` tasks, live Docker isolation, git registration, & spend auth) |

---

## 7. Prioritized Engineering Backlog to Reach Live `PILOT READY` and `CONFIRMATORY READY`

| Priority | Backlog Item | Target Files | Acceptance Criteria |
| :---: | :--- | :--- | :--- |
| **P0** | Wire `--internal` Docker network + `egress_proxy.py` sidecar into live container execution | `benchmarks/codex_r/run_simple.py`, `benchmarks/codex_r/exploratory/egress_proxy.py` | `docker network create --internal` is used per trial; `egress-proxy` container provides the sole outbound route to `api.openai.com:443` / `codex-cloud-environments.chatgpt.com:443`; proxy logs are captured into `runner_record["proxy_entries"]`; `isolation.inspect_legacy_runner_isolation()["live_egress_isolation_enforced"]` returns `True`. |
| **P1** | Connect `runner.py` 3-arm invocation spec to live `SimpleClient` / Docker container launcher | `benchmarks/codex_r/studies/stage2_validity_v1/runner.py`, `benchmarks/codex_r/run_simple.py` | Live executor accepts `build_trial_invocation_spec()` for Arms A, B, and C, passing the exact arm instruction text and tool allow-list to `SimpleClient.create_simple_session()`. |
| **P2** | Execute Arm-A-only calibration pass ($n_A \ge 3$) on the 17 `S2` tasks | `benchmarks/codex_r/studies/stage2_validity_v1/calibration.py`, `task_catalog.json` | Each of `R01–R12, C03, C04, H01, H04, H10` has $\ge 3$ scored Arm A trials; tasks with $\bar{Y}_A \in [0.10, 0.90]$ graduate to `S1`. |
| **P3** | Author `knowledge-pilot-v2.2` scorer & recalibrated task prompts to resolve `BEN-002` and ceiling saturation | `benchmarks/codex_r/knowledge_pilot_v21.py` (new `v22` module), `benchmarks/codex_r/knowledge_pilot/tasks/` | `D01–D03` evaluate verifiable package capabilities rather than a 2–3 package allow-list; `E01, E04, E05` do not abstain when additional true dependency facts are included; `C01, C02, C05` edge cases are hardened so $\bar{Y}_A \le 0.90$; $\ge 20$ total tasks qualify for `S1`. |
| **P4** | Freeze preregistration commit and derive confirmatory randomization seed | `experiment_manifest.json`, `PREREGISTRATION.md` | Commit final manifest on Git, record `registration_commit`, and compute `manifest.derive_seed(core_sha256, registration_commit)`. |

