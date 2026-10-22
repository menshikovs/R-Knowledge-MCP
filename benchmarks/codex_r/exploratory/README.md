# Nine-trial exploratory Codex pilot: offline preparation

This is a separate exploratory protocol for R01, R06 and R11, each assigned
once to conditions A, B and C. Its fixed seed is 1729; the generated order is
stored in `../reports/exploratory-pilot-plan.json`. The plan fixes `gpt-6-luna`,
reasoning `medium`, a 900-second per-row wall-time target, and a $10 total
aggregate ceiling. It does not alter the preregistered 72-trial manifest or its
30,000-token limit.

## Current gate: blocked

Only no-inference metadata checks and a synthetic dry-run are allowed in this
stage. No Codex model request, Managed Agents session, paid call, deployment or
merge is part of the implementation. The checked-in machine-readable report
`../reports/exploratory-pilot-preflight.json` deliberately leaves these gates
unverified:

- `MODEL_ACCESS_UNVERIFIED`: public model documentation and the local CLI's
  `--model` option do not prove that this account can use the requested model.
- `HARD_AGGREGATE_BUDGET_UNVERIFIED`: the local fake ledger is not provider
  enforcement. Managed Agents exposes per-session monetary spend controls, but
  its reported consumption/usage is best-effort and can be delayed; nine
  independent sessions do not establish a strict aggregate ceiling.
- `AGENT_ISOLATION_UNVERIFIED`: exact tool exposure is checked from the local
  MCP interface self-test, but that does not prove candidate process, filesystem,
  endpoint, credential, or session isolation.

These states are blocking. There is no command here that creates or launches a
Codex session. Do not substitute a different model, transport, or budget scheme.
Any later paid experiment requires explicit authorization and a separately
reviewed protocol with provider-enforced cumulative controls and measured
independent candidate isolation.

## Verification and commands

The checked-in plan is machine-readable and independent of the existing 72-row
plan. Rebuild it deterministically, print a fresh offline gate report, or create
synthetic events for all nine rows:

```powershell
python benchmarks/codex_r/exploratory/pilot.py write-plan
python benchmarks/codex_r/exploratory/pilot.py preflight
python benchmarks/codex_r/exploratory/pilot.py dry-run
```

`preflight` exits with status 2 because the gate is blocked. The dry-run uses
only in-memory fake process/event data. Its records are tagged
`exploratory_dry_run_not_trial`, have null usage, and are rejected by the
benchmark result importer. The synthetic `BudgetLedger` refuses reservations
that exceed its total, as well as new work while spend is missing or unsettled;
this tests fail-closed client bookkeeping only and cannot guarantee provider
billing behavior.

The verified local MCP interface exposes exactly 0 tools in A, 15 in B, and 20
in C. This inventory check does not start a model and does not constitute proof
of the actual Codex-side effective inventory for a future session.

## Official interface references

- [GPT-6 model catalog](https://developers.openai.com/api/docs/models) documents
  the `gpt-6-luna` model ID, `medium` reasoning, and function tools.
- [Using GPT-6](https://developers.openai.com/api/docs/guides/latest-model) says
  reasoning tool use should use the Responses API; GPT-6 Luna Chat Completions
  function calling is limited to `reasoning_effort: "none"`.
- [Managed Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview),
  [create-session reference](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create),
  and [observability](https://developers.openai.com/api/docs/guides/agents-api/observability)
  describe session configuration and usage/spend controls. They do not verify
  this account's access or establish a provider-enforced shared $10 cap over the
  nine proposed sessions. Session `spend_control` is a per-session amount in
  cents; session usage and consumed amounts are best-effort and can be null or
  change as accounting arrives.
- The PATH-based CLI subprocess reports `codex-cli 0.162.0-alpha.17.2`; the
  interactive PowerShell `codex --version` resolved a different executable and
  reported `0.162.1`. This executable mismatch itself needs resolving before
  any future run. Both checks were metadata-only and did not inspect credentials
  or invoke inference.

Public API documentation verifies interface support, not account availability,
actual charges, or an execution boundary. The exploratory results must not be
pooled with the preregistered benchmark.
