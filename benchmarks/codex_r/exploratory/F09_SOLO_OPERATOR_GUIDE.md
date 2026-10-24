# F09 solo-operator workflow

Date: 2026-10-24. Starting HEAD: `c316b486b432cf58d4ccdd1787fa8298c6593113`.
These changes are uncommitted. No real approval was issued or consumed.

**READY FOR SEPARATE LIVE AUTHORIZATION REVIEW.** This is offline workflow
readiness, not permission to connect. Both live gates remain unconditional
rejections. F09 live and R01-A remain **NO-GO**.

## Implementation and trust

`connectivity_harness.py` adds `SoloOperatorApprovalStore` and
`SoloOperatorAuthorization`, reusing the existing lease, journal, bounded
lifecycle, sanitizer and audit writer. `f09_solo_operator.py` exposes only
`approve` and read-only `inspect`; there is no execution command. Existing
synthetic capability fixtures remain separate and cannot become manual approval
records. The checklist and regression module cover the new workflow.

The trusted principal is the local operator account. There is no second Unix
identity, privileged helper, broker, daemon or signing infrastructure. A malicious
process under the same user can forge or alter local approvals and replay
evidence; permissions and hashes do not prevent that. An independent reviewer is
optional. Approval is not provider-authenticated credential verification.

The real store accepts an existing private directory outside the repository on
native Linux ext4/xfs/btrfs. It rejects Windows, DrvFS/9p, tmpfs, symlinks and
nonprivate directories. Directories are 0700 and records 0600. The repository
may remain on `/mnt/c`; its permissions are not a production trust guarantee.
Only explicitly synthetic tests use ephemeral Linux temporary state.

## Future operator procedure — do not execute as part of this task

1. Review and later commit the implementation after operator verification.
   Approval verifies the full HEAD SHA and the committed content of the harness,
   CLI, executor contract, Docker runtime and egress proxy. Modified executable
   files or an uncommitted CLI reject approval. These checks do not attest the
   installed Python dependencies or the running Docker image.
2. Verify the existing `rkmcp-staging` project and separately restricted keys in
   the dashboard: matching organization, project and intended owner; application
   Agents read/write only; environment connection only; no Responses permission.
   Record non-secret resource identifiers/labels, operator, reviewer (may be the
   operator) and actual UTC review time. Do not put keys in approval files,
   approval-command arguments/environment, logs or configuration hashes. Future
   credential loading needs its own reviewed boundary; application credentials
   must remain outside the executor. No introspection endpoint is assumed.
3. Select the amount explicitly with the billing owner. There is no default or
   fixed 200-cent approval. Review deadlines, immutable executor image ID and the
   restricted egress policy. Create a fresh persistent native Linux private state
   directory only after review, for example under the operator's Linux home.
   Do not reuse R01-A state or approvals.
4. Prepare a non-secret request JSON with exactly these fields:

   - `schema_version`: integer 1.
   - `source_commit`: the reviewed full 40-character HEAD SHA.
   - `project_id`: the exact approved staging project ID.
   - `agent`: reviewed model configuration with empty `tools`, no input/task.
   - `create_seconds`, `connect_seconds`, `cleanup_seconds`: explicit positive
     budgets within the existing 30/300/60-second caps.
   - `executor_image`: reviewed immutable `sha256:<64 hex characters>` image ID.
   - `spend_limit_cents`: the explicitly selected positive integer USD cents.
     Booleans, strings, fractions, missing and nonpositive limits reject.
   - `billing_owner_id`: the non-secret billing owner identity.
   - `credential_attestation`: `verification_method` equal to
     `operator_dashboard_attestation`; `organization_id`, `project_id`, `owner_id`,
     `application_key_resource_id`, `environment_key_label`, `operator_id`,
     `reviewer_id`; `application_permissions` equal to
     `["api.agents.read", "api.agents.write"]`; `environment_permissions` equal to
     `["api.agents.environments.connect"]`;
     `matching_organization_project_owner_confirmed` equal to true; `reviewed_at`
     equal to the actual canonical UTC timestamp. These are attestations, not
     proof that runtime credentials have those identities or permissions.
5. After separate live authorization review, the future local command is:

   ```sh
   .venv-wsl/bin/python -B benchmarks/codex_r/exploratory/f09_solo_operator.py \
     approve --request <non-secret-request.json> --state-dir <private-native-state> \
     --expires-in-seconds <explicit-seconds-from-1-through-900>
   ```

   Use an actual terminal, not piped confirmations. The command displays the
   fresh generated F09 attempt ID, exact commit/configuration hash, project,
   amount, one-session/zero-task scope and expiry. Type its exact displayed
   approval phrase, followed by
   `I ACCEPT BILLING RESPONSIBILITY AND BEST-EFFORT SPEND CONTROL`.
   EOF, cancellation, mismatch, expiry or uncertain persistence rejects approval.
   This records a local decision only; it cannot create a session.

