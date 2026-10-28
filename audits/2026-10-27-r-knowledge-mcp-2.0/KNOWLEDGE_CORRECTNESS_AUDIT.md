# Knowledge and R-ecosystem correctness audit

Commit `4d2266c`. IDs refer to [`FINDINGS.md`](FINDINGS.md).

## 0. Method and its limits

Mocked-transport tests prove internal consistency, not correctness against reality, so I compared the server with **real upstream data and with R itself**:

- **Real CRAN/Bioconductor reads**, sequential, no concurrency, public mirrors only: the CRAN index and title catalogue, about 75 package source archives across probes (15 hand-picked, a seeded random sample of 30, 10 for the Python-vs-Rust parity run, a handful for diagnosis), Bioconductor `config.yaml`, three category indexes and three archives, and three fixed framework pages. No credentials, no paid service.
- **R 4.5.2 ground truth** (local install; my own 10-line script, no repository or package code executed): `getNamespaceExports()` and `tools::Rd_db()` aliases for 14 installed packages (`evidence/real_truth_*`).
- Caveat that limits every comparison: the installed R library is older than current CRAN (for example MASS 7.3.65 installed vs 7.3-66 current). Only **two** of the 14 packages (`boot`, `codetools`) have identical versions on both sides; differences for the other twelve mix parser behaviour with genuine version drift and are labelled accordingly.
- Historical benchmark reports were treated as claims, not test results.

## 1. CRAN provider

| Area | Verdict | Evidence / notes |
|---|---|---|
| Package discovery / search | **Correct, with a documented scope.** Name+title all-terms ranking over 25 529 index records and the HTML title catalogue; ranking is deterministic (score, shorter name, name). Python and Rust give identical rankings on 5 real queries | `probe_perf`, `probe_parity` |
| Current-version resolution | **Correct.** Root `PACKAGES` records only; `Path:` (R-version sub-index) duplicates are excluded deliberately (`providers/cran.py:17-30`) | code + real index parse (25 529 unique) |
| DESCRIPTION parsing | Correct for the ~75 real DESCRIPTION files and the full 25 529-record index parsed; **quadratic worst case** (SEC-001) | `probe_redos` |
| PACKAGES handling | `PACKAGES.gz` preferred, plain fallback; expansion bounded at 64 MiB (`http.py:25,48-57`); 7.4 MB expanded parses in ≈ 100 ms | `probe_perf` |
| Archive retrieval | Fixed route `/src/contrib/<pkg>_<ver>.tar.gz` only; **the CRAN `Archive/` tree is not reachable**, so only the current release exists (see §4). Download ≤ 25 MB, expansion ≤ 128 MiB, ≤ 20 000 members, only `DESCRIPTION`, `NAMESPACE`, `man/*.Rd` are read, never written to disk | `http.py:304-313`, `parsers.py:86-121` |
| Checksum | `MD5sum` from the index is compared with the archive body (`providers/base.py:213-222`, `_verified_cached_source`); mismatch → `checksum_mismatch`. MD5 gives integrity against corruption, not authenticity; both values come from the same TLS origin | code; `source_verification_level` field reports `archive_checksum_verified` vs `description_version_matched` |
| Package-name validation | `[A-Za-z][A-Za-z0-9.]{0,99}` before any URL is built; invalid names never reach a route | `http.py:27,67-70` |
| Dependency extraction | Verbatim DCF values for Depends/Imports/Suggests/LinkingTo/Enhances, explicitly "not transitive"; repository origin resolution against the index | `providers/base.py:383-394` |
| Source attribution | Every envelope carries `source_url`, `checked_at`, `verification_status`, `sources[]`; times are real fetch/revalidation times, including for cached artifacts (cache returns the original artifact, a 304 stamps a new time) | `http.py:139-279` |
| Version comparison | **Matches R.** `version_parts` treats `.` and `-` alike and drops trailing zeros: R 4.5.2 agrees (`1.0 == 1.0.0`, `2.10-1 == 2.10.1`, `2.10-01 == 2.10.1`: all TRUE, `evidence/real_truth_versions.txt`). The inconsistency is that one tool does not use it (KC-003) | `probes/vers.R` |
| Compatibility claims | Wording is conservative and accurate: "metadata_compatible", scope string "not a transitive solver or installation test", warns that only the *current* CRAN version is checked. Real checks: ggplot2 4.0.3 vs R 4.5.2 → `metadata_compatible`; vs R 3.6.0 → `incompatible` with four dependency `R (>= 4.x)` warnings | `probe_bioc.txt` |

