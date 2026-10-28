# Security audit

Commit `4d2266c`. IDs refer to [`FINDINGS.md`](FINDINGS.md). Defensive review with bounded, non-destructive tests. No exploit was run against any third-party service;
every hostile input below was generated locally and parsed in memory. Public upstreams were only *read* (see `KNOWLEDGE_CORRECTNESS_AUDIT.md` §0).

## 1. Threat model

| Actor | Capability | What they can influence | Boundary |
|---|---|---|---|
| **Agent / prompt injector** | Supplies tool arguments (possibly steered by injected text) | package names, queries, free-form `question`, supplied R/Quarto source, prompt text, `revision` | MCP client → server |
| **Package author** (CRAN, Bioconductor, GitHub) | Publishes DESCRIPTION, NAMESPACE, Rd, archive layout, `URL:` fields, `AGENTS.md` | everything the server parses and returns | upstream → server → agent context |
| **Network attacker** | On-path or DNS | fetched bytes (TLS expected) | server → upstream |
| **Remote HTTP caller** | Reaches the streamable-HTTP listener | all tools, connection resources | internet → server (only when deployed) |
| **Compromised upstream** | Controls a mirror/Context7/GitHub response | any bytes within the size limits | upstream → server |
| **Operator** | Sets env vars, runs container | secrets (`GITHUB_TOKEN`, `CONTEXT7_API_KEY`), logs | host |

Assets: process availability, operator secrets, user prompt/question text, host filesystem and network position, integrity of what the agent is told.

## 2. `docs/security.md` — claim vs enforcement

| Claim in the document | Enforced? | How verified |
|---|---|---|
| Fixed HTTPS hosts and route allow-lists for CRAN/Bioconductor; redirects and env proxies disabled; user input cannot supply a URL | **Yes.** `RepositoryHTTP.fetch` checks `allowed_path()` (regexes) before building the URL, `follow_redirects=False` on every request, `trust_env=False` in `make_client`. Redirect handling has its own regression tests (301/302 → error, not followed; they pass) | `http.py:139-143,304-327,330-340`; `tests/test_http.py`; run suite |
| GitHub repository from verified metadata, single unambiguous repo, ref → commit SHA, fixed API routes | **Yes**, with a naming caveat (SEC-005) | `providers/github_agents.py:30-47,60-81,145-319` |
| Context7 key only in an `Authorization` header to the fixed host; exact library match; redacted questions | **Mostly.** Key never in URL or log (verified); library match is exact; redaction is inconsistent (SEC-004) and the question is logged by `httpx` at INFO (SEC-003) | `probe_logs`, `probe_secrets` |
| Shiny/Positron/Quarto from a fixed catalogue; caller never forms a URL | **Yes** | `providers/framework_docs.py:16-38,68-80` |
| External text labelled untrusted | **Partly.** AGENTS.md, Context7 and framework pages carry a `trust` field; CRAN DESCRIPTION and Rd text do not (SEC-006) | `probe_inject` |
| Prompt Intelligence never executes text and rejects credential-like input before copying it | **Yes** for the tested set (8/9 detected, 0/5 benign false positives); obvious evasions pass (documented as heuristic); package text is not copied into generated prompts | `probe_secrets`, `probe_inject` |
| HTTP timeouts, overall deadline, bounded retry, byte limits; 64 MiB / 32-artifact cache; GitHub/Context7/AGENTS limits; 60 000-byte tool results; errors not cached | **Yes** (read in code; singleflight and cancellation safety verified) | `http.py`, `service.py:2222-2283`, `probe_conc` |
| Archives never extracted to disk | **Yes**: `source_files` reads three name patterns into memory | §3.3 |
| Sanitised logs: operation id and exception type only | **Partly**: the application logger is sanitised; `httpx`'s INFO logger prints upstream URLs (SEC-003) | `probe_logs` |
| "The optional GitHub API does not use a personal access token" (`docs/security.md:85`) | **No — stale.** `GITHUB_TOKEN` is read (`config.py:47-52`) and sent as a Bearer header (`github_agents.py:83-90`) | DOC-001 |
| HTTP listener defaults to loopback with DNS-rebinding protection; development server has no auth or rate limit | **Yes** for the CLI default and the Host/Origin checks; the container image binds `0.0.0.0` | §3.1, SEC-002 |

## 3. Results by topic

### 3.1 HTTP exposure, Host/Origin, DNS rebinding, authentication, rate limiting
`evidence/probes/probe_http_transport.txt` (uvicorn on loopback, real HTTP):

