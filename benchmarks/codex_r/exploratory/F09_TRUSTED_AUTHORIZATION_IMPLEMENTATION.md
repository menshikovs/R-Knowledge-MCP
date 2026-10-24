# F09 authorization implementation and operator prerequisites

**Superseded architecture notice (2026-10-24):** the separate issuer/runtime
and protected-helper proposal below is historical. The accepted current threat
model trusts one local operator account; see
[F09_SOLO_OPERATOR_GUIDE.md](F09_SOLO_OPERATOR_GUIDE.md). Separate users or a
broker are not current prerequisites. The 143-test evidence below predates the
solo workflow. Live execution remains disabled and R01-A remains **NO-GO**.

Date: 2026-10-24. Starting source: `de4727bf9691436fc7f1d08d5f21ee2903b01d40`.

Verified implementation/test commit:
`c316b486b432cf58d4ccdd1787fa8298c6593113`.
Only the harness and test module were committed. This guide and pre-existing
checklist/report material remain uncommitted. Both committed Python files were
checked against their verified pre-commit SHA-256 hashes; their contents match.

**Decision: NOT READY - trusted boundary incomplete.** This change implements
the permitted offline fallback. It does not implement production issuance or a
privileged consumption helper. All live gates remain closed. R01-A is **NO-GO**.
No real approval, credential, session, Docker resource or provider request was
used. Existing staging project and keys do not need to be recreated.

## What the code implements

The existing `OfflineStagingAuthorizationStore` remains synthetic-only. The
shared claims validator now requires schema version 2 and an exact expected
binding: F09 attempt ID, full source commit, staging project ID, harness
configuration digest, non-secret credential-attestation digest and approved
integer USD-cent limit. One session, zero tasks and no Responses calls remain
mandatory. Expiration is explicit and at most 15 minutes after issuance.
Billing-owner approval and acknowledgment of financial risk are separate fields.
Legacy unbound claims are rejected; no historical records are migrated.

`200` cents is a policy ceiling, not a default or an approved amount. A smaller
positive exact integer is accepted only when the claims, expected binding and
session request agree. The checklist's proposed 200-cent budget remains pending.
Neither this limit nor a session without input proves a hard maximum bill or
zero cost.

`connectivity_configuration_sha256` covers the agent configuration, fixed
workspace, create/connect/cleanup budgets and zero-task scope. It does not
establish that the executing files match the supplied commit, or verify an
installed executable, Docker image or egress-policy digest. Those remain future
trusted-launcher responsibilities. No credential value is hashed.

`unverified_credential_scope_sha256` accepts bounded non-secret resource IDs or
labels, organization/project/owner metadata, review metadata and exact permission
lists. It accepts only dashboard attestation as its evidence category. It cannot
authenticate those declarations or bind runtime-loaded keys to those resources.
It rejects secret-shaped values, URLs, extra permissions and malformed metadata.

An optional `SyntheticStagingAuthorization` rehearses this order against fake
HTTP/executor boundaries:

1. Validate exact request bindings and explicit spend approval before the lease.
2. Acquire the existing staging lease.
3. Create and fsync an exclusive retained attempt claim, then sync its directory.
4. Fsync the consumption journal intent, write/fsync the final consumed marker,
   sync its directory and fsync the matching outcome.
5. Revalidate the binding/expiration before the sole session-create operation,
   including inside its bounded worker.
6. Execute the existing zero-task lifecycle and existing cleanup protocol.

The attempt claim prevents consumption of another approval for the same attempt.
It also survives an incomplete intent or final-marker write. Partial files are
retained. Replay is rejected before a new journal intent. No error removes a
claim or restores an approval. Failure after lease acquisition keeps the lease;
best-effort audit persistence cannot certify cleanup. Audit schema 2 uses the
boolean `approval_consumption_durable`, whose name preserves its type through
the existing confidentiality sanitizer. No sanitizer policy was weakened.