## 2. Bioconductor provider

| Area | Verdict | Evidence |
|---|---|---|
| Release discovery | **Dynamic and correct.** `config.yaml` parsed with `yaml.safe_load`; `release`=3.23 (R 4.6), `devel`=3.24, historical `3.20` → R 4.4, unknown `9.99` → `release_not_found`. Nothing hard-coded | `probe_bioc.txt`, `releases.py:28-78` |
| Devel/stable/historical | Distinct `channel` per release; warnings attached to devel and historical results (`service.py:256-266`) | code; `DESeq2` at R 4.2.0 → release 3.16 with the historical warning |
| R-version mapping | R 4.5.2 → releases 3.21 and 3.22, recommended 3.22; R 3.0.0 → 2.13; unmapped R → empty list with a warning, never invented (`releases.py:80-107`) | `probe_bioc.txt` |
| Software/annotation/experiment repositories | One index per category (3 747 records for 3.23); duplicate names across categories fail the whole release rather than guessing (`providers/bioconductor.py:14-29`) — conservative; not observed on the real release | `probe_bioc_cost.txt` |
| Repository-specific identity | `search_packages(repository="all")` kept CRAN and Bioconductor results separate; `get_package("S4Vectors","all")` → verified with the CRAN not-found treated as expected (`service.aggregate`) | `probe_bioc.txt` |
| No silent fallback | **Verified.** `BiocGenerics` docs at release 3.23 → 0.58.1; at `bioc_version="3.20"` → 0.52.0 (the 3.20 archive, not the current one) | `probe_bioc.txt` |
| Compatibility | `check_package_compatibility` selects a release by R version and reports `compatibility_status: metadata_compatible`, `not_checked` for unsupplied R | code, `service.py:2063-2138` |
| Cost | `config.yaml` is re-parsed on every call and the provider is rebuilt after each cache refresh (PERF-001): 12 ms/call, 17 ms rebuild | `probe_bioc_cost.txt` |

## 3. Function Discovery (`list_package_functions`) and its relationship to `get_function_docs`

### 3.1 Design as implemented

One ordered stream of entities `export | alias | topic | method`, bounded at 10 000 entries and 16 KiB per page; exact → normalised → fuzzy ranking (`SequenceMatcher` ≥ 0.55 or substring) with an explicit `fuzzy_search_complete` flag when more than 1 000 candidates exist; `snapshot` = SHA-256 of (schema, identity, archive digest, query) so that continuation pages fail with `source_identity_drift` if the archive or query changes; `callability: not_checked` everywhere; `relationship_verified` only for exact/alias/topic matches.
`get_function_docs` requires a *literal Rd alias* and returns raw Rd (8 000 characters per page); on a miss it returns `docs_not_found` with `suggestions` drawn from the discovery index (top 3 aliases), `closest_aliases` (10) or the full alias list when the package has ≤ 30 aliases.

### 3.2 Ground truth against R (14 installed packages; CRAN current via the server)

| Package | R-installed → CRAN | same version | status | issues | exports R / server (missing, extra) | aliases R / server (missing, extra) |
|---|---|---|---|---|---|---|
| MASS | 7.3.65 → 7.3-66 | no | partial | namespace_nonliteral_arguments | 77 / 77 (0, 0) | 248 / 248 (0, 0) |
| lattice | 0.22.7 → 0.23-1 | no | partial | namespace_nonliteral_arguments | 148 / 147 (1, 0) | 247 / 248 (0, 1) |
| cluster | 2.1.8.1 → 2.1.8.3 | no | partial | namespace_nonliteral_arguments, rd_encoding_unavailable | 25 / 25 (0, 0) | 84 / 83 (1, 0) |
| rpart | 4.1.24 → 4.1.27 | no | partial | namespace_nonliteral_arguments | 14 / 14 (0, 0) | 37 / 37 (0, 0) |
| **boot** | 1.3.32 → 1.3-32 | **yes** | verified | — | 36 / 36 (0, 0) | 101 / 101 (0, 0) |
| nnet | 7.3.20 → 7.3-21 | no | partial | namespace_nonliteral_arguments | 7 / 7 (0, 0) | 27 / 27 (0, 0) |
| class | 7.3.23 → 7.3-24 | no | partial | namespace_nonliteral_arguments | 15 / 15 (0, 0) | 17 / 17 (0, 0) |
| **codetools** | 0.2.20 → 0.2-20 | **yes** | verified | — | 19 / 19 (0, 0) | 20 / 20 (0, 0) |
| foreign | 0.8.90 → 0.8-92 | no | partial | namespace_nonliteral_arguments | 17 / 17 (0, 0) | 17 / 17 (0, 0) |
| KernSmooth | 2.23.26 → 2.23-27 | no | partial | namespace_nonliteral_arguments | 7 / 7 (0, 0) | 7 / 7 (0, 0) |
| nlme | 3.1.168 → 3.1-171 | no | partial | namespace_nonliteral_arguments | 109 / 109 (0, 0) | 536 / 536 (0, 0) |
| Matrix | 1.7.4 → 1.7-6 | no | partial | namespace_nonliteral_arguments, rd_literal_coverage_partial | 417 / 321 (215, 119) | 2002 / 2002 (0, 0) |
| survival | 3.8.3 → 3.8-12 | no | partial | namespace_nonliteral_arguments, namespace_unsupported_expression | 79 / 80 (2, 3) | 263 / 258 (10, 5) |
| mgcv | 1.9.3 → 1.9-4 | no | partial | namespace_nonliteral_arguments | 191 / 195 (3, 7) | 261 / 266 (3, 8) |