| Request | Result |
|---|---|
| Default `Host` | 200 |
| `Host: evil.example`, `127.0.0.1.evil.example` | 421 |
| `Origin: http://evil.example`, `http://localhost.evil.example`, `null` | 403 |
| `Origin: http://localhost:1234` | 200 |
| No `Authorization` header | 200 (no authentication layer exists) |
| `GET /mcp` | `200 text/event-stream`, still open after 3 s, no events, no idle timeout (**SEC-002**) |
| `OPTIONS` pre-flight | 405 (no CORS) |
| 20 MiB POST body | 413 |
| 100 000-level nested JSON | 500, `RecursionError` in server log (no crash) |
| `MCP-Protocol-Version: 1900-01-01` | 400 |
| Custom `--allowed-host example.test` | localhost is **replaced**, not extended; custom-host Origin allow-list entries are `http://` only (an HTTPS front end with browser clients would be rejected — not tested) |

Container: `docker build` succeeds (13 s), runs as uid 10001, works with `--read-only --cap-drop=ALL --security-opt=no-new-privileges`, answers `initialize` on a published loopback port; a request carrying the docker-network Host name gets 421 until `--allowed-host` is given. No HEALTHCHECK. The server has no authentication and no per-client limits, which the document states; it is nevertheless a **blocker for remote hosting** and the SDK-level spec text ("Servers MUST rate limit tool invocations", "SHOULD implement proper authentication") is not met.

### 3.2 SSRF, redirects, URL validation
No caller-supplied value reaches a URL host. Package names (`[A-Za-z][A-Za-z0-9.]{0,99}`), versions (from index records after `version_parts` validation), Bioconductor releases (`[0-9]+\.[0-9]+`) and GitHub identifiers (`[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}`, SHA-only tree/blob paths) are regex-constrained before substitution; `revision` allows `/` and `.` but rejects `..` segments and is URL-quoted into a *fixed API path on a fixed host*. Redirects are never followed. DNS-rebinding **toward** upstream is not applicable to fixed public hosts, but there is no egress allow-list at the network layer (`docs/security.md` leaves this to the deployer). I found no SSRF.

### 3.3 Malicious archives, decompression, memory
`probe_archive_hostile.txt`, `probe_rss_hostile_archive.txt` (hostile archives built locally, parsed in memory):

| Case | Result |
|---|---|
| `../x/man/x.Rd`, absolute names, backslash names, deep paths | ignored (only `<pkg>/DESCRIPTION`, `<pkg>/NAMESPACE`, `<pkg>/man/<name>.Rd` accepted) |
| Symlink / hardlink / FIFO / device members named like Rd files | skipped (`isfile()` false) |
| Duplicate `DESCRIPTION` | `invalid_source` |
| Rd of 2 MiB + 1 byte; 17 × 1.5 MiB Rd; 20 001 members | `source_too_large` (the 20 001-member case costs 0.9 s) |
| Gzip bomb, 100 MiB / 133 MiB expanded from ≈ 1 MB compressed | `source_too_large`; peak working set rises from 19 MB to **134 MB / 164 MB** (bounded by the 128 MiB read) |
| Concurrency | `SourceRepository._parse_lock` serialises archive expansion per provider (one CRAN, up to eight Bioconductor providers), so the worst case is not multiplied by request count |

Nothing is written to disk, so path traversal and link-following cannot occur. `tarfile` extraction filters are irrelevant because `extractfile().read()` is used.

### 3.4 Regular-expression and algorithmic complexity
`probe_redos.txt` (inputs at the documented caps):
- Prompt-side credential detector, intent classifier, `validate_prompt`, Context7 redaction, Rd `aliases()`/`rd_index_record()`/`_rd_complete()`, NAMESPACE tokenizer/parser: all ≤ 0.31 s for 8 000-character prompts, 500-character questions, 2 MiB Rd, 256 KiB NAMESPACE (including unclosed `\alias{`, 128-level brace nesting, 2 M backslashes, 20 000 nested parentheses). **No catastrophic backtracking found.**
- **`parsers.dcf()` is quadratic** (SEC-001): 80 000 continuation lines 0.12 s; 350 000 lines 2.4 s; 698 000 lines (just under the 2 MiB DESCRIPTION cap) ≈ 57 s on the event loop.
- Static analyzers at 256 KiB: ≤ 0.4 s per call and run in worker threads (`service.py:814`).

