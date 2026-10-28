# Stage 2 Experimental Design and Runner Integration Audit

## 1. Three-Arm Experimental Design

Stage 2 separates **tool availability** from **prompt encouragement** using a three-arm randomized block design defined in [`protocol.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/protocol.py):

| Arm | Runner Mode | MCP Server Wired | Base Instruction (`COMMON_BASE_INSTRUCTION`) | Encouragement Suffix (`ARM_C_ENCOURAGEMENT_SUFFIX`) | Scientific Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Arm A** | `without-mcp` | `False` | Identical (`sha256: b39ef2bc...`) | None (`""`) | Baseline control (no R-Knowledge-MCP access). |
| **Arm B** | `with-mcp` | `True` (`consolidated`, 10 tools) | Identical (`sha256: b39ef2bc...`) | None (`""`) | **Primary treatment arm**: voluntary MCP availability. |
| **Arm C** | `with-mcp-encouraged` | `True` (`consolidated`, 10 tools) | Identical (`sha256: b39ef2bc...`) | Appended (`sha256: 00161e26...`) | Secondary arm: MCP availability + standardized encouragement sentence. |

### Instruction Invariance Contract

- **`COMMON_BASE_INSTRUCTION`**:
  > *"Complete the R benchmark task in the current working directory. Write only the requested deliverables at the exact relative paths specified by the task prompt. Do not modify test harnesses or hidden verification files. Verify your solution before finishing."*
- **`ARM_C_ENCOURAGEMENT_SUFFIX`**:
  > *"When package metadata, function signatures, lifecycle changes, Bioconductor release compatibility, or ecosystem candidates are uncertain, consult the available R-Knowledge-MCP tools before finalizing your answer."*
- `protocol.assert_protocol_invariants()` enforces at import/test time that `instruction_text("A") == instruction_text("B")`, that `instruction_text("C")` equals `instruction_text("B") + "\n\n" + ARM_C_ENCOURAGEMENT_SUFFIX`, and that Arms B and C expose the exact same MCP toolset (`consolidated`, 10 tools).

## 2. Unit of Randomization and Counterbalanced Block Design

Defined in [`design.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/design.py):

- **Blocking Factor**: Each `(task_id, repetition_index)` pair forms a complete block of size 3 (`block_id = f"{task_id}__r{rep:02d}"`) containing one trial of Arm A, one of Arm B, and one of Arm C.
- **Within-Block Position Counterbalancing (`blocked-latin-permutations-v1`)**:
  - There are $3! = 6$ permutations of `("A", "B", "C")`: `ABC`, `ACB`, `BAC`, `BCA`, `CAB`, `CBA`.
  - Within each task across repetitions, and across tasks at a fixed repetition, blocks cycle through balanced Latin-square permutations seeded deterministically by `derive_seed(registration_commit, study_id, stage)`.
  - `design.verify_plan_balance()` verifies that every block contains exact arm set `{"A", "B", "C"}` and that position 0, position 1, and position 2 counts across arms differ by at most $\lceil B / 6 \rceil$.
- **Interleaved Global Execution Order**: Blocks are interleaved in randomized waves so all repetitions of a single task are never executed back-to-back.
- **Fresh Context Per Trial**: Every trial receives a unique `session_isolation_id`, a freshly materialized workspace directory, and a fresh container/CLI process (`fresh_context = True`).

## 3. Environment and Network Egress Policy

`protocol.REQUIRED_EGRESS_POLICY` locks the target isolation contract:

- `offline_evidence_root`: `benchmarks/codex_r/evidence/b1_frozen_20261026` (mounted read-only in Arms B and C; unmounted in Arm A).
- `allowed_egress_hosts`: `["api.openai.com"]` (model inference endpoint only).
- `blocked_r_package_hosts`: `["cloud.r-project.org", "cran.r-project.org", "bioconductor.org", "api.github.com", "github.com"]` (prevents Arm A or B/C from bypassing the controlled snapshot via live `curl`/`install.packages()`).

## 4. Real Runner (`benchmarks/codex_r/run_simple.py`) Integration Audit

Phase E audited [`benchmarks/codex_r/run_simple.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/run_simple.py) to determine whether it can execute the Stage 2 A/B/C protocol directly and produce valid Stage 2 trial records.

### 4.1 Capabilities Already Present in `run_simple.py`

1. **Per-trial fresh workspace and container**: Each `(task, mode)` run creates a fresh temporary workspace copy and runs a separate `docker run --rm` invocation with a unique `run_id`.
2. **Task and scorer hash pinning**: Computes `task_sha256` and `scorer_sha256` and validates them on `--resume`.
3. **Canonical schema-1.2 telemetry**: Captures client JSONL events and server stderr telemetry into `telemetry.jsonl` and summarizes them via `benchmarks/codex_r/telemetry/aggregate.py`.
4. **Stage 2 record conversion bridge (`records.from_runner_result`)**: Implemented in [`records.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/records.py), `from_runner_result(planned_trial, runner_record, telemetry_events, expected=...)` deterministically converts a `run_simple.py` `result.json` + `telemetry.jsonl` pair into a schema-validated Stage 2 trial record (`trial_record.schema.json`), mapping runner statuses (`scored`, `error`, `interrupted`, `unsupported_for_automatic_scoring`) and automatically auditing protocol compliance.

### 4.2 Confirmed Runner Blockers Preventing Pilot / Confirmatory Execution Today

| Requirement | Current `run_simple.py` Behavior | Blocker Status |
| :--- | :--- | :--- |
| **Three-arm (`A`/`B`/`C`) execution** | Supports only two modes (`without-mcp` and `with-mcp`); has no `with-mcp-encouraged` mode and does not inject `COMMON_BASE_INSTRUCTION` or `ARM_C_ENCOURAGEMENT_SUFFIX`. | **BLOCKER (Pilot & Confirmatory)** |
| **Randomized `plan.json` execution** | Iterates deterministically over `--tasks` $\times$ `--modes` ($R=1$ per invocation) rather than consuming a counterbalanced multi-repetition `plan.json`. | **BLOCKER (Pilot & Confirmatory)** |
| **Egress allow-list proxy enforcement** | Runs `docker network create <net>` (plain Docker bridge network with full outbound internet access). `benchmarks/codex_r/exploratory/egress_proxy.py` exists as a standalone prototype but is **not wired** into `run_simple.py`. Consequently, `from_runner_result()` marks `egress_proxy_enforced = False` and records `"egress_proxy_not_enforced"` in `protocol.capability_violations`. | **BLOCKER (Pilot & Confirmatory)** |
| **Token and cost accounting** | Populates `token_usage` in only `1 / 103` historical runs because Codex CLI stdout/JSONL frequently omits final usage summaries. | **Non-blocking for primary score ITT (`null_handling = "explicit_missing_allowed"`), but limits cost/token secondary precision.** |

