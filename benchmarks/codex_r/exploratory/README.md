# Nine-trial exploratory Codex pilot

This is a separate exploratory protocol for R01, R06 and R11, each assigned
once to conditions A, B and C: A exposes 0 MCP tools, B exposes 15 core tools,
and C exposes 20 tools including Prompt Intelligence. The fixed model is
`gpt-6-luna` with `medium` reasoning; each trial is limited to 900 seconds.
Its nine rows and results are separate from the original strict 72-trial
benchmark and do not alter that protocol, its token guard, or its artifacts.

## Balance-aware policy

The operator's approximate $10 prepaid balance is an opening estimate, not an
aggregate spending ceiling. The pilot does **not** require a provider-enforced
hard $10 cap. The client ledger is a best-effort checkpoint record and cannot
limit provider billing. Usage and cost accounting may be delayed, so charges can
exceed the balance most recently displayed by the operator.

Before each individually authorized trial, the operator records the current
available credit balance and chooses a conservative reserve. The default
reserve is 200 cents and can be changed in `BalanceAwareLedger`. The ledger
refuses to record an authorization when the balance is unknown or at/below the
reserve, or while another trial is active. Authorization only records the
operator's decision; this module has no real session launcher.

After each completed trial, stop and review all four items before making any
new decision:

1. Provider-reported spend for the session.
2. Session usage values.
3. Independent correctness/scoring review.
4. A fresh available-credit balance and reconciliation against reported spend.

Missing or unreconciled spend, usage, or balance permanently stops the current
ledger. A clean checkpoint never authorizes the next trial automatically; a
new explicit operator decision is required. The balance check is advisory and
cannot prevent delayed charges. OpenAI's documented Costs API returns
time-bucketed organization costs and is not a live prepaid-credit balance
endpoint; an operator dashboard balance and provider-reported session usage
must remain separate observations. Do not infer a remaining balance from token
usage or the Costs API.

Example offline ledger flow (no Codex process or API request is started):

```python
from benchmarks.codex_r.exploratory.pilot import BalanceAwareLedger
import json
from pathlib import Path

ledger = BalanceAwareLedger(
    available_balance_cents=1000,  # manually checked operator dashboard value
    reserve_cents=250,  # operator-selected conservative reserve
    balance_source="operator_dashboard",
    checked_at="2026-10-23T10:00:00Z",
)
authorization_record = ledger.authorize_one(
    "R01-A",
    operator_authorized=True,  # affirm only after separately authorizing this one trial
    estimated_spend_cents=150,  # operator estimate; explicitly non-binding
)
Path("exploratory-ledger.json").write_text(
    json.dumps(ledger.audit_record(), indent=2) + "\n", encoding="utf-8"
)
# A separately reviewed execution adapter would run exactly this one row.
# After that session completes, provide observed spend, usage, scoring review,
# and a newly checked balance to ledger.checkpoint(...).
# Export audit_record() again after the checkpoint; keep the prior record too.
```

Do not call `authorize_one` as a substitute for an execution preflight. The
preflight still blocks on all of the following:

- Actual account/model access for `gpt-6-luna` is unverified. The public model
  page confirms the API model and reasoning setting, but not account access.
- Actual candidate/agent isolation is unverified; no isolation evidence is
  claimed by a local workspace check.
- Hidden oracle exposure has not been independently ruled out for a real agent.
- Actual effective MCP tool inventories in the execution environment are not
  verified, even though local manifest inventories are 0/15/20.
- Explicit operator authorization is required separately for every paid trial.
- No real execution adapter is implemented or verified in this offline pilot.

Therefore there is no command in this repository that launches a paid trial.
No inference request, session creation, authentication probe, or credential
inspection is performed by preflight or dry-run. One trial must be authorized
and reviewed at a time after the isolation and execution interface receive a
separate security review. Do not automatically start all nine rows.

## Offline commands and validation

```powershell
python benchmarks/codex_r/exploratory/pilot.py write-plan
python benchmarks/codex_r/exploratory/pilot.py preflight
python benchmarks/codex_r/exploratory/pilot.py dry-run
```

`preflight` returns status 2 while launch gates are blocked. The dry-run uses
only in-memory synthetic data and creates no benchmark records. The tests mock
Codex discovery and metadata commands; no local Codex installation or API
credentials are required.

The single-trial runtime and its exact execution blockers are documented in
[ADAPTER.md](ADAPTER.md). A separate Codex 0.163.0 image based on the unchanged
frozen R image has been built and its real `codex exec-server` process has been
started in a networkless, restricted Docker candidate container. The
Managed Agents API configuration/client has mocked offline coverage. No API
session or model turn was created; `run-one` remains fail-closed because a
path-aware egress broker/relay and remaining lifecycle integrations are not
verified.

The [Docker/WSL2 offline runtime probe](ADAPTER.md#rebuild-and-offline-checks)
uses the pinned Codex image, runs the actual executor binary with only the
public workspace mounted, and verifies the fixed filesystem/network boundary
and container cleanup. It does not verify remote executor registration,
effective tools in a Managed Agents session, account access, or model
connectivity.

## Official interface references

- [GPT-6 Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna)
  documents the model ID, `medium` reasoning and Responses API tool support.
- [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
  describes reasoning configuration and tool use.
- [Codex config basics](https://learn.chatgpt.com/docs/config-file/config-basic)
  documents setting `model_reasoning_effort = "medium"` and MCP servers in
  local Codex configuration. The preflight only checks CLI model/config flags;
  it does not verify a real model turn or the effective tools in a session.
- [Spend limits](https://developers.openai.com/api/docs/guides/rate-limits#spend-limits)
  distinguishes alerts from provider-enforced hard limits. This pilot does not
  require the latter.
- [Admin API costs reporting](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)
  returns time-bucketed organization costs; it is not treated as a prepaid
  balance lookup or a real-time per-session kill switch.

The official API documentation establishes public interface capability only.
It cannot establish account access, effective tools, actual spend, or a safe
execution boundary. Pilot findings must never be pooled with the strict 72-trial
benchmark.
