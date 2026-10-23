# Independent root-cause audit: R01-A Managed Agents execution

Audit date: 2026-10-23. Audited baseline: `8b3ef1c` (main, including PR #24).
Scope: exploratory adapter and its controller, HTTP client, Docker boundary,
proxy, ledger, scorer handoff, serialization, tests and CI. This is an audit,
not a change to execution policy. All four attempts are historical and closed.
No fifth attempt is authorized or recommended as an automatic next step.

## 1. Executive summary

The repeated failures are consistent with components tested independently
against different contracts, rather than an exercised end-to-end execution
contract. There is a **PROVEN, still-present duplicate URL validator defect**:
the HTTP client accepts endpoint subpaths and trailing slashes, but the Docker
executor still rejects both. An offline, container-free reproduction confirmed
this inconsistency. It is a strong candidate for the fourth failure, **not a
proven diagnosis of that historical execution**: its safe URL shape and original
exception reason are unavailable here.

The misleading fourth-attempt message is **PROVEN explainable by code**. The
lifecycle initializes `session_creation_attempted=False` and only refreshes it
from the client in `finally`, after constructing its generic failure message.
Thus a successful session can coexist with a message saying the executor failed
before session creation. Docker exception messages and subprocess error context
are then discarded; teardown can remove the only remaining container logs.

The supplied checkpoint does not establish a 1004-cent charge. The spending
field is entered by the operator, not read from provider billing. The ledger
correctly rejects `1004 - 1004 != 1004` and missing usage as unreconciled. No
historical financial value should be repaired by inference.

**Decision: NO-GO for further live execution.** First eliminate the cross-layer
contract mismatch and demonstrate the actual runtime method, serialization,
failure handling and deadlines offline. Separately preserve and review safe
evidence of the fourth attempt. Passing those checks would establish readiness
for review, not authorization for another attempt.

## 2. Evidence scope and confidence

**PROVEN** means directly observed in inspected code or in this audit's offline
reproduction. **LIKELY** means multiple observations support a hypothesis but
the actual historical cause is not established. **UNKNOWN** means insufficient
evidence. High confidence in a code defect is not high confidence that it caused
a particular incident.

The incident facts below come from the operator's supplied task. They were not
independently read from the historical WSL files. A read-only `wsl.exe --list
--quiet` returned `Wsl/EnumerateDistros/Service/E_ACCESSDENIED`; read-only
`docker ps --all --filter name=rkmcp` could not access
`dockerDesktopLinuxEngine` (permission denied). The Windows home equivalent of
the state directory was absent; that says nothing about the WSL home. No actual
historical audit, authorization, checkpoint, inventory or Docker log was read,
modified or normalized. No privileged retry of those inspections was needed
to establish the static findings.

Repository implementation inspected (line references below are for the audited
baseline; filenames without prefixes are under `benchmarks/codex_r/exploratory/`):

- `adapter.py`: CLI and context, fingerprints, authorization, leases, markers,
  runtime factory, checkpoint review, cleanup verification, historical
  validators, serialization and result inspection.
- `lifecycle.py`: full controller, artifact validator and failure/cleanup paths.
- `managed_agents.py`: client, configuration, URL validation, SSE, submission,
  cancellation and deletion.
- `docker_runtime.py`: command wrappers, policy construction/inspection, image
  and workspace checks, executor startup/stop, topology and offline probes.
- `egress_proxy.py`: request validation, DNS restrictions, tunnel and logs.
- `pilot.py`: balance ledger, checkpoint and redaction.
- `../runner/bench.py`: artifact sealing, Docker command/scoring, output bounds;
  `../runner/controller.py`: public workspace and inventory boundaries.
- `../runtime/candidate.Dockerfile`, `../runtime/egress.Dockerfile`,
  `../configs/Dockerfile`; `ADAPTER.md` (status, protocol, operating guidance
  and limitations); root `AGENTS.md`, `.github/workflows/tests.yml`.
- `tests/test_codex_managed_agents.py`,
  `tests/test_codex_managed_agents_lifecycle.py`,
  `tests/test_codex_docker_runtime.py`, `tests/test_codex_egress_proxy.py`, and
  historical-provenance/serialization tests in
  `tests/test_codex_single_trial_adapter.py`.

Official pages opened during this audit (documentation retrieval only, no
authenticated API calls):

- [Self-hosted sandboxes](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted)
- [Sandbox security](https://developers.openai.com/api/docs/guides/agents-api/environments/security)
- [Sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions)
- [Events and items](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)
- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)

Current documentation cannot prove the exact service contract at a historical
execution time, account-specific capability, or the pinned CLI's live behavior.

## 3. Incident timeline

| Event | Supplied observations | Interpretation and evidence boundary |
| --- | --- | --- |
| Attempt 1 | ManagedAgentsError; no confirmed HTTP status or creation; no inference; local cleanup | Initial remote outcome unclassified. Later inventory is separate evidence, not retrospective proof that create never succeeded. |
| Attempt 2 | Local self-lock rejection before session creation; cleanup | Lease acquisition conflicted with a cleanup check that expected no lock. Current ownership-aware code addresses this; historical audit preserved. |
| Attempt 3, recovery | HTTP 201 then response-schema rejection of remote URL; no inference | Client rejected successful creation. Remote state was initially uncertain; operator reports a later complete official inventory contained zero sessions. |
| Final-continuation preparation | Legacy fields and redacted authorization ID rejected | Compatibility failures occurred before final authorization/execution. PRs #23/#24 address these paths; they are not additional model trials. |
| Attempt 4, final continuation | One session created; resolved Luna/medium/empty tools; start_executor DockerRuntimeError; zero task submissions/inference | Failure is after session creation and before observed executor connection. Exact Docker sub-operation is unknown. |
| Final cleanup/checkpoint | Deletion and local cleanup reported true; 1004/1004/1004 checkpoint unreconciled; subsequent local cleanup check clear | Local absence is distinct from provider deletion. Spending remains unknown. Final authorization is consumed. |

PR #22 fixed `managed_agents.py` URL handling; current `docker_runtime.py`
retains the original exact-path restriction. PR #24's regression now persists
the third audit through the real writer, a useful improvement over hand-written
JSON. It does not test executor startup.

## 4. End-to-end lifecycle reconstruction

The names in `STATES` are membership-checked, not an enforced transition graph
(`lifecycle.py:80-96,213-218`). For example, `stream_events` is recorded before
`start_executor`; network setup is only `current_operation`, not a state;
`terminate_container` is appended after teardown. State history is therefore
an orchestration trace, not proof of each side effect's completion.

| Stage / references | Preconditions, dependencies and effects | Failure, retry, audit and cleanup / coverage |
| --- | --- | --- |
| CLI/context, `adapter.py:2191-2442,166-307` | Select fixed R01-A; derive image/runtime fingerprints; read public workspace and preserved history | Value/Adapter/OSError failures stop before API. No retry. CLI preflight error may lack lifecycle audit. Provenance tests mock Docker cleanup. |
| Historical provenance, `adapter.py:1372-1770` | Legacy audit/auth contracts, SHA-256 byte bindings, expired second auth, consumed markers, complete fresh independent inventory | Reject changed history, active/unknown statuses, fifth marker. Local Docker listing is not remote inventory. Current tests cover legacy/redacted shapes. |
| Authorization, `adapter.py:459-809,1036-1103` | Exact trial/model/tools, public workspace, image/config digest, balance, UTC TTL <=300 s, explicit confirmations | Creates private exclusive authorization only when separately requested. No API. Audit task did not invoke it. Tests use isolated fixture records. |
| Runtime construction, `adapter.py:1106-1159` | Separate keys, exact image/base layers/version, R scorer image, workspace | Real Docker version probe creates a disposable container during normal launch; not invoked here. Presence/scope attestation is not service verification. Errors can precede lifecycle audit creation. |
| Lease/consume, `lifecycle.py:220-232`, `adapter.py:830-1001` | Own exclusive lock; revalidate under lease; create exclusive trial marker then auth marker; activate ledger | Fail closed on existing/foreign lock or marker. No rollback/retry. Two marker writes are not a single crash-durable transaction; conservative partial consumption blocks reuse. |
| Restricted topology, `lifecycle.py:233-244`, `docker_runtime.py:994-1217` | Build proxy, create outbound/internal networks, attach sidecar, readiness and policy checks | DockerRuntime/timeout/OSError/JSON errors; startup cleanup attempted. Partial teardown can mask original failure. Audit stores topology summary, not all resource IDs/logs. |
| Create session, `lifecycle.py:245-251`, `managed_agents.py:289-377` | One POST, controller app key, no initial input; returned model/effort/tools must match | Exactly one create per client. No automatic retry. Track successful response before schema validation; delete usable ID if validation fails. Unknown-ID failure remains uncertain. HTTP mock coverage good; no live compatibility proof. |
| Response/URL, `managed_agents.py:88-172` | HTTPS, reviewed API host/port, path namespace, forbidden component checks; URL preserved | Safe reason codes and field names. A second inconsistent runtime validator remains (F01). |
| SSE initialization, `managed_agents.py:436-465` | Controller GET stream, no redirects, SSE content type | On successful stream headers call executor-start callback; this is before connection/task. HTTP failures are normalized without equivalent create-session diagnostics. No reconnect/retry. |
| Executor create/start, `lifecycle.py:253-268`, `docker_runtime.py:829-946` | Topology, URL, workspace, image/version, bind/policy, scoped key, create/start/top | Many generic DockerRuntime errors; real method is bypassed in lifecycle Docker test. Process name evidence is not registration. Startup cleanup may remove logs before outer audit. |
| Readiness/task, `managed_agents.py:499-507`, `lifecycle.py:270-295` | Require environment.connected event; start watchdog; submit one input event with idempotency key | One submission attempted per client/session; ambiguity tracked, no retries. SDK/service automatic executor reconnect is a different layer. Resolved config alone does not verify coding commands. |
| Events/finish, `managed_agents.py:467-538`, `lifecycle.py:305-324` | Bounded events, terminal completed outcome, connection observed | Timer kills candidate only after connected; stream read timing is separate. Cancel/failure stops; unsuccessful outcomes do not score. Events buffered in memory. |
| Cancel/delete/terminate, `lifecycle.py:356-439` | On primary failure try cancel; stop/remove container; confirm provider DELETE; close client; tear down topology | Cancellation exception swallowed. Deletion uncertainty blocks aggregate cleanup. No API retry. Resource absence is recorded as booleans; phase times/secondary errors largely lost. |
| Export/score, `lifecycle.py:466-485`, `../runner/bench.py:239-266,321-363` | Only after verified teardown; bounded regular allowlisted files; sealed hashes; networkless scorer with oracle mounted there only | Symlink/traversal/special/unexpected files rejected. Scorer failures distinguished partly; no inference. Sealed temp copy discarded after scoring; original workspace remains. Strict benchmark implementation not changed. |
| Checkpoint, `adapter.py:1163-1186`, `pilot.py:410-482` | Interactive spend, balance, source, usage extracted only from explicit completed-turn events | Unavailable or inconsistent values stop ledger; raw operator number still stored as reported spend. No automatic continuation. Input is unbounded in time. |
| Release/persist/inspect, `lifecycle.py:514-525`, `adapter.py:1014-1033,2000-2031,2384-2442` | Release own lease only on clean branch; exclusive final JSON writer with recursive redaction | Final evidence is written only after run returns/raises and checkpoint interaction. Crash gaps, redacted provenance IDs and limited inspect-result fields are material weaknesses. |

## 5. Fourth-attempt DockerRuntimeError: exhaustive reachable paths

There is **no Docker SDK** here: Docker operations use `subprocess.run` via
`_bounded_run`/`_docker`. Docker HTTP status is not exposed by this CLI wrapper.
It must remain null, not be invented from the CLI exit code.

| Reachable startup phase | DockerRuntimeError causes / related exceptions | Safe evidence that would distinguish it |
| --- | --- | --- |
| Local validation, `docker_runtime.py:846-862` | Topology inactive/default network; invalid environment ID; missing scoped key; stale exact remote path | Reason code and failing component; booleans for URL policy checks, not URL contents |
| Workspace, `351-364,863` | Input inventory invalid, evaluator-root containment, unrepresentable bind path; controller errors wrapped | Validated inventory hash, path mapping class, UID/GID access booleans |
| Image, `665-713,864` | Wrong immutable ID/user/workdir/entrypoint/base layers, pinned version mismatch; Docker image inspect/run failure | Image/CLI versions, failing command kind, exit class; no Config.Env dump |
| Proxy/argv, `366-443,865-883` | Invalid proxy string policy; `ipaddress`/URL parsing can raise ValueError instead | Private-IP/subnet check booleans and network ID; exclude key and remote argv |
| Create, `264-285,884` | CLI timeout/OSError/output overflow; daemon nonzero; malformed returned ID; cleanup/name-absence failure | Create exit code, generated resource name/ID, allowlisted error code, bounded scrubbed diagnostic |
| Policy inspection, `445-492,886-909` | Incomplete inspect; unexpected mounts/source/tmpfs/user/security/resource state; network/key presence mismatch | Actual versus expected field names/booleans, filtered inspect projection. JSON decoding may instead raise ValueError. |
| Start/process, `910-938` | Start/top/inspect CLI rejection; executor exits; five-second process visibility expiry | State, exit/OOM flag, time to startup, filtered runtime log classifications |
| Cleanup wrapper, `939-960` | Stop/remove cannot verify; wrapper can replace primary error with cleanup error | Preserve primary and cleanup failure separately, resource ownership and removal evidence |
| Shared subprocess, `187-205,241-250` | Timeout subclass; executable/daemon OSError; nonzero discarded stderr; output cap checked only after capture | Operation/sub-operation, timeout, bounded streaming capture, code classification |

The exact fourth root cause is **UNKNOWN**. Session creation means the daemon
and topology had worked earlier in that run; it does not rule out later daemon
failure, a mount/policy mismatch, workspace permissions, pinned CLI failure, or
network problems after process startup. The early URL check can fail without
any candidate container being created.

**LIKELY candidate:** the remaining fixed-path validator rejected the same
URL family that the repaired HTTP validator accepted. A read-only in-process
probe passed synthetic trailing-slash and subpath records through
`validate_environment_record`, then called the runtime with a synthetic active
topology. Both failed at the local URL check, before workspace checks or Docker:

```text
trailing_slash: client ACCEPTED; runtime REJECTED: Executor remote URL is outside the documented endpoint
subpath: client ACCEPTED; runtime REJECTED: Executor remote URL is outside the documented endpoint
```

This proves the mismatch, not the historical URL. No URL is recovered or
rewritten. A different actual URL or a later error would require a different
incident diagnosis.

Other unresolved hypotheses: WSL bind-source translation, UID 65534 unable to
write public workspace, Docker inspect mount representation (including tmpfs),
binary/runtime dependency failure, start/top timing, or proxy/TLS/WSS failure.
None has preserved direct evidence here. The image has a pinned exec-server
entrypoint and correct command arrangement; root is read-only with writable
tmpfs and workspace. Those choices are not themselves proof of a permission
failure. Do not relax them speculatively.

## 6. Findings ranked by severity

No Critical finding is established: no credential disclosure, unauthorized
inference or oracle exposure is proven. The following are actionable defects
and limits, not assertions that each caused a live failure.

| ID | Severity / confidence | Finding and exact references |
| --- | --- | --- |
| F01 | High / PROVEN | Inconsistent URL contract: `managed_agents.py:148-171` vs `docker_runtime.py:852-862`. Offline reproduced. |
| F02 | High / PROVEN | Stale lifecycle flags create false temporal diagnostics: `lifecycle.py:179,245-251,346-355,378-397`. |
| F03 | High / PROVEN | Docker root cause and forensic evidence lost: `docker_runtime.py:187-205,247-249,939-946`; `lifecycle.py:346-355`; `adapter.py:2410-2425`. |
| F04 | High / PROVEN | Existing Docker lifecycle test replaces production executor startup: `tests/test_codex_managed_agents_lifecycle.py:526-539`; CI `.github/workflows/tests.yml:27-32` builds production MCP image only. |
| F05 | High / PROVEN | Deadline is not one global bounded lifecycle: `lifecycle.py:270-288`; `managed_agents.py:437,449-451,467-469`; `adapter.py:1167-1177`. |
| F06 | Medium / PROVEN | Operator-entered spend is not provider telemetry: `adapter.py:1163-1185`; `pilot.py:425-468`. Ledger stops correctly, but field provenance is ambiguous. |
| F07 | Medium / PROVEN | Audit redaction and historical schema assumptions broke provenance preflight: `adapter.py:60-88,1014-1033,1372-1770`; prior PR fixes and fixture history. |
| F08 | High / PROVEN | Failure/cleanup bookkeeping is not crash-safe durable evidence: `lifecycle.py:159-200,325-439,441-464,495-525`; `adapter.py:975-1000,1014-1033`. |
| F09 | Medium / PROVEN | Startup gates are local checks/attestation, not TLS/WSS or account proof; `adapter.py:1144-1159`; `docker_runtime.py:914-928`; `ADAPTER.md:90-111,553-565`. |
| F10 | Medium / PROVEN (coverage limit) | Sanitizers cannot guarantee removal of arbitrary scoped keys or signed URLs in free text: `managed_agents.py:540-565`; `adapter.py:60-88`. Actual leak UNKNOWN. |
| F11 | Low / PROVEN | Operating/status and result inspection obscure reality: `ADAPTER.md:3,113-115,557-565`; `adapter.py:1-6,2000-2031`. |

### F01: duplicated endpoint policy

Cause: PR-level repair stopped at the API response boundary; runtime policy was
not part of its contract test. Impact: consume authorization/create session,
then reject a URL already accepted by the upstream parser. Remediation: one
reviewed validation contract shared by both boundaries, preserving exact
server-issued value and fixed trusted origins/ports. Offline verification:
every permitted and malicious URL fixture traverses parsing **and the actual
startup method**, with subprocess injected; assert zero Docker calls on rejection.
Do not automatically expand hosts or rewrite routes.

### F02: contradictory temporal diagnostic

Cause: the local record remains `session_creation_attempted=False` during error
formatting, despite `session_created=True`; refresh occurs later in `finally`.
Impact: fourth failure is mislabeled as pre-session. Remediation: transition
the operation flags before external calls and keep authoritative response flags
consistent throughout; describe observed phase rather than infer it from stale
state. Offline verification: inject a DockerRuntimeError after valid HTTP 201;
assert create=true, start failed, task=false and no pre-create wording.

### F03: generic normalization destroys diagnosis

Cause: `_docker` drops return code/stderr; DockerRuntimeError lacks structured
diagnostics; lifecycle drops its safe message and exception chain. Cleanup
removes the candidate/proxy before logs are exported. Impact: several unrelated
causes produce the identical audit. Remediation: structured reason-code mapping
at each boundary; capture filtered observations before removal without delaying
termination. Offline verification: failure injection for every row in section 5,
including cleanup failure, and serialization assertions with embedded fake
secrets to prove no raw stderr/URL/key reaches the report.

### F04: integration tests do not integrate the failing seam

Cause: `FakeRuntime` returns a container ID unconditionally; `FakeClient`
synthesizes connected immediately. Even the marked real-Docker lifecycle test
replaces `start_managed_executor` with `run_codex_proxy_transport_probe` and
returns a dummy ID. The real probe observes a synthetic CONNECT rejection, not
a TLS/WSS session. Impact: these tests cannot expose F01 or real start/policy
errors. Remediation: retain useful negative tests, add production-method
composition tests and an explicitly offline test transport seam. Verify CI
actually runs that suite with frozen images; a green MCP Docker job is not
benchmark-runtime certification. See section 8.

### F05: fragmented deadlines

Cause: the watchdog begins only at environment.connected; executor validation
and startup occur earlier. SSE checks monotonic time only when a line arrives;
its read timeout is a fresh inactivity limit, not the remaining deadline.
Checkpoint prompts have no deadline. Impact: candidate termination is bounded
after connection, but pre-connect/session lifetime/controller completion is not
bounded by one 900-second clock. Cleanup itself has additional local bounds.
Remediation: specify distinct preparation, task, teardown and operator-review
budgets; use one monotonic task deadline and remaining-time I/O, with watchdog
coverage for any running candidate. Offline verification: silent streams,
slow headers, delayed connected, blocked top, task POST timeout, no terminal
event, and timer/cleanup races with accelerated clocks. Keep the 900-second
task cap; do not claim all phases complete within it.

### F06: spending evidence is manually reported

Cause: a numeric prompt populates `reported_spend_cents`; provenance of that
number is not tied to a provider session/receipt. Impact: entering the prepaid
balance as spend can look like an actual charge. The reconciliation gate
correctly stops it. Remediation: separate operator report, provider usage,
provider-confirmed cost and unknown cost; retain original values untouched.
Offline verification: supplied 1004/1004/1004 case must retain the values,
declare mismatch and usage unavailable, and never be summarized as billed $10.04.
Unknown spending is representable today using null plus stop reasons.

### F07: schema and persistence contracts evolved separately

Cause: validators required new fields in immutable old files; fixtures originally
hand-wrote JSON without the writer's redactor. Impact: safe attempts blocked
before authorization and prompted repeated compatibility fixes. PR #24 now
exercises persisted `[REDACTED]` and validates original authorization/markers
independently. Remediation: explicit historical schema fixtures and read-only
migrations in validation, never rewrite evidence. Offline verification: golden
synthetic files for each historical shape, including real serialization and
unchanged bytes, complete inventory, markers and SHA-256 binding.

### F08: cleanup safety and durable forensics need separate guarantees

Cause: record/events live in memory until final write; checkpoint interaction
occurs before persistence. Trial/auth markers use separate exclusive writes;
only the lease is explicitly fsynced. KeyboardInterrupt/crash can leave no final
audit, a partial marker pair, or a retained lease. A successful-create failure
with valid session ID is deleted, but crash before recording can leave unknown
remote state. Early helper failures can mask the primary exception. Checkpoint
ledger exceptions and some BaseExceptions outside the main cleanup path can
skip normal release/persistence. Impact: manual forensic recovery is required;
partial markers must block rather than invite replay. Remediation: durable,
private append-only side-effect intent/outcome journal with fsync, explicit
primary/secondary cleanup errors, and release in an ownership-aware finalizer.
Preserve existing closed markers. Offline verification: subprocess crash at
each marker/create/start/delete/write boundary; assert no replay and conservative
unknown state. Also test unnamed `verify_candidate_image` version containers:
killing the Docker CLI on timeout does not itself prove container removal.

### F09: attestation and observed compatibility differ

Cause: live gates check image/workspace/key presence and operator scope
attestation. Registered executor, WSS and coding-command capabilities are only
observed later. Impact: `pre_session_gates` can be mistaken for a complete live
compatibility certificate. Remediation: label each gate's evidence class and
time, keep unobserved service behavior unknown. Offline verification cannot
prove account-specific service compatibility; enforce that distinction in all
outputs. Official scope attestation remains an explicit trust boundary.

### F10: privacy guarantees must cover values, not just keys

Cause: event sanitization removes sensitive-named fields and the application
key, but does not know the executor key; generic redaction uses patterns/key
names. A scoped key or signed URL inside an ordinary output string may escape
those checks. Impact: potential sensitive forensic output; no actual leak is
established. Remediation: allowlisted event/error projections, exact configured
secret replacement, URL suppression before bounded storage, and never dumping
Config.Env/process arguments. Offline verification: fake nonstandard secrets
and signed URLs embedded in arbitrary text, nested lists, exception causes,
stderr and tool output; check disk and stdout, not only in-memory values.

### F11: stale operating statements and thin inspection

Cause: docs/docstrings still say no live session has been created, while current
incident history reports several; inspect-result omits failure operation/reason,
attempt ID and session-creation details. Impact: incorrect interpretation and
unnecessary raw JSON inspection. Remediation: date/cite status statements and
expose a safe failure summary through the existing reader. Offline verification:
persisted failed audit summarized without secrets or semantic loss.

## 7. Session/executor protocol boundary: facts versus assumptions

The official self-hosted guide supports an OpenAI-managed harness with an
outbound local executor, registration at the API and WSS commands/results.
It requires passing the issued environment ID and remote URL unchanged.
The separate environment key is intentionally readable by sandbox code; the
application key must stay outside. Those are documented boundaries, not proof
of this account's permissions. [Official self-hosted guide](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted).

The code preserves the supplied URL in `exec-server --remote`, uses controller
HTTPX with `trust_env=False`, and supplies only the restricted environment key
to the candidate. It requests no MCP tools. Candidate user 65534, one public
bind, read-only root, dropped capabilities, limits and denied local DNS are
explicit policy. The proxy permits two reviewed destination hosts on 443;
it does **not** enforce API paths inside TLS. This is an enforceable host/port
boundary, not a credential broker or path-aware model proxy.

The official session/event guides support subscribing before input and the
terminal event names used here. Waiting for environment.connected before the
single input is a deliberate additional application condition. A process seen
by `docker top` is only process-start evidence. HTTP 201 plus resolved settings
does not prove executor registration, TLS/WSS, coding tools or inference.
[Events and items](https://developers.openai.com/api/docs/guides/agents-api/sessions/events),
[Sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions).

Luna's current model page supports medium reasoning, but it does not certify
this pinned CLI/Managed Agents/account combination. The operator's fourth
session response supports resolved configuration only.
[Model reference](https://developers.openai.com/api/docs/models/gpt-6-luna).

Unknown: actual URL path class; whether the pinned exec-server honors the proxy
through both registration and WSS; scoped key organization/project/owner match;
working directory write access; post-start connection behavior. The fake CONNECT
403 proves proxy selection at its first request only. Successful session creation
must not be used to close these unknowns.

## 8. Why did we need four attempts to discover defects that should have been caught offline?

1. **The wrong seams were replaced.** The lifecycle tests mock both client and
   runtime; the Docker lifecycle test also replaces the production start method.
   Unit coverage of each module therefore leaves the duplicated URL policy
   untested. The new URL-variant test (`test_codex_managed_agents.py:390-400`)
   only calls the HTTP validator. Green tests do not imply the URL can reach Codex.
2. **Fixtures represented intended schemas, not historical bytes.** Required
   attempt IDs/new status fields and real audit redaction were absent from early
   fixtures. PR #24 repaired one persistence seam; the same principle was not
   applied to executor startup and startup failure after HTTP 201.
3. **State tests asserted sequence without invariants.** `FakeClient` did not
   carry the production client creation flags; tests covered a genuine pre-session
   error message (`test_codex_managed_agents_lifecycle.py:353-378`), not a post-create
   error with that same stale flag. The wrong wording was thus tested in its
   valid case but never tested against contradictory facts.
4. **Offline transport evidence was narrower than launch readiness.** An actual
   binary issuing CONNECT to a local rejecting sink says nothing about TLS/WSS
   success. CI builds the MCP service container, not the Codex/R benchmark images
   or a real production-method lifecycle. Optional marked tests can be skipped.
5. **Failure handling removed the differentiating data.** The first generic
   ManagedAgentsError and fourth DockerRuntimeError share a pattern: output was
   made safe by dropping diagnostics rather than projecting safe fields. Every
   deeper failure required a new operator observation instead of a discriminating
   offline matrix and preserved causal evidence.

This is a component-contract/testing failure, not evidence that four paid
attempts were intrinsically necessary. The exact fourth runtime cause remains
unknown even after this explanation.

Minimum offline integration architecture: use the real lifecycle, HTTPX client,
runtime startup method, authorization parser, lease/markers, serializer and
ledger with synthetic keys and private temporary state. Mock only the remote
API transport and (in fast tests) the Docker subprocess boundary. Inject complete
schema-faithful HTTP/SSE responses and real Docker inspect projections. Exercise
URL variants through all components. Use a separate opt-in Docker job with the
pinned binary, production policy and local synthetic registration/TLS/WSS service;
an explicitly injected offline transport seam must have no insecure live switch,
no TLS bypass, no route to OpenAI and no change to live allowlists. It must call
the actual start method rather than substitute another probe. If such a seam
is not yet available, state that gap rather than claim the rejecting sink covers it.
All resulting records must be synthetic and rejected by real-result import.

## 9. Observability and forensic model

Proposed safe error projection (future implementation, not added here):

```json
{
  "operation": "start_executor",
  "sub_operation": "validate_remote_endpoint",
  "exception_type": "DockerRuntimeError",
  "safe_error_code": "executor_endpoint_policy_mismatch",
  "docker_http_status": null,
  "docker_cli_exit_code": null,
  "container_short_id": null,
  "container_exit_code": null,
  "stderr_summary_code": null,
  "stderr_redacted_excerpt": null,
  "lifecycle_state": "start_executor",
  "session_creation_attempted": true,
  "session_creation_http_status": 201,
  "remote_session_state": "created",
  "task_submission_state": "not_attempted",
  "cleanup_attempted": true,
  "local_cleanup_verified": true,
  "remote_deletion_verified": true
}
```

These values illustrate field semantics only, not the fourth attempt's missing
root cause. Record operation start/end timestamps and primary versus secondary
errors separately. CLI-only Docker failures cannot honestly supply an HTTP
status. A bounded stderr excerpt should default to null: expose only a reviewed
allowlist of diagnostic text after exact key and URL removal. Never persist raw
argv, Config.Env, response bodies, signed URLs, headers or exception repr/chains.
Hashes of historical files are suitable provenance; a redacted ID is not evidence
of identity until tied to its original authorization and consumed markers.

## 10. Authorization, billing, cleanup and evidence risk

- Exclusive lock ownership, private scoped authorization, immutable file hashes,
  exclusive consumed markers and one-create/one-submit guards provide valuable
  at-most-once protections. Exactly-once remote execution across process crash
  cannot be proven by local markers alone. Partial state must remain blocked.
- HTTP 201 followed by local failure is a created-session failure, not successful
  inference and not a zero-billing certificate. Current code attempts validated
  deletion. With a usable ID, schema failure is deleted inside the client;
  without one, uncertainty remains and blocks aggregate cleanup.
- Fourth-attempt deletion/local cleanup are operator-reported facts here. The
  later local verify-cleanup command checks Docker names/networks/lock and saved
  audit booleans; it does not query remote session inventory. Empty Agents Logs
  is not deletion evidence. Independent complete inventory has its own source,
  check time, pagination and freshness gate; absence establishes no listed
  sessions at that time, not proof of historical noncreation.
- The ledger is client-side best effort, not a hard spending limit. Unknown
  usage/spending is stored as null and stops progress. Preserve the unreconciled
  historical checkpoint exactly; request provider evidence separately.
- Teardown removes executor/proxy logs; final JSON is written after prompts.
  Preserve safe failure evidence before teardown and side-effect intent before
  calls, while terminating dangerous processes promptly. Do not retain running
  candidates merely to obtain logs. Do not reset any closed attempt marker.

## 11. Prioritized remediation roadmap

1. **P0: preserve and classify.** Freeze the four historical records and marker
   history, obtain safe missing evidence, label billing unknown and keep NO-GO.
2. **P0: repair the demonstrated contract defect.** In a separately authorized
   coding task, share reviewed URL policy and test parser-to-runtime composition.
3. **P0: repair forensic truthfulness.** Correct state flag timing, preserve safe
   Docker sub-operation errors, distinguish primary/cleanup errors, persist a
   private append-only journal before external side effects.
4. **P1: exercise the production runtime offline.** Introduce narrowly scoped
   transport/subprocess injection and CI requirements described in section 8;
   include golden serialized historical schemas and complete failure matrix.
5. **P1: prove termination and uncertain-side-effect handling.** Global deadline
   accounting, startup/stream/task/cleanup crash tests; enforce conservative lease
   retention and no automatic retries.
6. **P1: clarify evidence semantics.** Separate provider versus operator money
   fields, observed versus attested gates, local absence versus remote deletion,
   and improve the existing result inspector/docs.

None of these steps authorizes another attempt or modifying the strict benchmark.

## 12. Safe offline verification performed and proposed

Performed in this audit:

```text
.venv/Scripts/python.exe -m pytest tests/test_codex_managed_agents.py
  tests/test_codex_managed_agents_lifecycle.py tests/test_codex_docker_runtime.py
  tests/test_codex_egress_proxy.py -m "not docker" -q --basetemp <system-temp>/rkmcp-audit-offline-tests
67 passed, 1 skipped, 7 deselected in 1.43s
```

The non-Docker skip is the Windows symlink-creation privilege test; seven marked
Docker tests were explicitly deselected to respect the resource-creation ban.
Synthetic test methods are not live CLI invocations. No live authorizations,
sessions, inference or Docker resources were created. The container-free URL
probe described in section 5 also ran. Read-only WSL/Docker attempts failed as
described in section 2. Full pytest, real Docker tests, scorer execution and
remote CI were not run for this documentation-only audit.

Required later offline cases: failure at every startup sub-operation; successful
HTTP 201 then runtime URL rejection; daemon unavailable after topology startup;
mount/UID mismatch; child exit/nonzero/OOM; create timeout with partial resources;
missing/stale/malformed inventory; altered history bytes; both consumed-marker
failures; SSE replay/duplicate connected, silent stream, task POST uncertainty;
deadline races; failed cancel/delete/close/teardown; disk write/checkpoint failure;
crash before and after every external side effect. Assert no automatic retry,
no scoring before verified candidate termination, accurate unknown remote state,
no artifact export on cleanup failure and no synthetic record imported as real.

## 13. Evidence still required: safe operator read-only commands

These commands are **not an execution/recovery procedure**. Run in the actual
WSL distribution against existing files; do not run authorize-one, run-one,
Docker probes/build/run/create/start, or any cleanup deletion. Do not publish
raw audits/authorizations, `docker inspect` output, environment dumps or logs.

```bash
state="$HOME/.local/state/r-knowledge-mcp/r01a"
stat --format='%n %s %y' "$state"/r01a-result*.json
sha256sum "$state"/r01a-result*.json "$state"/authorization*.json
find "$state/consumed-trials" "$state/consumed-authorizations" \
  -maxdepth 1 -type f -name '*.json' -exec sha256sum {} \;
test ! -e "$state/active-trial.lock" && printf 'No active lock\n'
docker version --format '{{.Client.Version}} {{.Server.Version}}'
docker ps -a --filter name=rkmcp --format '{{.ID}} {{.Names}} {{.Status}}'
docker network ls --format '{{.Name}}' | sed -n '/^rkmcp-/p'
```

Project only fixed scalar fields from the saved final result (no arbitrary
failure reason, URL, key, environment, event content or authorization ID):

```bash
python - "$state/r01a-result-final-continuation.json" <<'PY'
import json, sys
from pathlib import Path
r = json.loads(Path(sys.argv[1]).read_bytes())
keys = ('session_created', 'session_creation_attempted', 'sessions_created_count',
        'session_creation_http_status', 'inference_submitted',
        'task_submissions_attempted_count', 'cleanup_verified',
        'session_deleted_verified', 'container_termination_verified',
        'topology_cleanup_verified')
print(json.dumps({k:r.get(k) for k in keys}, indent=2))
print('state_count:', len(r.get('states', [])))
print('event_count:', len(r.get('events', [])))
PY
```

If any candidate container still exists, a narrowly filtered read-only inspect
is safe after selecting its ID from the previous listing:

```bash
# Substitute an existing container ID; do not create a replacement.
docker inspect --format '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}} {{.State.StartedAt}} {{.State.FinishedAt}}' CONTAINER_ID
```

Missing discriminator evidence: a pre-existing safe startup error code, Docker
CLI return code/sub-operation, before-removal container state, and a locally
reviewed URL-policy classification (exact path versus trailing slash/subpath,
trusted origin/port booleans only). If raw daemon/executor logs still exist,
review them locally using a separately reviewed sanitizer; do not paste
`docker logs`, complete daemon events, journal output or process arguments.
If cleanup already deleted the container, say those observations are unavailable;
do not recreate it or infer its exit code. Obtain the original launch commit,
image IDs, WSL/Docker versions and workspace mode/UID mapping without key values.

Request preserved independent session inventory evidence/source/check time,
pagination completeness and provider deletion confirmation separately. Existing
inventory may establish the current remote absence only for its check time.
No new authenticated API request was made or is scripted here. Billing needs
provider usage/cost evidence or a dated operator dashboard review; opening
balance is not a session charge. Original history and checkpoint stay unchanged.

## 14. Go/no-go criteria

Current status: **NO-GO**. All four identities remain closed; consumed
authorizations cannot be replayed, and historical files must not be edited.

Before any future experimental proposal can be reviewed: F01/F02/F03/F04/F05/F08
must have concrete fixes and passing offline acceptance evidence, no secret
leakage in persisted synthetic failure tests, verified artifact/scorer separation,
correct unknown-spend handling and complete cleanup evidence. Remaining live
TLS/WSS/account limitations must be explicitly listed rather than marked passed
from mocks. Any later real verification that could create a billable side effect
requires a separate operator decision and protocol review. This report provides
neither an additional attempt identity nor authorization to use one.