Reading the table:
- Where versions match (`boot`, `codetools`) exports and aliases are **identical** to R's. Where versions differ and no parsing issue is flagged beyond `useDynLib` (MASS, rpart, nnet, class, foreign, KernSmooth, nlme) the sets are also identical — so the parser itself is accurate on those; most differences elsewhere (lattice, survival, mgcv) are plausibly version drift and I did not attribute them further.
- `cluster`: the one missing alias is `plantTraits`, the file that triggers KC-001.
- `Matrix`: the 215 "missing" are R's internal `.__C__*` class-metadata objects; the 119 "extra" include generics named in `exportMethods` (`!`, `%*%`, …). This is the documented static-declaration semantics (KC-005), not an error, but agents must not read the list as `getNamespaceExports()`.
- Status: 12 of 14 are `partial` although all but `Matrix`/`survival` (genuinely conditional or class-heavy NAMESPACEs) were enumerated completely — KC-002.

### 3.3 Prevalence on a seeded random sample of 30 current CRAN packages (seed 1729)

`verified` 16, `partial` 14 (47 %; Wilson 95 % CI 30–64 %). Causes (a package can have more than one): `rd_literal_coverage_partial` 6, `export_patterns_not_expanded` 5 (the only legitimate kind: `exportPattern()` cannot be expanded statically; 3 of the 30 packages therefore list **0 exports**), `namespace_nonliteral_arguments` 3. `get_function_docs` on the first listed alias succeeded for **30/30**. Median discovery latency 0.1 s (warm index), max 0.5 s (`evidence/real_cran_sample.json`). Encoding failure (KC-001) did not occur in this sample.

### 3.4 Relationship between the two tools

| Question | Finding |
|---|---|
| Does a name returned by discovery always work in docs? | **Not always.** Aliases are literal in both, so normally yes, but KC-001 breaks docs for the whole package while discovery lists the aliases; and exports that are not Rd aliases (e.g. S4 generics documented under `topic,class-method` aliases) are listed as `export` but have no literal alias — the entry's `documentation_topics` shows the link when it exists |
| Do both use the same version notion? | No — KC-003 |
| Is `docs_not_found` informative? | Yes. `validate::violations` (benchmark call) really does not exist in validate 1.1.7; docs returned `closest_aliases = [violating, voptions, …]` and discovery with `query="violations"` ranks `violating` first (`probe_validate.txt`). The 59 frozen `docs_not_found` events (all D01/D03) are guesses such as `new_app`, `select_input`, `check_box_group`, `choose_menu` for packages the agent did not know — the situation the discovery tool exists for |
| Ambiguous aliases | If two Rd files define the same alias the docs tool raises `ambiguous_docs` without listing the candidate files (`providers/base.py:437-440`): the agent cannot resolve it with the tool. Not observed on real data |
| Paging | Snapshot paging completed without a drift error for all 15 packages (Matrix: 89 pages of ≤ 50 entities, ≈ 36 per page because of the 16 KiB cap); documentation paging is by character offset |
| Requested version handling | Only the *current* repository version is available. Any other `package_version` is refused with `requested_version_unavailable` (explicit, no substitution — as `AGENTS.md` requires). Consequence: for a project that has an older version installed, version-specific docs are unavailable by design; Bioconductor history works through `bioc_version`, CRAN history does not (§4) |
| Coverage reporting | Honest and structured (`coverage.namespace/rd`, `issues`, counts `*_complete`, `export_patterns`), but see KC-002 for how often "partial" fires |
| Python/Rust parity | Identical on 10 real archives (SHA-256 of the full entry list, issues, patterns equal); 108 parity/discovery tests pass with the native module loaded |