Synthetic issuer/runtime callbacks are test fixtures only. A process with the
same OS identity can alter their role callbacks or rewrite their files. Path,
mode, inode, hard-link and replacement checks add rejection coverage but do not
turn this store into a production security boundary. Synthetic lifecycle tests
without an approval rehearsal remain supported; none can enter live mode.

Both `StagingAgentsClient` and `ConnectivityHarness` independently reject live
use. A forged concrete client or module capability cannot bypass the new
unconditional harness rejection. `require_trusted_staging_authorization` still
rejects even structurally valid claims. There is no live authorization CLI.

## Observed OS prerequisites

WSL enumeration inside the Windows sandbox returned
`Wsl/EnumerateDistros/Service/E_ACCESSDENIED`. Running WSL outside that sandbox
under the same Windows user succeeded; no sudo or configuration change was used.
Read-only Ubuntu checks observed:

- Python 3.14.4; current UID 1000, including `sudo` and `docker` group membership.
- Repository filesystem: `9p`/DrvFS. Linux `/tmp`: `tmpfs`.
- No `f09`/`rkmcp`-named accounts were found, and no protected policy existed at
  the proposed `/etc/rkmcp/f09/trust.json` path. This is not proof that arbitrary
  other accounts cannot exist; no intended issuer/runtime mapping was verified.

The current operator may administer the installation, but that privileged
account must not serve as an allegedly isolated runtime. Test data on `/tmp`
is disposable synthetic state; its volatility makes it unsuitable for persistent
real approval/replay evidence.

## Minimum missing production boundary

Before any live implementation can be reviewed, establish a native Linux,
persistent installation with distinct unprivileged issuer and runtime UIDs.
The runtime must lack sudo, Docker-group and equivalent escalation rights.
Protect the installed source and trust policy from runtime modification;
executing a runtime-writable checkout on `/mnt/c` does not meet that condition.

Use an issuer-owned 0700 authorization directory with 0600 records, consumption
claims and journals. Use a separate runtime-owned 0700 lifecycle directory with
0600 journal/lease/audit files. The runtime must have no ability to modify or
remove issuer records or consumed evidence. All parent ownership and ACLs matter;
mode bits on DrvFS or two role names under one UID are insufficient.

Read-only checks for a future administrator, with approved placeholders:

```sh
id -u
id -nG
getent passwd <issuer_account> <runtime_account>
id <issuer_account>
id <runtime_account>
findmnt -T <persistent_authorization_root> -o TARGET,FSTYPE,OPTIONS
namei -l <persistent_authorization_root>
stat -c '%a %u %g %F' <persistent_authorization_root> <protected_policy_file>
```

These commands do not create the installation, change permissions or prove
sudo/ACL policy completeness. An administrator must separately verify that the
runtime cannot write the issuer store, policy, installed code or trusted helper.
Real cross-UID denial tests are still required; same-UID subprocess tests do not
prove that boundary. No such setup or real cross-UID test was performed here.

The smallest remaining software addition is a short-lived, OS-authenticated,
issuer-owned consumption helper with a fixed protected entry point. It must
expose consumption only to the runtime, with no runtime issuance operation or
caller-selectable program/configuration. Manual issuance runs separately under
the authenticated issuer after review of the exact source/configuration,
non-secret attestation and billing approval. A capability travels only through
an inherited descriptor or stdin; only its digest is persisted. Consumption and
all replay evidence stay under the issuer UID and must be durable before the
helper returns a result to the reviewed launcher. This helper is not implemented
or installed by this fallback. A runtime-writable consumed-marker directory
cannot substitute for it; no permanent broker or daemon is necessary.

Credential/project evidence is still only attested, not provider-authenticated
runtime verification. No undocumented introspection endpoint is assumed. A
separate review must resolve that binding policy, trusted launch/receipt handling
and image/egress provenance before removing any live rejection. Keep the
application key outside the executor and the environment key restricted to its
existing reviewed startup boundary. Do not include either in an approval,
configuration digest, command argument, report or log.

