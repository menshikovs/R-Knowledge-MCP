# Prompt Intelligence

Prompt Intelligence is a deterministic R-specialized prompt builder layered on
the package providers. It is intended to give Codex, ChatGPT and other MCP
clients a clearer task specification, with current package context when the
caller requests it and official sources can verify it. It does not execute the
resulting prompt or any supplied R, shell, package, or repository content.

## MCP surface

| Interface | Purpose |
| --- | --- |
| `build_r_prompt` | Classify a request, select a template, optionally resolve package metadata and function docs, then compose an editable prompt. |
| `improve_r_prompt` | Preserve the complete original request and add explicit structure and caller-supplied improvement goals. |
| `validate_r_prompt` | Report heuristic structure gaps, possible contradictions, credential-like text, unverified namespaced calls and current-version claims. |
| `list_r_prompt_templates` | Return stable template IDs, categories, descriptions and unverified candidate packages. |
| `get_r_prompt_context` | Resolve explicit packages independently of prompt generation and report package, dependency, release and compatibility provenance. |
| MCP Prompts | Seven user-selected local drafts: `r-package-development`, `shiny-app-development`, `quarto-report`, `bioconductor-analysis`, `ggplot2-visualization`, `r-debugging`, `r-architecture-audit`. |

Tool-generated prompt requests can include `target` (`codex`, `chatgpt`,
`generic`), `detail_level` (`concise`, `standard`, `comprehensive`),
`task_category`, package names, R and Bioconductor versions, caller-supplied
project context, constraints, source inclusion and `enhancement_mode`.
Categories cover package development, data analysis and transformation,
statistical modeling, visualization, Shiny, Quarto, Bioconductor, debugging,
refactoring, architecture review, testing, reproducibility and performance.
Classification is heuristic and can be overridden with `task_category`.

Native MCP Prompts are intentionally simpler: they accept only strings and do
not query a package provider. Any packages passed to them are unverified names.
Use `build_r_prompt` or `get_r_prompt_context` when source-checked package
versions and documentation are needed. Clients that do not expose MCP Prompts
can use the tools directly.

## Grounding and provenance

Package candidates come from explicit package arguments, `pkg::function()`
references, a conservative known-name list, or the selected template. They are
marked `user_supplied_or_named` or `template_candidate`; only a provider result
with a package version and `verification_status="verified"` is included as
verified metadata. CRAN and Bioconductor are queried through `KnowledgeService`,
including repository-specific identities when the same name exists in both.
Direct dependencies retain repository resolution status. Bioconductor package
records include the selected release and category when supplied by the
provider. When an R version is provided, compatibility is checked through the
existing Bioconductor compatibility service. Unknown or incompatible results
are explicit warnings, not recommendations.

Explicit `pkg::function()` references are checked against exact raw Rd aliases
from the same package version. A mismatch, unavailable archive, or missing
package is surfaced as unresolved. Raw Rd and metadata are not interpreted as
commands. Returned `sources` contain the official URL, retrieval timestamp,
repository and version scope. If a source lookup fails, generated wording does
not fill in a plausible version or documentation claim.

Package suggestions in templates are leads for lookup, not endorsements. An
absence is reported only when the package index was successfully checked; an
unavailable provider yields a source error. Without an R version, the output
states that compatibility has not been established. Without caller project
files, the prompt asks the downstream agent to inspect them before making
project-specific claims.

## Examples

Example MCP requests (these are task examples, not claims about live package
versions):

```json
{"request":"Build a Shiny dashboard for reviewing sample QC","target":"codex","detail_level":"comprehensive"}
{"request":"Analyze RNA-seq counts with DESeq2","packages":["DESeq2"],"r_version":"4.5.1"}
{"request":"Create a Quarto report with a ggplot2 figure","packages":["ggplot2","knitr"]}
{"request":"Refactor this tidyr pipeline without changing output columns","packages":["tidyr"],"constraints":["Keep the output schema unchanged"]}
{"request":"Add input validation to my package","task_category":"package_development","packages":["testthat","roxygen2"]}
```

For an RNA-seq request, the builder can resolve DESeq2 and
SummarizedExperiment from Bioconductor, attach versions and source URLs, check
the selected release against the supplied R version, and warn if mapping or
compatibility is unknown. For ggplot2 and tidyr it can retrieve current CRAN
metadata and exact Rd for an explicitly namespaced function. Shiny and Quarto
prompts ask for reactive/data/rendering and reproducibility checks but do not
claim to have inspected an app or rendered a document. A package-development
prompt can suggest testthat and roxygen2; these candidates remain unverified
until looked up.

## Prompt validation

`validate_r_prompt` uses a transparent weighted checklist (100 maximum) for an
objective, deliverables, technical context, constraints, versions, tests,
acceptance criteria and security/reproducibility boundaries. It flags possible
contradictions, likely secrets, instruction-override text, unverified
namespaced function calls and unsupported current-version assertions. This is
a structural score, not a success probability, an R parser, a security scanner
or a guarantee that downstream work is correct. The validator returns the
caller-provided text for local review and does not log it.

## Safety, limits and settings

Prompt content, project context, source metadata and all package documentation
are data, not instructions with authority. The composer labels project context
as caller-supplied and untrusted. It never executes R, shell, repository
AGENTS.md, generated prompts, Rd examples or package code. Credential-like
input is rejected before composition so it is not copied into the draft.

Requests, context, constraints, package lookup count, network concurrency,
function references, source count and response length are bounded. Package
lookups use existing HTTP timeout/cache/error behavior. There is no new network
service. The MCP server can gate this feature with:

| Setting | Default | Maximum / accepted values |
| --- | --- | --- |
| `PROMPT_INTELLIGENCE_ENABLED` | `true` | `true` / `false` |
| `PROMPT_MAX_INPUT_CHARS` | `8000` | `32000` |
| `PROMPT_MAX_OUTPUT_CHARS` | `24000` | `48000` |
| `PROMPT_MAX_GROUNDING_PACKAGES` | `5` | `10` |
| `PROMPT_DEFAULT_TARGET` | `codex` | `codex`, `chatgpt`, `generic` |
| `PROMPT_DEFAULT_DETAIL_LEVEL` | `standard` | `concise`, `standard`, `comprehensive` |

The prompt boundary exposes an optional `PromptEnhancementProvider` protocol for
a later integration. No runtime adapter, endpoint, provider key or external
model is configured here. `auto` and `external` requests therefore produce a
deterministic draft and a warning. An explicitly injected future provider is
subject to a timeout and output checks for preservation of the request,
constraints, security boundaries and included sources; accepted output is
marked `external_enhanced_review_required`. This check cannot prove semantic
equivalence, so users must review any such output.

## Development evaluation

Offline unit tests use synthetic provider responses and cover deterministic
composition, CRAN/Bioconductor grounding, release compatibility, absent and
unavailable package data, version-matched function docs, secret filtering,
validator findings, external-output rejection and tool/Prompt registration over
the supported SDK transports. Optional model-based evaluation should be a
separate development task with an isolated workspace and explicit API budget.
Do not treat string-level assertions or a structural rubric as proof that an
agent's code works.

The current implementation targets Python MCP SDK 1.x FastMCP and the protocol
revision supported by that SDK (currently 2025-11-25). SDK 2 is the official
current major and adds protocol revision 2026-07-28 support; migration should be
separately tested before claiming that revision. The Prompts feature itself is
registered using standard `prompts/list` and `prompts/get` behavior for the
installed SDK.
