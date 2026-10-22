# Execution capability audit (2026-10-22; controller branch update)

Inspected Codex CLI 0.162.1 using --version and exec --help; no agent was started.
Official interfaces were checked against [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

| Capability | Evidence / boundary |
| --- | --- |
| Fresh independent sessions | exec, --ephemeral and --ignore-user-config exist; never use resume/fork for trials |
| Explicit model/reasoning | --model and -c model_reasoning_effort supported; exact authorized model ID must be preregistered |
| Workspace selection | --cd exists; host sandbox writes control DOES NOT establish hidden-test read isolation |
| JSON events/actual usage | --json supported; importer reads actual turn.completed usage if supplied |
| Condition tool filtering | Benchmark stdio gateway enforces fixed list AND call allowlists; no production registration changed |
| Time/resource bounds | Implemented for disposable R/scorer containers; external agent controller must enforce its own deadline |
| Token/cost hard cap | No uniform supported controller verified; token metrics at end do not enforce a hard pre-call budget |
| Credential/model account | No secrets inspected, no model requests or available paid quota verified |
| Artifacts and scoring | Implemented independent safe source import plus offline R/testthat container evaluation |
| Full agent execution | NOT implemented/claimed; external authenticated isolated agent controller required |

An additional review checked the current official Managed Agents API after the
benchmark branch was merged. Its public interface supports explicit model and
reasoning settings, hosted/self-hosted environments, MCP `allowed_tools`, session
events, and a monetary spend control. Session token usage is described as
best-effort/reporting; no preemptive cumulative total-token budget for the
Codex agent/tool loop is documented. A USD spend ceiling is not equivalent to
the benchmark's 30,000-token budget and is not used as a substitute. The API is
therefore not enabled as a real-run adapter here.

The new `runner/controller.py` supplies an offline configuration/preflight path
and fake-process dry-run only. Its preflight always remains blocked until a real
adapter supplies verifiable isolation, endpoint, authentication, image and hard
token-budget evidence. No Codex credentials were read and no model API request or
paid trial was made. See `runner/CONTROLLER.md` for details and the proposed
non-comparable monetary-cap alternative.

Supported CLI building blocks are not evidence of an operational blinded experiment.
Do not run the CLI in the evaluator repository, expose the host filesystem, mount a
Docker socket, or assume --ignore-user-config disables administrative/system policy.
The external operator must audit effective tools, plugins, skills, inherited memory,
network egress, fresh workspace inputs and model snapshot; retain that inventory.
For B/C configure only the gateway as an MCP connection and mark it required; verify
the actual exposed tools against manifest.json before timing. For A no gateway or
other MCP connection is permitted. Disable ordinary browsing in every condition.
A token-accounting event emitted only at turn completion cannot enforce a strict
per-trial cap by itself. Never invent an unsupported CLI budget flag.