No issuance/consumption command for real approval is supplied or authorized.
Reviewing this guide or completing dashboard attestation does not unlock a gate.

## Verification on the modified source

These are observed results from this task, distinct from the operator's earlier
102-test baseline result:

- Windows filesystem-independent selection: 46 passed, 94 deselected, one
  configuration warning, before the final three metadata-type cases were added.
- Final Ubuntu focused authorization selection: **41 passed, 102 deselected,
  0 failed, 0 skipped, 1 warning**, 1.82 seconds.
- Final Ubuntu complete F09 module: **143 passed, 0 failed, 0 skipped,
  0 deselected, 1 warning**, 4.37 seconds.
- Ruff check and Ruff format check on the harness and test module: PASS.
- `git diff --check`: PASS; Git reports existing CRLF normalization notices.

The warning is the existing unknown `cache_dir` configuration option when
`cacheprovider` is disabled. An initial bash invocation was rejected before test
execution because Windows CRLF contaminated its selection argument; a Linux
Python launcher then ran the commands successfully. One initial regression
assertion incorrectly expected no final marker after a write failure. Since
`O_EXCL` creates that file before writing, the corrected assertion verifies its
retained zero-byte state, pending journal intent and rejection of a second grant
for the same attempt. No security exception was suppressed.

The actual WSL launcher used `.venv-wsl/bin/python -B`, `tempfile.mkdtemp` under
`/tmp`, mode 0700, and these pytest arguments. Equivalent operator commands:

```sh
cd /mnt/c/programming_pj/cran-mcp
test_root=$(mktemp -d /tmp/f09-auth-focused-XXXXXX)
chmod 700 "$test_root"
PYTHONDONTWRITEBYTECODE=1 .venv-wsl/bin/python -m pytest \
  tests/test_codex_connectivity_harness.py -q -p no:cacheprovider -m "not docker" \
  --basetemp="$test_root/pytest-tmp" \
  -k "authorization_rehearsal or failed_second_consumption or approval_record_replacement or approval_symlink or offline_capability_store or bound_authorization or scope_attestation or scope_and_configuration or no_production_store"

test_root=$(mktemp -d /tmp/f09-auth-full-XXXXXX)
chmod 700 "$test_root"
PYTHONDONTWRITEBYTECODE=1 .venv-wsl/bin/python -m pytest \
  tests/test_codex_connectivity_harness.py -q -p no:cacheprovider -m "not docker" \
  --basetemp="$test_root/pytest-tmp"

ruff check benchmarks/codex_r/exploratory/connectivity_harness.py tests/test_codex_connectivity_harness.py
ruff format --check benchmarks/codex_r/exploratory/connectivity_harness.py tests/test_codex_connectivity_harness.py
git diff --check
```

All regression credentials, approvals, clocks, HTTP responses and executor
effects are synthetic. Tests cover replay/restart/concurrency, mismatched scope,
expiry, invalid spending types, retained partial consumption, journal and
permission failures, symlink/replacement rejection, cleanup uncertainty, audit
confidentiality and absent task/Responses routes.

These passes do not establish live TLS/WSS compatibility, provider permissions,
trusted cross-UID issuance or power-loss durability. Fsync ordering and retained
markers provide process-crash evidence when the filesystem honors syncs; a valid
hash chain cannot detect complete-record truncation without a trusted anchor.
Any unresolved approval, lease, worker, session or cleanup requires operator
reconciliation. Never remove a marker or reset R01-A history as recovery.

**Next operator action:** review and approve the native-Linux issuer/runtime and
protected consumption-helper setup. This is a preparation decision only; a real
zero-task check would still require separate identity/scope review, exact short
approval, billing acknowledgment and explicit live authorization. R01-A remains
**NO-GO**.
