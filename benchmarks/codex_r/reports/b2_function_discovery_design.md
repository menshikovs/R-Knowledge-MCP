# B2 — proactive verified function discovery (design only)

Status: NOT RUN. No model, Agents API, benchmark or paid service call is authorized
or launched by this document.

## Question and hypothesis

Does proactive, version-scoped package API discovery reduce speculative docs
lookups while preserving final-answer correctness? The hypothesis is fewer
docs_not_found and unique failed names, more verified docs resolution and at
least equally correct answers. This is unmeasured.

B1 is descriptive context: 59 docs misses, 42 preserved request identities and
17 unknown. Its Control/Treatment differed in server description and had two
repetitions; it cannot establish a causal discovery-tool effect. Existing
available_aliases/closest_aliases hints must remain part of the baseline.

## One treatment variable

Run both arms from the same P1-B checkout, dependencies, backend configuration,
model/version/thinking effort, prompts, source fixtures, task contracts, scorer,
tool deadlines and reviewed B1 control server description.

- Control: consolidated MCP with FUNCTION_DISCOVERY_ENABLED=false.
- Treatment: consolidated MCP with FUNCTION_DISCOVERY_ENABLED=true.

Only list_package_functions availability differs. Existing tools and their
descriptions, enriched docs miss diagnostics, resources, prompts and server
instructions are identical. The registration regression test compares complete
existing tool schemas and server instructions between arms. Do not compare
legacy against consolidated; that changes many variables.

Set R_KNOWLEDGE_NATIVE identically in both arms and record extension ABI/version.
A missing/stale native extension in one arm is a preflight failure. There is no
Python-versus-Rust treatment in this experiment. A separate backend performance
experiment would be required to test acceleration.

## Evidence and task prerequisites

The local D01 contract is a package recommendation for terminal UI behavior,
feature/caveat IDs and official version/source URLs; it is not a function-name
oracle. D03 is a declarative-validation recommendation with similar constraints.
C01 is a pinned dplyr closest-join coding repair. Knowledge Pilot V2.1 abstains on
unfrozen claims; an abstention cannot be counted as a wrong answer or a runtime
failure.

Do not edit/reuse their historical files as new B2 tasks. Prepare separately
versioned FD-series tasks and source-backed answer oracles for:

1. termr API discovery for an explicit terminal interaction.
2. climenu selection/menu API discovery.
3. validate documentation lookup for an explicit validation behavior.
4. A negative name/requirement where safe abstention is correct.
5. An actually documented ambiguous alias/topic from the chosen fixture.
6. Version-sensitive lookup where the requested history may be unavailable.
7. A non-discovery coding control inspired by C01, with fresh data/wording.

Do not invent concrete termr/climenu/validate function names before inspecting
the approved source snapshots. An ambiguous case must exist in its oracle;
otherwise substitute a clearly labelled synthetic control instead of claiming a
real-package ambiguity.

Each task needs a frozen source/version manifest, checksum/digest, provenance,
answer contract, allowed evidence and explicit success/abstention rules. Keep the
same scorer contract in both arms. Recommendation tasks can retain reviewed
V2.1 semantics; function-discovery oracles need their own reviewed frozen
contract before execution. Do not silently repurpose existing feature IDs.

Historical B1 prompts/results have already been inspected in this development
session. If any prompt is reused for continuity, label it exploratory with
contamination/comparison limitations and do not pool it with fresh tasks or claim
independent replication. Prefer fresh tasks and data.

## Source and transport control

Real pinned B1 package archives are currently missing locally. This blocks a
credible historical replay and B2 source freeze; no automatic downloads are part
of this plan. Obtain separately authorized official snapshots first and review
the source manifest. Current repository URLs may move; never refetch current
data silently during a trial.

Use the same reviewed offline provider/MockTransport fixture adapter injected
server-side through KnowledgeService in both arms. Caller tool inputs must not
gain local-path or URL selection. Record archive and index content hashes, exact
version/release/category/R mapping, upstream capture time and offline check time.
A private test server/launcher adapter may need to be prepared and reviewed before
B2; this document does not claim an executable B2 runner already exists.

Fix cache policy: isolated provider/session per trial, same cold/warm preflight
in both arms, no cross-arm transcript or cache state. If latency is secondary,
separate cold-fetch overhead from warm index/query time.

## Allocation, sample size and stopping

Pre-register seven tasks and five paired repetitions per task: 35 pairs, 70
trials maximum. Randomize balanced AB/BA order using a recorded seed and retain
the task/repetition pair IDs. A smaller two-pair-per-task pilot (28 trials) may be
used only for pre-registered feasibility, with exploratory conclusions and no
optional stopping for favorable results. Do not choose a sample size from B1's
call-level effect because calls within trials are dependent.

Before any paid run, specify an operator-approved total spend/token cap, model
price/version and per-trial limits. Proposed operational caps: 180 seconds and
45 MCP calls per trial, with the existing 60-second tool deadline. Report
timeouts/abstentions rather than extending limits in one arm.

Stop the experiment for a source hash/version mismatch, missing native parity
preflight, unbounded/invalid tool output, any false verified API claim by the
tool, unexpected outbound request or spend limit. Quarantine an affected pair;
do not silently replace only its unfavorable arm. Resumption and exclusion rules
must be recorded before outcomes are read.

## Outcomes and analysis

Primary, per trial/pair:
- docs_not_found count.
- Successful version-consistent verified docs resolution.
- Final-answer correctness under the same frozen scorer.
- Scorer abstention rate and reason.

Secondary:
- Discovery calls/adoption on eligible tasks and non-discovery controls.
- Unique failed names, correction attempts and recovery after miss.
- Exact/alias/topic/normalized/fuzzy discovery events.
- MCP call count, latency p50/p95, response bytes and actual token usage if present.
- Source verification and wrong-function/API recommendations.

A fuzzy candidate is not an exact match, not a prevented docs miss and not proof
of user intent. Count retrieval success only after actual docs were obtained
from the same versioned snapshot. Tool-verified alias presence, namespace export
declaration and runtime callability remain separate.

Use paired trial deltas and task-stratified raw counts. Report uncertainty at the
pair/trial level (for example paired bootstrap over task/repetition pairs); do
not treat each call as independent. Keep abstention denominator visible. Report
adoption separately from answer correctness; more calls do not prove benefit.

Proposed preregistered engineering targets: zero false source-backed verified
exports/aliases; at least 30% fewer docs misses on discovery tasks; no observed
correctness or appropriate-abstention regression on negative/control tasks.
These are targets, not achieved effects or statistically powered guarantees.
If uncertainty is wide, report inconclusive rather than causality.

Deterministic offline replay measures retrieval changes only. This B2 measures
agent adoption and outcomes. A later server-description experiment must hold the
toolset/implementation fixed and change description alone. P1-B leaves original
B1 descriptions, prompts, scorers, frozen evidence and historical results intact.
