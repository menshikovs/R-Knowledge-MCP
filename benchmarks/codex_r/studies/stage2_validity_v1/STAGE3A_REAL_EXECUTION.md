# Stage 3A: Real Benchmark Execution

**Date**: 2026-10-28  
**Branch**: `feature/stage3a-real-benchmark-execution` (stacked on PR #28's head `b851b28`; #28 unmerged)  
**Target**: `2.0`, via a PR temporarily based on `feature/stage2-benchmark-validity` (#28's branch), to be retargeted to `2.0` after #28 merges  
**Protocol**: 1.0.0 amended by **A1 → 1.1.0** ([`PREREGISTRATION_AMENDMENT_A1.md`](PREREGISTRATION_AMENDMENT_A1.md))  
**Final status**: **`STAGE 3A EXECUTION READY`**: execution infrastructure only; real-model execution is not empirically verified, and no trial is authorized

No real model request was made. Every trial in this document ran against a mocked Agents API; all
such records are `synthetic: true`. Real-model execution is implemented but **not empirically
verified**. "Execution ready" means the Stage 3A definition of done is met. It does not mean
calibration is authorized or that the confirmatory study is feasible.

| Status | Value |
| :--- | :--- |
| Mock-ready | **YES**: in-process, Stage 2.6 Docker/mock-model, and the real runner with a mocked model API |
| Live executor (real runner) | **IMPLEMENTED, NOT EMPIRICALLY VERIFIED**: no authorized real-model run has taken place |
| Calibration authorized | **NO**: no owner-approved spend ceiling |
| Study 1 (MCP vs model knowledge) | **SUPPORTED** |
| Study 2 (MCP alongside standard tools incl. web search) | **UNSUPPORTED**: equal web access cannot be ensured (§6) |
| Usable for the primary analysis | **YES, under amendment A1, for new runs only**: capability-equivalent trials started on or after 2026-10-28T00:00Z in runs that declare A1. Under 1.0.0 every legacy-runner trial would be excluded; historical results stay excluded (§9) |
| Confirmatory-ready | **NO**: at most 14 of the preregistered 30 target tasks reachable (Stage 2.7 §4.3) |

---

## 1. Existing runner components reused

Each Stage 2 trial attempt is **one call of `run_simple.run_trial`**. None of the following was
reimplemented:

| Concern | Reused implementation |
| :--- | :--- |
| Model API, sessions, SSE, submission, cancel, delete | `run_simple.SimpleClient` (over `exploratory/managed_agents.ManagedAgentsClient`) |
| Credentials | `run_simple.KEY_NAMES`, `start_executor` (executor key only via the child environment), `scrub` |
| Executor sandbox | `run_simple.start_executor` (read-only, caps dropped, uid 65534, memory/pids/CPU limits) |
| MCP server and allow-list | `run_simple.start_mcp`, `agent_mcp_tools` |
| Workspace preparation | `bench.prepare`, `hard.prepare`, `knowledge_pilot.prepare` |
| Artifact sealing | `run_simple.seal_trial_artifacts` |
| R scoring | `bench.score` (R01–R12), `hard.score` (H*), `knowledge_pilot.score` (legacy and v2/v2.1) |
| Timeouts, interrupts, cleanup | `run_simple` `SIGALRM` deadline, `RunInterrupts`, `cleanup_trial` |
| Usage / cost | `cleanup_trial` `collect_usage` (session `usage`/`cost`), `observed_usage` |
| Telemetry (schema 1.2) | `RunTelemetry`, `observe_stream_event`, `emit_server_telemetry`, `parse_mcp_call_telemetry` |
| Image resolution / verification | `run_simple.default_image_refs` (extracted from `main`, unchanged behaviour), `image_id`, `knowledge_pilot.verify_*_image` |
| Ledger, retries, resume, records, analysis | Stage 2 `runner.execute_study_plan`, `records`, `telemetry`, `analysis` |

## 2. Adapter architecture

```
plan (design.build_plan, pinned) ──> runner.execute_study_plan (ledger, retries, resume, spend guard)
                                         │  one attempt
                                         ▼
                      legacy_executor.make_legacy_trial_executor
                        arm -> (mode, instruction variant, MCP surface)
                        re-measure task/scorer digests (refuse on drift)
                                         │
                                         ▼
                      run_simple.run_trial(args, task, mode, rep, <attempt dir>, keys, images)
                                         │  result.json + telemetry.jsonl + artifacts
                                         ▼
                      legacy_executor.translate ──> records.from_runner_result ──> trial record
```

New components (everything else is reused):

| Component | Lines | Purpose |
| :--- | ---: | :--- |
| `legacy_executor.py` | ~490 | Arm mapping, study configurations, preflight, legacy→Stage 2 translation, `execute_study`, plan pinning |
| `scorer_bindings.py` | ~110 | Explicit, versioned binding from a catalogue scorer label to the scorer that actually executes |
| `run_simple.py` changes | +47 / −14 | Study-only arm C instruction variant, optional MCP surface override, sent-instruction digest, `default_image_refs` extraction; all default-off |
| `records.py`, `runner.py`, `live_runner.py` | small | Canonical scorer results (no invented aggregate), binding-based digests, protocol-version binding |
| `amendment.py` + `PREREGISTRATION_AMENDMENT_A1.md` + `preregistration_amendment_a1.json` | ~180 + doc | Versioned amendment A1: capability-equivalence evaluation, pinned hashes of the unchanged originals |
| CLI | — | `plan --pin`, `execute-study`; `execute-calibration --executor live` wired to the runner |

**Comparison.** The real execution path runs on about 4,500 lines of existing runner, scorer and
client code (`run_simple.py` 3,772; `runner/bench.py` 733; plus `hard/suite.py`,
`knowledge_pilot.py`, `managed_agents.py` and the telemetry package). The integration adds about
600 lines of adapter code and about 60 changed lines in `run_simple.py`. No second model-API path,
container launcher or scorer was written.

**Canonical implementations.** `run_simple.run_trial` is the only real-model executor.
`live_runner.py` (Stage 2.6) is kept as the mock-model isolation test harness
(`execute-calibration --executor docker-mock-model`, `live-smoke`). It is not a second production
path, so nothing was deleted.

## 3. A/B/C execution

| Arm | `run_simple` mode | Instructions sent | MCP |
| :--- | :--- | :--- | :--- |
| A | `without-mcp` | `standard` (byte-identical to B) | none: no container, no tool entry |
| B | `with-mcp` | `standard` | the preregistered 16-tool consolidated surface |
| C | `with-mcp` | `standard` + `protocol.ENCOURAGEMENT` (one sentence) | identical to B |

- The arm C text is a **study-only** variant (`run_simple.STUDY_INSTRUCTION_VARIANTS`). It is not a
  legacy `--instructions` choice, so the legacy CLI and the R launcher are unchanged. A test keeps
  `run_simple.MCP_ENCOURAGEMENT == protocol.ENCOURAGEMENT`.
- The legacy runner gives R tasks a 15-tool `legacy` allow-list and H/knowledge tasks a 13-tool
  list. The preregistration fixes the full 16-tool consolidated surface for B/C, so the adapter
  passes `mcp_tool_override` (B and C receive identical capabilities on every task).
  Historical invocations never set it.
- MCP use stays optional: the tool entry's `required: true` concerns the server connection, and
  no instruction requires a call.
- Per trial: a fresh session, a fresh temporary workspace, and a fresh attempt directory owned by
  the ledger. Execution follows the plan's `execution_index`.
- Evidence is measured, not planned: `session_instructions_sha256` is the digest of the text in
  the actual request body; `allowed_tools`, the MCP container start and the server audit come from
  the legacy result.

## 4. R scorer integration

`scorer_bindings.bind(task, catalogue_label)` decides what executes, and the Stage 2 digest
(`scorer_sha256`) covers that scorer's files:

| Tasks | Catalogue label | Executed scorer (`scorer_version`) | Label executable |
| :--- | :--- | :--- | :--- |
| R01–R12 | `legacy` | `runner/bench.py` R verifier (`legacy`) | yes |
| H01, H04, H10 | `hard-v1` | `hard/suite.py` R verifier (`hard-v1`) | yes |
| D01, D03 | `knowledge-pilot-v2.1` | `knowledge_pilot_v21.py` host JSON (`knowledge-pilot-v2.1`) | yes |
| B01–B03, C01–C05, D02, E01–E05 | `knowledge-pilot-v2.1` | `knowledge_pilot.py` legacy (`legacy`) | **no** |

Two defects were confirmed and fixed:

1. **Wrong pinned scorer digests.** `runner._task_and_scorer_meta` hashed `knowledge_pilot_v21.py`
   for 14 tasks it cannot score (v2.1 supports only D01/D03). The calibration schedule therefore
   pinned the digest of code that never runs. Digests now cover the executed scorer. The catalogue
   label is kept as `catalogue_scorer_label`, and the substitution is reported in
   `live_execution_limitations()`. The preregistered pilot list labels C01 with v2.1; that label
   is likewise not executable. The manifest is unchanged.
2. **Invented aggregation.** Stage 2.7 summed v2/v2.1 dimension checks into passed/total. The
   canonical scorers return `passed: null`, `total: null`, `overall_score: null` by design and
   abstain (`fully_correct: null`) on unknown claims. The sum could call an abstention "fully
   correct". Now:
   - the preregistered primary outcome (passed/total) is *undefined* for these scorers, so the
     record is a missing outcome (`scoring_error`);
   - `scorer_result` preserves the scorer's `status`, `fully_correct` and per-dimension states.

   This affects D01/D03 (quarantined Q tasks, used only as exploratory pilot replications).
   A latent `UnboundLocalError` for a scored result without integer checks was fixed with it.

Recorded per trial: scorer identity and version, executed-scorer digest, raw status,
passed/total, normalized score, fully correct (via `scorer_result`), and the outcome kind
(`scored`, `candidate_failure`, `scoring_error`, `infrastructure_failure`, `not_executed`).
Classification of legacy outcomes (`legacy_executor._primary_error`):

| Legacy result | Stage 2 outcome |
| :--- | :--- |
| `scored` with passed/total | `scored` |
| `candidate_error`, `candidate_timeout`, elapsed-time `TimeoutError` | `candidate_failure` (0) |
| `unsupported_for_automatic_scoring`, `scoring_error`, multidimensional result | `scoring_error` |
| turn failure, environment/executor/Docker/API error, `cleanup_error` | `infrastructure_failure` (retried once) |
| interrupted | not committed; the ledger records the interruption and resumes with a fresh attempt |

A turn failure is classified as infrastructure (provider side) and is retried once. This is a
stated judgement: an agent that fails its own turn could arguably be a candidate failure.

## 5. Calibration execution

`execute-calibration --executor live` now runs on `run_simple.run_trial`, Arm A only, in this order:

1. schedule validation, including pinned task/scorer digests against the current files;
2. `--authorize-spend` and a complete spend ceiling (`--max-spend-usd`, prices, per-trial reserve);
3. `live_execution_blockers()` (empty for the current 25-task schedule);
4. `legacy_executor.preflight`: Linux, Docker CLI, both key variables present (values never
   reported), image ids and runtime verification.

Nothing is written before all four pass. During the run, the Stage 2.7 `SpendGuard` (reserve
before each attempt, observed-usage pricing, full reserve for unobservable usage or interruptions,
journal replay on resume) and the schedule's retry and stop conditions apply. Usage and cost come
from the runner's own session observation; the original `usage` and `cost` are kept in each
attempt's `legacy_result`.

No provider-side spend limit is sent (the Agents API contract for one is not verified here), so
the ceiling is accounting over reported usage, not metering. Mock modes are unchanged.

The committed `calibration_schedule.json` was regenerated with the corrected digests. The
previous file fails validation: all 75 trials are reported as having changed scorer digests, which
is the integrity guard working as intended.

## 6. Study configurations

`legacy_executor.STUDIES`:

| Study | Configured non-MCP tools (all arms) | Web access | Status |
| :--- | :--- | :--- | :--- |
| `study1_mcp_vs_model_knowledge` | executor shell (`command_execution`) | no | **supported** |
| `study2_mcp_with_standard_tools` | shell + web search | yes | **unsupported** |

Study 2 is refused by `execute-study`, `make_legacy_trial_executor` and `execute_study`. The
reasons: the runner's session declares no web-search tool, its shared instructions forbid browsing,
and no verified API contract for an equal web-search tool exists in this repository. Treating
Study 2 as comparable would be pretending.

Each record carries `agent_tools`:

- `available` (the configuration): agent tools, web access, R-Knowledge-MCP;
- `used`: observed `agent.tool.started` item types;
- `web_access_calls`;
- `findings`: for example, web-access items observed although none was configured.

Each run directory binds its study configuration (`study_execution.json`), so a resume cannot mix
studies. Separate studies need separate run directories and are never pooled.

**Limit of Study 1.** The executor runs on a plain bridge network with internet access. "No web" is
enforced at the tool level (no web tool) and by instruction, not by the network. Shell-level
downloads would be visible only as `command_execution` items, not as web-access items.

## 7. End-to-end evidence (mocked model, real everything else)

`tests/test_stage3a_end_to_end.py` (Linux + Docker; run under Ubuntu WSL2 with Docker 29.8.2):

1. **Full A/B/C lifecycle on R01.** Covers manifest equality, plan pinning, a randomized plan,
   arm configuration and execution through the real `run_trial`, a real R-Knowledge-MCP container,
   a real `tools/list` + `tools/call` from a container on the trial network, the real R verifier
   (4/4), records, the ledger, an **interruption and resume** (only the interrupted trial re-runs,
   as attempt 2, charged its reserve), and the regenerated analysis.
   Asserted:
   - A has no MCP;
   - B and C have `listed`, `attempted = completed = 1`, and `delivered ≥ 1` from the server's
     own log;
   - instruction digests: A = B, and C = B + sentence;
   - B and C have identical 16-tool allow-lists;
   - sessions are deleted and no containers are left over.
2. **Real R scorer, correct vs incorrect.**
   - R01: a reference written from the public task statement passes 4/4; a mutant fails.
   - H01: the frozen `controls/H01/reference.R` passes; `wrong_filter_then_group.R` fails.
3. **D01 (multidimensional).** The canonical v2.1 result (`passed`/`total`/`overall_score` null,
   dimensions, `fully_correct`) is preserved in `scorer_result`, and the outcome is `scoring_error`.
4. **Live calibration on the real runner.** R01 × 2 runs through `execute_calibration(live)` with
   authorization, a ceiling and a mocked-model context: records are scored, spend is accounted from
   the mocked usage, and the records are labelled synthetic and refused as baseline evidence.

The scripted solution files are fixtures. They show that the pipeline carries a given solution to a
correct verdict; they say nothing about model capability.

### Verification run (2026-10-28, commit `d09df9c`)

| Check | Result |
| :--- | :--- |
| `ruff check .` / `ruff format --check .` | passed / 329 files formatted |
| `pytest --collect-only -q` | 2106 tests collected |
| **Windows 11**, `pytest -m "not docker"` | 1933 passed, 130 skipped, 0 failed |
| **Windows 11**, Docker-marked tests (Stage 2.6, 2.7, 3A) | 14 passed, 7 skipped (the Stage 3A end-to-end tests need Linux `SIGALRM`); no containers or networks left behind |
| **Linux (WSL2 Ubuntu), full suite including Docker**, from a clean clone of `d09df9c` on WSL's native filesystem | **2026 passed, 80 skipped, 0 failed** (896 s) |
| `cli frozen --verify` | 279 frozen files, 0 differences |
| Manifest / generated-artifact consistency, including the amendment record | 11 of 11 equal |
| `cli amendment --verify` | matches the unchanged originals and the amendment document |

The 80 Linux skips are all clone or environment related. None is a Docker test: git-ignored
bundles and saved historical runs absent from a clean clone (17), the optional native extension
not installed (11), and two image-id variables unset (2).

**Test failures vs environment failures.** There were no test failures. Two earlier Linux runs
failed for environmental reasons, and both were investigated:

- Six Stage 2.6 Docker tests failed at `b851b28` and in an earlier Stage 3A state. This was a real
  defect, fixed below.
- One full run on the mounted Windows drive (`/mnt/c`) stopped after 151 passing tests with a
  pytest `INTERNALERROR` (`FileNotFoundError` in `os.getcwd()`). That is an environment failure of
  the mounted filesystem: the same test files pass alone (32/32) and in the same order (152/152).
  It did not recur on the native filesystem.

**Defect found by the Linux run (pre-existing).** The Stage 2.6 live runner's candidate container
(uid 65534) could not write into the host-created workspace on Linux:
`PermissionError: /candidate/answer.json`. Six Stage 2.6 Docker tests failed for this reason,
identically at PR #28's head `b851b28`. They had only ever been run on Windows, where Docker
Desktop's bind mounts hide the problem. `TrialTopology` now makes the mounted workspace writable,
as `run_simple` already does. All 14 tests pass on Linux.

## 8. Legacy compatibility

- `run_simple` CLI choices, defaults, trial IDs, record fields and resume behaviour are unchanged.
  The changes are default-off: the study variant is not a CLI choice, the override is only
  read via `getattr`, and `session_instructions_sha256` is an additive field.
- Existing legacy suites (`test_codex_simple*.py`, launcher, MCP diagnostics, knowledge pilot)
  pass. The Linux-only `run_trial` suites ran under WSL.
- Frozen evidence: 279 files, 0 differences. No scorer, task, oracle, verifier or historical
  result was modified.

## 9. Remaining limitations and blockers

1. **Egress rule: resolved prospectively by amendment A1.** Under 1.0.0, every legacy-runner trial
   records the invalidating `egress_not_restricted` and `egress_unverified`. The owner approved
   amendment A1 (protocol 1.1.0), registered before any real trial. A1 replaces the topology
   requirement with per-trial capability equivalence:
   - A and B have equal non-MCP capabilities and instructions;
   - MCP is absent in A and present in B/C;
   - all arms share the same model transport;
   - scorer and reference files are unreachable from candidate mounts;
   - each study has an explicit web policy;
   - every deviation is logged.

   Study runs and live calibration declare A1 in `run_config.json`, and each record carries
   `protocol_version: "1.1.0+A1"` and a `capability` block. The two egress codes stay in every
   record, marked `superseded_by: "A1"`. `PREREGISTRATION.md` and `experiment_manifest.json` are
   byte-identical; `preregistration_amendment_a1.json` pins their hashes. Records made without A1,
   historical results, and trials started before the effective time are **not** made eligible
   retroactively.
   - **Residual.** The executor's shell still has network access, and the repository is public.
     "No web" (Study 1) is enforced by tool configuration and instructions. Scorer access over the
     network is caught only by the heuristic `reference_access_suspected`. See the amendment's §6.
2. **Not empirically verified.** No authorized real-model run has taken place.
3. **Spend is accounted, not metered** (§5).
4. **Study 2 unsupported** (§6).
5. **Confirmatory infeasibility** with the current catalogue (Stage 2.7 §4.3), unchanged.
6. **Infrastructure retry cap.** The preregistration's "at most 10% of trials" retry cap is not
   enforced by the runner; calibration enforces the schedule's 20% failure-rate stop.

## 10. Commands for future authorized trials

Run on Ubuntu/WSL2 with Docker, the runner images, and `OPENAI_API_KEY` and
`OPENAI_EXECUTOR_API_KEY` exported. Prices and ceilings come from the owner.

```bash
M=benchmarks.codex_r.studies.stage2_validity_v1.cli

# Arm-A calibration (75 trials) on the real runner
python -m $M execute-calibration --executor live --authorize-spend \
  --out-dir <run-dir> --max-spend-usd <USD> --input-usd-per-mtok <USD> \
  --output-usd-per-mtok <USD> --per-trial-reserve-usd <USD>

# Study 1: randomized, pinned A/B/C plan, then execution (resume = same command, same out-dir)
python -m $M plan --tasks <task ids> --reps 3 --seed <registered seed> --out plan.json --pin
python -m $M execute-study --study study1 --plan plan.json --out-dir <run-dir> \
  --authorize-spend --max-spend-usd <USD> --input-usd-per-mtok <USD> \
  --output-usd-per-mtok <USD> --per-trial-reserve-usd <USD>

# Preregistered analysis of a finished run
python -m $M analyze --plan plan.json --records <run-dir>/trial_records.jsonl --out analysis.json
```

Exit codes: 0 ok; 1 dataset problems; 2 refused input or blocked environment (`BLOCKED:` lists
the runner's preconditions); 3 schedule structurally unavailable on the real path.