## Single use, cleanup and uncertainty

There is one approval per store, no renewal/reset command and no automatic
retry. At the future execution boundary the concrete manual authorization must
match the actual project, configuration, source, spending approval, image and
lease. Consumption writes an exclusive `consumption.started` guard and syncs it,
then a durable journal intent, exclusive `consumed.json` and matching durable
outcome, before the sole session-create POST. Private files and parent directories
are fsynced. Concurrent claims, restart replay, partial writes, scope mismatch or
uncertain durability reject. Synthetic records cannot be promoted.

Ambiguous create is never retried. Existing bounded cleanup still requires
confirmed executor termination, topology cleanup and matching session deletion;
durable final audit precedes clean lease release. Failed authorization, uncertain
effects or incomplete cleanup retain evidence and the lease. Never remove markers
or switch directories to retry without first reconciling the prior attempt.

Read-only inspection cannot authorize recovery, certify cleanup or unlock live:

```sh
.venv-wsl/bin/python -B benchmarks/codex_r/exploratory/f09_solo_operator.py \
  inspect --state-dir <private-native-state>
```

Fsync ordering and subprocess tests are process-crash evidence, not a power-loss
guarantee. Complete-record journal truncation requires an external trusted anchor
to detect. Same-user tampering remains outside the threat model.

## Financial exposure and remaining live work

Provider spend control is best-effort, not a guaranteed billing ceiling. A
zero-task session is not proven free. The approximately $10 available balance
is operator-reported and unverified here; it is neither a budget nor authorization.
Keep the old 200-cent proposal pending unless explicitly selected and confirmed
again. Reconcile actual provider billing after any separately approved check.

Before execution, separately review the small live entry point and consumption
integration, actual immutable image/egress configuration, credential-loading
boundary and operator attestation policy. The current client and harness still
reject live construction. No live TLS/WSS compatibility has been demonstrated.
No approval issued now could authorize R01-A; that benchmark needs its own
separate decision, budget and authorization.

## Offline verification observed in Ubuntu WSL2

- Focused solo-operator tests: **38 passed, 143 deselected, 0 failed, 0 skipped**,
  one existing configuration warning, 3.46 seconds.
- Full F09 suite: **181 passed, 0 failed, 0 skipped, 0 deselected**, one existing
  configuration warning, 8.73 seconds. This includes the earlier 143 cases.
- All approvals, credentials, HTTP and executor effects were synthetic. The
  warning is the existing unknown `cache_dir` option with cacheprovider disabled.
- Ruff check and Ruff format check on all three changed Python files: PASS.
  `git diff --check`: PASS. New files also have no trailing whitespace or
  detected replacement/encoding markers. Earlier Windows sandbox failures and
  previous 143-test results do not substitute for the Ubuntu results above.

The final added regression also rejects a credential-shaped model identifier
before confirmation or storage. Its first run rejected the value correctly but
the test checked generic exception text instead of the diagnostic code. After
correcting that assertion, the focused and full results above completed.

Equivalent offline commands from the repository in Ubuntu:

```sh
test_root=$(mktemp -d /tmp/f09-solo-focused-XXXXXX)
chmod 700 "$test_root"
PYTHONDONTWRITEBYTECODE=1 .venv-wsl/bin/python -m pytest \
  tests/test_codex_connectivity_harness.py -q -p no:cacheprovider -m "not docker" \
  --basetemp="$test_root/pytest-tmp" -k solo_operator

test_root=$(mktemp -d /tmp/f09-solo-full-XXXXXX)
chmod 700 "$test_root"
PYTHONDONTWRITEBYTECODE=1 .venv-wsl/bin/python -m pytest \
  tests/test_codex_connectivity_harness.py -q -p no:cacheprovider -m "not docker" \
  --basetemp="$test_root/pytest-tmp"

ruff check benchmarks/codex_r/exploratory/connectivity_harness.py \
  benchmarks/codex_r/exploratory/f09_solo_operator.py tests/test_codex_connectivity_harness.py
ruff format --check benchmarks/codex_r/exploratory/connectivity_harness.py \
  benchmarks/codex_r/exploratory/f09_solo_operator.py tests/test_codex_connectivity_harness.py
git diff --check
```
