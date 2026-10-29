# Preregistration Amendment A1: capability equivalence instead of network topology

| Field | Value |
| :--- | :--- |
| Study | `stage2_validity_v1` |
| Amendment | **A1** |
| Protocol version | **1.1.0**, amending **1.0.0** |
| Registered | 2026-10-28, approved by the project owner |
| Effective from | `2026-10-28T00:00:00Z` (trials starting at or after this time, in runs that declare A1) |
| Registered before any real experimental trial | **Yes**: no real-model trial of this study has been collected |
| Original preregistration | `PREREGISTRATION.md` and `experiment_manifest.json`, **unchanged** |
| Machine-readable record | `preregistration_amendment_a1.json` (pins the hashes below; regenerate with `cli amendment --write`, check with `cli amendment --verify`) |

The original documents are not edited. Their SHA-256 digests, together with this document's digest
and a digest of the amended rules, are recorded in `preregistration_amendment_a1.json`, and a test
fails if any of them changes.

## 1. What is amended

Protocol 1.0.0 required every trial to run on an internal network behind an observing allow-list
proxy, and made two violations invalidating:

- `egress_not_restricted`: the trial network was not internal;
- `egress_unverified`: no egress log.

The 1.0.0 manifest itself records this egress policy as "NOT IMPLEMENTED in the runner (plain
bridge network)". The benchmark runner (`run_simple.run_trial`) uses a fresh plain Docker bridge
network per trial, and the self-hosted executor must reach the model API through it. Under 1.0.0,
**every** trial of the study would therefore be excluded from the primary analysis. This happens
regardless of whether the arms differed in anything other than the treatment.

A1 replaces that topology requirement with a **capability-equivalence rule**. The rule tests what
the comparison actually depends on: that the arms differ only in MCP access (and, for C, one
sentence).

## 2. Rules under A1

1. Arms A and B have **identical non-MCP capabilities and instructions**. Capabilities are:
   - the non-MCP tool entries in the session request;
   - the executor runtime image;
   - the network configuration;
   - the model transport.

   The instructions must be byte-identical.
2. **MCP is unavailable in A and available in B and C.** C differs from B only by the registered
   encouragement sentence. (These are the unchanged 1.0.0 checks.)
3. **All arms may use the same required model API transport.** Network topology is not itself a
   validity requirement; equality of the network configuration across arms is.
4. **Scorers and reference answers stay inaccessible during candidate execution.**
   - No scorer, verifier, oracle or reference file may be reachable from the candidate's mounts
     (checked per trial).
   - References to their locations in the agent's non-MCP tool items are recorded as a
     *heuristic* violation.
5. **Study 1 and Study 2 each record an explicit web-access policy.**
   - Study 1: `none` (no web tool is configured; web-access items observed in a trial are a
     deviation).
   - Study 2: `equal_web_search`, which remains **unsupported** until an equal web-search tool can
     be configured in every arm.
6. **The actual capability configuration, observed tool use and every deviation are logged per
   trial** (record field `capability`, plus `violations`).

## 3. Violation codes

**Superseded (still recorded, now non-invalidating, marked `superseded_by: "A1"`):**
`egress_not_restricted` and `egress_unverified`. `egress_unexpected_destination` is unchanged; it
applies whenever an egress log exists.

**New, invalidating under A1:**

| Code | Meaning |
| :--- | :--- |
| `capability_configuration_unrecorded` | The trial did not log its capability configuration or its scorer-isolation evidence |
| `non_mcp_capabilities_differ` | Configured non-MCP tools or the executor runtime differ from the run's capability policy |
| `execution_environment_differs` | The network or model transport differs from the run's policy |
| `web_access_policy_differs` | The trial's web-access policy is not the study's |
| `web_access_policy_deviation` | Web-access tool use was observed although the policy is `none` |
| `scorer_material_exposed` | A scorer or reference file was reachable from candidate mounts |
| `reference_access_suspected` | Heuristic: non-MCP tool items reference the scorer or reference locations |
| `pre_amendment_trial` | The trial started before the effective time |

All other 1.0.0 codes and their invalidating status are unchanged.

## 4. Unchanged

The following are not amended:

- the primary estimand (B − A, intention to treat, equal task weights);
- randomization and assignment;
- outcome definitions, including candidate failure scored as 0;
- the missing-data rules;
- statistical inference;
- multiplicity control;
- the confirmatory minimum (30 tasks);
- the model and effort;
- the arms and their texts.

## 5. Compatibility

- **Scope.** A1 applies only to trials of runs whose `run_config.json` declares
  `protocol_amendment: "A1"` and that started at or after the effective time. Such records carry
  `protocol_version: "1.1.0+A1"`.
- **No retroactive eligibility.** Historical results and any record produced without the A1
  declaration keep the 1.0.0 evaluation, including their invalidating egress violations. A record
  converted under A1 whose trial started earlier receives `pre_amendment_trial`.
- **Nothing is removed.** Superseded codes remain in every A1 record with their original detail.
- **Binding.** A run directory is bound to its protocol version: resuming under a different
  version or capability policy is rejected.
- **No pooling.** Records evaluated under 1.0.0 and under A1 are reported separately.

## 6. Rationale and residual limitations

The causal comparison needs the arms to differ only in MCP access. The 1.0.0 topology rule was a
means to that end. As written, it could not be met by the runner, and it would have excluded every
trial without distinguishing a valid comparison from an invalid one. A1 checks the end directly and
logs the evidence per trial.

Stated limitations:

- **Shell network access remains.** The executor can still reach the network from its shell.
  "No web" in Study 1 is enforced by tool configuration and instructions, not by the network. Shell
  downloads are visible as `command_execution` items, and only the heuristic reference check
  inspects them.
- **The repository is public.** Its scorers could in principle be fetched from the network.
  `reference_access_suspected` detects references to their locations in tool items; it cannot
  detect every possible access.
- **Not empirically verified.** No real-model run has yet confirmed that the evidence fields are
  populated as in the mocked end-to-end tests.