### 3.5 Behaviour when documentation is absent, ambiguous, outdated or incompatible

| Situation | Behaviour | Verdict |
|---|---|---|
| Alias absent | `docs_not_found` + suggestions, `lookup_stage: literal_rd_alias`, resolved version and check time | good |
| Package absent | `package_not_found` with index URL | good |
| Requested version ≠ current | `requested_version_unavailable` with both versions; but spelled differently from R's `packageVersion()` it fails in discovery (KC-003) | defect |
| Rd with other encoding | whole-package `unsupported_encoding` in docs; partial in discovery | defect (KC-001) |
| No NAMESPACE / `exportPattern` | `namespace_missing` / `export_patterns_not_expanded`, `exports: []` | honest; "partial" |
| Package newer than the agent's R | docs are for the current version; no R-compatibility gating inside the docs tool (use `check_r_compatibility`) | by design; note for agents |
| Outdated docs | the tool is "current only"; `checked_at` and `version_scope: latest_cran` are returned | honest |

## 4. Value ceiling set by "current only"

Neither CRAN `Archive/` nor Bioconductor history beyond `bioc_version` is reachable for packages, so documentation for an **installed** older package version can never be returned; `docs/ROADMAP.md` lists "historical CRAN archives with exact-version provenance" as planned. Given that agent sandboxes usually have the installed package's own help available via R (`help()`/`?`), the capability the server uniquely offers — version-pinned docs for something *not* installed or *different* from latest — is the one it cannot yet provide. See `AGENT_USABILITY_AUDIT.md` §3.

## 5. Other providers

| Provider | Authority and trust | Findings |
|---|---|---|
| R manuals (`search_r_documentation`, `get_r_documentation_section`) | Official CRAN manuals, fixed six URLs, local SQLite-FTS5 index, never fetched at call time | Empty on a fresh install (AGT-002). Refresh path not exercised by me (it fetches six large manuals); index validation (`_safe_index`, size/signature checks) read, not stress-tested |
| Framework docs (Shiny/Positron/Quarto) | Fixed catalogue of 13 HTTPS URLs, topic selects the URL, redirects off, 2 MiB cap, `trust: untrusted_reference_material`, `version_scope: current_official_docs_not_version_pinned` | Live fetch of three pages: 78 %, 100 % and 92 % of the visible text is exposed (truncated at 8 192 characters, no paging); `version` is accepted but ignored (echoed as `requested_version`) — labelled honestly |
| GitHub `AGENTS.md` | Repository taken from the package's DESCRIPTION URL; ref resolved to a commit SHA; tree and blob SHAs checked; ≤ 24 files / 96 KiB; labelled `untrusted_reference_only`, `commands_executed: false` | Repository ownership is not verified though labelled "verified" (SEC-005). Not run live (needs a package with a GitHub URL and the 60/hour anonymous limit); logic read and covered by mocked tests |
| Context7 | Disabled without `CONTEXT7_API_KEY`; exact `/owner/repo` library-id match required; question redacted; secondary-source warning in every result | Over-redaction (SEC-004); question text in INFO logs (SEC-003). Not run live (no key, by instruction) |
| Positron | Documentation only; no GUI/session control is claimed (`server instructions`) | consistent with `AGENTS.md` |
| Quarto/Shiny/visualization analyzers | Bounded lexical analysis of supplied text, never executed; findings labelled with certainty; worst case at the 256 KiB cap ≈ 0.4 s | not validated against ground truth (no labelled corpus exists; see TST-001) |

Successful retrieval was never equated with semantic correctness in the code paths I read: `verification_status` values distinguish `verified`, `partial`, `retrieved_official_documentation`, `retrieved_from_context7`, `verified_at_pinned_commit`.

## 6. What I could not verify

Live GitHub and Context7 behaviour; the R-manual refresh; Windows-specific upstream behaviour; Bioconductor devel behaviour during a release transition; packages with > 4 000 NAMESPACE directives or > 10 000 entries (KC-004, only synthetic); CRAN packages with duplicate aliases across Rd files; any claim that depends on CRAN policy (for example whether a 2 MiB DESCRIPTION would be accepted).