### 3.5 Secrets, redaction, logging, telemetry privacy
- API key and GitHub token are only ever placed in request headers; neither appeared in the INFO log, in URLs, or in any result (`probe_logs`). Token validation rejects control characters and > 255 characters (`config.py:47-52`).
- `RKMCP_BENCH_TELEMETRY` (one JSON line per call, always on, to stderr) contains tool name, byte counts, timings, a 12-hex-digit `argument_fingerprint`, package/repository, and optional run/trial ids — **no arguments or results**. The fingerprint is a truncated hash of normalised arguments; low-entropy arguments (package names) could be matched by a guess, so logs should still be treated as sensitive. `RKMCP_DIAGNOSTIC_FUNCTION_ALIASES=1` additionally logs a sanitised function alias; it is opt-in.
- SEC-003 and SEC-004 above are the exceptions: Context7 question text reaches stderr via `httpx`, and some credential shapes reach Context7.

### 3.6 Prompt injection and untrusted upstream content
- `get_package` returned a DESCRIPTION `Title` containing "IGNORE ALL PREVIOUS INSTRUCTIONS… curl … | sh" verbatim with no per-field marker; `get_function_docs` returned the same string inside Rd text (SEC-006). The server-level instructions and the README say package text is untrusted, and clients are responsible for the boundary.
- The same payload did **not** appear in `build_r_prompt` or `get_r_prompt_context` output: Prompt Intelligence propagates only validated identity/version/provenance fields, which is the correct design.
- `AGENTS.md` retrieval is the highest-risk content channel by nature; it is labelled `untrusted_reference_only` per file, pinned to a commit SHA, bounded to 96 KiB, and the repository comes from package metadata a package author controls (SEC-005).

### 3.7 Cache poisoning and key collisions
In-process caches only. HTTP cache keys are the validated route path (no query strings); a poisoned entry would require a malicious upstream response, and bodies are checksum-verified against the index before parsing (`checksum_mismatch`) for archives. GitHub cache key includes repository, version, owner/repo and *requested revision* (a moving branch name is cached for up to 1 h although resolved to a SHA — the SHA and times are returned, so staleness is visible). Context7 key includes the redacted question. I found no collision. Cached dicts are returned by reference (`github_agents.py:166-167`, `context7.py:135-136`); I found no caller that mutates them, but a future one could corrupt the cache silently.

### 3.8 Dependency and supply chain
- `pip-audit 2.10.1` against the resolved runtime closure (`mcp 1.30.0`, `httpx 0.28.1`, `starlette 1.10.0`, `uvicorn 0.54.0`, `PyYAML 6.0.3`, `pydantic 2.14.1`, …): **no known vulnerabilities** on 2026-10-27 (`evidence/probes/pip_audit.txt`). This is a point-in-time result for versions chosen by the resolver, not for pinned versions.
- No lock file or hashes for Python dependencies; unpinned `python:3.11-slim`; GitHub Actions pinned by tag (`checkout@v4`, `setup-python@v5`), workflows run with `contents: read`; no SBOM/provenance attestation; the `native/Cargo.lock` is committed (good) and the Rust crate has no `unsafe`. (SEC-007)
- `mcp>=1.30,<2` pins the 1.x line while 2.x is current; the project acknowledges the migration.

## 4. Classification

**Confirmed weaknesses (no active exploit shown):**
- SEC-001 quadratic parser (availability; exploitability depends on upstream acceptance of a hostile DESCRIPTION — unverified)
- SEC-002 unauthenticated, unlimited HTTP listener (documented; deployment risk)

**Defense-in-depth (confirmed):** SEC-003, SEC-004, SEC-005, SEC-006, SEC-007.
**Possible, not reproduced:** SEC-008 (LRU touched from a worker thread), SEC-009 (YAML on the event loop).
**Not found:** SSRF, open redirects, DNS-rebinding bypass of the Host/Origin checks, path traversal, archive extraction to disk, regex denial of service, credential leakage in URLs/results, command execution.

## 5. Recommended minimum before any remote deployment
1. Put the listener behind TLS and an authenticating reverse proxy with per-client rate and concurrency limits and an idle/total connection timeout for `GET /mcp` (SEC-002).
2. Fix SEC-001 and run DESCRIPTION parsing off the event loop.
3. Silence the `httpx` logger below WARNING (SEC-003) and unify/strengthen redaction (SEC-004).
4. Add the per-field untrusted marker to package-author text (SEC-006).
5. Pin dependencies with hashes, pin the base image by digest, add a HEALTHCHECK (SEC-007).
