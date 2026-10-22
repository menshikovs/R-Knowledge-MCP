# Controlled Codex execution adapter

## Current status: strict execution is blocked

This module currently implements a fail-closed preflight and an offline dry-run.
It does **not** start Codex, call a model endpoint, read Codex credentials, or
create benchmark records. The blocking limitation is specific: the frozen
protocol requires a *preemptive per-trial cumulative ceiling of 30,000 model
tokens*. Codex CLI 0.162.1 exposes `codex exec --json`, `--ephemeral`, `--model`,
`--ignore-user-config`, and configuration overrides, but its token usage is
reported as turn usage after generation. The reported count cannot stop a model
request before it exceeds the remaining token allowance.

The current OpenAI Managed Agents API is another supported Codex harness path.
It offers isolated hosted or self-hosted environments, explicit model/reasoning
configuration, MCP tool allowlists, session events, and a spend control in USD.
Its public session result describes usage as best-effort session token usage; the
documented spend control is a monetary ceiling, not an exact token ceiling. The
controller must not convert 30,000 tokens to an estimated dollar figure or use
post-completion usage as a hard limit. A hostile-but-isolated hosted environment
also does not meet this benchmark until the frozen R image, endpoint policy,
artifact export and gateway route have been independently verified.

No supported adapter currently combines all required controls. Until a provider
offers a preemptive cumulative token guard (including reasoning/tool model usage)
and the full boundary audit passes, `preflight` returns `blocked`. The existing
study protocol remains unchanged. A future separate, explicitly preregistered
exploratory protocol could use a fixed per-trial monetary cap with a declared
model-specific token estimate and report the estimate as nonbinding; it must not
be pooled with the preregistered 72-trial token-capped study.

## What is implemented

`controller.py` derives A/B/C session configuration from the randomized plan and
the committed manifest. It rejects unassigned trials, changed benchmark hashes,
changed production baselines, mutable image tags and mismatched effective MCP
inventories. It makes the intended fresh-session, public-workspace-only, no-web,
and allowed-gateway configuration reviewable. Those declarations are not
represented as a proven container boundary.

`validate_public_workspace` checks that a newly prepared candidate workspace is
outside the evaluator tree and contains only the public task, lockfile and CSV.
Its result deliberately says `boundary_verified: false`: a filesystem listing
cannot prove what a remote agent can read. `preflight` additionally refuses to
launch because there is no verified isolated Codex adapter, restricted model
route, hard token guard, authenticated model check, or controlled frozen-image
check in this implementation.

`dry_run` accepts only a `FakeCodexProcess`. It exercises synthetic completion,
missing-usage, unexpected-exit, timeout/termination, cleanup, and redaction paths.
Its output is tagged `controller_dry_run_not_trial`, reports usage as null, and
cannot be imported by `bench.py record` as a benchmark observation. It makes no
network request and never reads a credential.

## Commands

Create a plan using the existing benchmark interface and an already verified
immutable R image ID:

```sh
python benchmarks/codex_r/runner/bench.py plan \
  --model EXACT_MODEL_ID --reasoning-effort high \
  --image sha256:ACTUAL_IMAGE_ID --seed 1729 --repetitions 2 --output plan.json
```

Print the exact preflight blockers for an assigned row. A blocked result returns
exit status 2 and is never a launch fallback:

```sh
python benchmarks/codex_r/runner/controller.py preflight \
  --plan plan.json --trial R01-A-1
```

Run the offline adapter dry-run; this uses a synthetic process event and does not
contact Codex or create a trial record:

```sh
python benchmarks/codex_r/runner/controller.py dry-run \
  --plan plan.json --trial R01-A-1 --output dry-run.json
```

There is deliberately no `run` command. The optional real pilot is not available
until preflight can verify all requirements. No paid model trials were started.

## Authentication and security

The dry-run does not probe authentication because even a no-task API/model probe
can incur account activity, and it cannot prove availability of the preregistered
model snapshot or its supported reasoning setting. A future adapter must check
authentication without printing or logging credential contents; use a short-lived
least-privilege credential held outside the candidate container. Do not put a key
in plan/config JSON, command-line arguments, candidate environment variables,
gateway audit, trial JSONL or artifacts.

Before enabling execution, an adapter must demonstrate with external evidence:

- separate disposable candidate container/VM per trial; no evaluator, oracle,
  reference, prior attempt, scoring result, Docker socket, host filesystem or
  evaluator/other-trial credential is reachable;
- the model harness can reach only its controlled endpoint and, for B/C, the
  separate recording gateway; the candidate cannot browse arbitrary websites;
- the gateway audit and process are outside candidate-visible mounts;
- effective tools equal exactly zero in A, the manifest's 15 in B, and the same
  15 plus five PI tools in C; no inherited MCP, plugin, web, prompt or resource
  route is present;
- each assignment receives a fresh ephemeral session with no resume, prior
  messages, user/project configuration, skill, plugin, memory or cache carryover;
- exact provider-resolved model and reasoning effort are fixed and recorded;
- hard wall-clock termination kills the process tree and all MCP processes;
- a preemptive cumulative 30,000 model-token limit can stop further inference
  before the next request would exceed the limit, including reasoning tokens;
- the exact frozen R image is mounted and public artifacts can be sealed before
  the oracle is attached in a separate scoring step.

An operator attestation alone is not enough to make the controller's isolation
check pass. A future adapter needs measured boundary probes and retained run
evidence. This branch leaves real execution blocked rather than weakening any
of these requirements.

## Validation

`tests/test_codex_controller.py` uses only synthetic plan/event data. It tests
condition configuration, exact allowlist enforcement, fresh-session flags,
public workspace restrictions, credential redaction, missing token usage,
timeouts/forced termination, unexpected exits, cleanup status, invalid plans and
the hard preflight blocker. The repository's usual `ruff` and `pytest` checks
also cover the existing benchmark importer, scorer and gateway.

## Authoritative interfaces reviewed

- [Codex CLI non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
  [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference),
  and the installed `codex exec --help` (CLI 0.162.1).
- [Managed Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview)
  and [create-session reference](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/methods/create).
- [Agents API configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration)
  and [session observability](https://developers.openai.com/api/docs/guides/agents-api/observability).

The docs support explicit model/reasoning, environment selection, MCP
`allowed_tools`, usage reporting, and spend controls. They do not document the
required per-session hard total-token ceiling for a Codex tool loop.
