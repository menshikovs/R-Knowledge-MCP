# Benchmark measurement hardening: scorer and telemetry v2

This note describes the opt-in D/E JSON evaluator and benchmark-only MCP projection format.
It changes no production MCP tool, description, prompt, server instruction, or response.
No historical run, score, event file, or baseline is rewritten.

## Version selection and reproducibility

The existing D/E evaluator remains the default (`legacy`) and keeps its original predicates.
To select the new evaluator explicitly for a future pilot run:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple \
  --effort medium --pilot tool-value --knowledge-pilot-scorer knowledge-pilot-v2
```

The V2 configuration id is `consolidated-v2`; it exposes the same MCP toolset and changes
only the D/E candidate instructions, public output contracts, and evaluator. B/C and the E02/E03
R verifier continue through their existing scoring paths. A run manifest records the scorer id,
evaluator SHA-256, the combined contract SHA-256, and each task contract SHA-256. Resume reads
that saved identity and rejects a different scorer choice. Legacy manifests omit those V2-only
fields, so their configuration identity remains stable.

The V2 evaluator reads only the bounded `answer.json` artifact and local frozen evidence. It does
not make network requests, run an LLM, run R, or invoke Docker. It returns `overall_score: null`
and no combined pass count: the dimensions have different meanings and must be reviewed
separately. `fully_correct` is `null` when an answer contains claims that cannot be automatically
checked; it is never promoted to a pass based on an unknown.

## Public D/E JSON contracts

Each V2 candidate workspace receives `OUTPUT_SCHEMA.json`, the public task-specific JSON Schema,
and a task note that names it. The schema files are:

| Task | Contract |
|---|---|
| D01 | [`knowledge_pilot/contracts/v2/D01.schema.json`](knowledge_pilot/contracts/v2/D01.schema.json) |
| D02 | [`knowledge_pilot/contracts/v2/D02.schema.json`](knowledge_pilot/contracts/v2/D02.schema.json) |
| D03 | [`knowledge_pilot/contracts/v2/D03.schema.json`](knowledge_pilot/contracts/v2/D03.schema.json) |
| E01 | [`knowledge_pilot/contracts/v2/E01.schema.json`](knowledge_pilot/contracts/v2/E01.schema.json) |
| E04 | [`knowledge_pilot/contracts/v2/E04.schema.json`](knowledge_pilot/contracts/v2/E04.schema.json) |
| E05 | [`knowledge_pilot/contracts/v2/E05.schema.json`](knowledge_pilot/contracts/v2/E05.schema.json) |

Schemas reject undeclared fields and malformed types. They list the supported equivalent forms;
the scorer normalizes only those forms. Examples include E01 package maps or package-record
arrays, `minimum_version` or a `>= version` edge constraint, a string or one-item list for
`changed_fields`, E04 repository maps or repository-record arrays, and E05 case maps or case
arrays. Source strings and `{ "url": ... }` source objects are both defined. Undocumented
shapes are schema failures, not silently ignored facts.

The V2 result separates:

| Dimension | Meaning |
|---|---|
| `schema_validity` | Strict conformance to the public task contract. |
| `factual_correctness` | Required task claims checked against frozen facts. |
| `version_repository_identity` | Package version and repository/release identities. |
| `dependency_correctness` | Required dependency edge and exact minimum constraint where applicable. |
| `source_quality` | Official source host and task-scope checks; D uses the frozen package/version URL allowlist. |
| `unsupported_claims` | Additional claims outside the local frozen evidence bundle. |

An unsupported dimension is not a failure or a pass. Invalid contracts mark other factual
dimensions `not_evaluated`; they do not invent a score for facts that could not be normalized.

## D recommendation policy

The D task prompts permit more than one package and do not declare a closed package universe.
The frozen `candidates.json` plus `official_resources.json` currently provide automated evidence
for their listed packages and exact versions. D recommendations inside that evidence bundle are
checked for the selected version, frozen CRAN source/documentation URL, requested feature IDs,
and documented caveat IDs. These checks are kept in separate factual, identity, and source
dimensions.

A package name outside that frozen evidence set—including `utils` or `httptest`—is returned as
`unsupported_for_automatic_scoring`. Its schema can still be valid, while its factual identity and
source dimensions remain unsupported. Existence, familiarity, or a plausible URL never establishes
that it satisfies the task. No network fallback or manual answer-specific exception is used.

This policy is open-world at the task level and evidence-bounded at the automatic scorer. It can
report a candidate failure only for facts the frozen evaluator can check; review of other
alternatives requires a separate documented evidence bundle and a new scorer version.

## Safe MCP observations v2

The runner writes one closed projection record per observed call to
`mcp_observations_v2.jsonl`, validated against
[`telemetry/mcp-observations-v2.schema.json`](telemetry/mcp-observations-v2.schema.json). This
file is separate from normalized `telemetry.jsonl` schema 1.0; old results remain readable.
The runner projects an item before `events.json` redaction, and raw arguments and responses are
not copied into the V2 records. The projection never changes the object returned to the agent.

Request fields are limited to validated package/repository/version/function/section names and
bounded offsets/limits. Search text and other free-text queries are never saved: if they pass the
secret detector, the runner stores only a per-trial keyed fingerprint, UTF-8 byte length, line
count, and word count. The key is process-local and is not written. Likely secrets suppress the
fingerprint and mark the request projection `partially_projected`. Unknown argument names and
values are not stored.

Response fields are limited to structured status/error codes, package/version/repository,
verification status, safe official source URLs, bounded aliases, check time, truncation and page
offset indicators, byte counts, and measured duration. Source URLs must use an allowlisted HTTPS
official host and cannot include credentials, query strings, or fragments. Raw docs, tool result
text, R source, user schemas, prompts, and exception strings are never projected. Large or
malformed fields are dropped. If secret or unbounded structure is detected inside structured
content, the response projection fails closed to status and size fields only.

The agent stream item id and MCP server call number are separate identifiers. There is no shared
protocol call id in the current path, so a matching order and tool name is recorded as
`inferred_ordinal`, never as confirmed. Mismatches create `unmatched_client` and
`unmatched_server` observations. `confirmed` is reserved for future records with the same
explicit client and server protocol ids; the current runner emits none. The server's
`list_tools_requests_observed` count does not establish which definitions the agent actually
received. Advertised tool names and schemas therefore remain `null` with status `unavailable`.

## Metric separation and unknown values

V2 metrics keep three families separate:

* `adoption`: client and server calls actually observed. Tool availability is not counted as use.
* `tool_effectiveness`: observed success/error outcomes and verified-source rate with its known
  denominator. This is tool evidence quality, not answer correctness.
* `efficiency`: observed response bytes and duration. A result-token estimate is
  `ceil(serialized response bytes / 4)` and is explicitly not billed API token usage.

Answer correctness lives in the scorer dimensions. Adoption, tool effectiveness, and efficiency
are not added into a single utility score. Missing observations remain `null` or have an explicit
observation count; missing telemetry is never converted to zero. Confirmed API usage remains a
separate field from estimated MCP response size.

## Local validation

The added scorer fixtures are independent synthetic JSON answers. Telemetry tests use synthetic
secrets, Unicode, malformed values, large documentation strings, and injection-like content to
check the projection boundary. The tests do not contact APIs, CRAN, Bioconductor, GitHub, or
Context7. A benchmark run, model call, and external MCP call are not part of validation.
