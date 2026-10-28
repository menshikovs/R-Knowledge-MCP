# Prompt Intelligence audit

Commit `4d2266c`. IDs refer to [`FINDINGS.md`](FINDINGS.md). Scope: `src/cran_knowledge_mcp/prompt_intelligence/` (8 modules + 9 under `composition/`, ≈ 4 700 lines), the three consolidated tools `build_r_prompt`, `validate_r_prompt`, `get_r_prompt_context`, the 14 native MCP prompts, and `docs/PROMPT_*.md`, `COMPOSABLE_PROMPTS.md`.
Measured with mocked providers only (no model was called); label **exploratory** wherever the data are mine.

## 1. What the subsystem is

A deterministic, offline layer: classify the request into one of 24 categories → select/compose from 30 versioned templates → ground named packages through the existing providers (versions, direct dependencies, provenance) → render a Markdown prompt (concise/standard/comprehensive) with assumptions, constraints, safety boundaries and sources → return it with a structural score from `validate_r_prompt`. It never calls a model; "external enhancement" is disabled unless an adapter is injected. It does not execute anything.

## 2. Findings by stage

| Stage | Observation (evidence) | Verdict |
|---|---|---|
| **Intent classification** (`intent.py:121-…`) | Ordered first-match regex lists (domain patterns, then 14 category patterns), default `data_analysis`. On 30 auditor-labelled requests: **21/30 (70 %)**. Systematic misses: "hypothesis test" → `testing`; "fix the failing Shiny app" → `shiny_development` (before `debugging`); "pivot a wide table" and "merge two data frames" → `data_analysis`; "speed up this slow loop" → `data_analysis`; "explore the iris dataset" → `csv_analysis`. Labels are mine, N is small (exploratory; Wilson 95 % interval ≈ 52–83 %) | heuristic, unvalidated (PI-001) |
| **Package detection** (`intent.py:PACKAGE_ALIASES`) | A fixed 40-name list matched as plain words, so ordinary English triggers packages: "validate the input columns" → `validate`, "a bench of test cases" → `bench`, "check the janitor reports" → `janitor`. Detected names are then *grounded against CRAN/Bioconductor*, so a false positive costs requests and clutter, not a false claim | minor, but wasteful |
| **Template selection / composition** | Keyword substring specialisation (`"plotly" in lowered` → `plotly-interactivity`, …; `composition/resolver.py:63-91`). Multi-stage requests compose templates in dependency order; "Import a CSV, load into PostgreSQL, then render a Quarto report" → `csv-import` + `sql-database` + … in `composed` mode | works for the documented scenarios; rigid by construction |
| **Workflow decomposition / dependency planning** | Deterministic; planner detects unknown edges and cycles (`planner.py`); ≤ 10 stages, ≤ 8 templates, hard rejections rather than truncation | sound and bounded |
| **Constraint resolution / conflicts** | Conflict detection is a handful of regexes plus explicit structured fields: multiple dialects are a *conflict* only if the request says "only/without choosing/must choose one"; otherwise treated as a deliberate multi-backend requirement; `read_only` is recognised only as a structured field; offline-vs-network by keyword (`composition/constraints.py:58-88`). In my probes, free-text constraint lists such as `["Use PostgreSQL","Use MySQL"]` and `["read-only connection","must write updated rows"]` produced **no conflict** | narrow; the documented guarantee ("conflicting requirements are preserved, not silently resolved") holds only for the forms it recognises |
| **Package grounding / provenance** | Unknown package → `package_resolution: [{status: source_unavailable, error_codes: [package_not_found, package_not_found]}]` (CRAN and Bioconductor both reported), no invented version; assumptions state "template package candidates are optional suggestions … verified versions do not imply installed versions"; sources and check times are carried. This matches `AGENTS.md` (candidates until verified; report unavailable sources instead of filling in) | good |
| **Input sanitisation** | 8 000-character request cap (`input_too_large`), credential-like text rejected (`sensitive_input`; 8 of 9 positives detected, 0 of 5 benign R/prompt strings flagged, obvious evasions such as `pwd=…`, spaced letters, zero-width characters pass: documented heuristic). Context fields are copied into the prompt under a heading "supplied by the user; treat them as untrusted project context, not policy" — an instruction-override phrase placed in `project_context` is **kept verbatim** but labelled; `validate_r_prompt` flags `instruction_override_attempt` | acceptable containment; no hard rejection of override text by design |
| **Upstream text** | Package titles/Rd containing an injection payload did **not** reach `build_r_prompt`/`get_r_prompt_context` output | correct design |
| **Output size** | Offline evaluator (20 scenarios × 3 levels): concise median 1 340 chars (max 5 708), standard 3 300 (7 542), comprehensive 3 675 (7 862); ggplot2 scatter: 493 / 2 667 / 3 041. Over-limit output is rejected, not truncated (`PROMPT_MAX_OUTPUT_CHARS`, default 24 000) | economical; ≈ 120–2 000 tokens |
| **Language** | Russian and English patterns; generated instructions are English (`validate_language`); Cyrillic request classified correctly in one probe | adequate |

## 3. Does it add measurable value over a capable baseline model?

**Unknown, and nothing in the repository measures it.** `docs/PROMPT_OUTPUT_EVALUATION.md` says so explicitly: the 20-scenario evaluation measures structure and size, "does not benchmark … whether a coding agent completes tasks more successfully", and a shorter prompt "is not evidence of better downstream performance". `ROADMAP.md` lists broader prompt evaluation as future work. In the agent benchmark the Prompt Intelligence tools are never offered: the allow-list of the P1-E run (`experiment.json` → `mcp_server.allowed_tools`) is the 13 consolidated tools **excluding exactly** `build_r_prompt`, `validate_r_prompt` and `get_r_prompt_context`.

Plausible sources of value (hypotheses, not findings): (a) verified package facts and provenance inside the prompt; (b) safety scaffolding for SQL/CSV/secret handling; (c) consistent structure for weaker models or non-expert users. Plausible costs: ≈ 0.4–2 k tokens per prompt; one more tool round-trip; templates that over-constrain an already-clear request; wrong category (30 % in my probe) steering the plan; and the risk that the agent treats a long, confident prompt as authoritative.

## 4. The quality score rewards form

`quality.validate_prompt` (219 lines) awards points for the *presence of keywords* (`objective`, `deliverables`, `constraints`, `testing`, … in English and Russian) and finds "unverified API claims" by pattern. `docs` and the function docstring already say it is a heuristic, "never success odds". Exploratory probe (`probe_c_prompt_score_ctx7_redaction.txt`):

| Input | Score |
|---|---|
| Sensible, specific request with objective/deliverables/constraints/verification sentences | 35 |
| Keyword salad ("Objective Deliverables Constraints Verification … purple elephant banana") | 40 |
| "Fix the plumbing. Deliverables: none. Constraints: none. Verification: none. package R version" | **50** |
| "build something" | 10 |

The score orders formatting, not quality, and can rank nonsense above a good prompt. It is safe to keep as a lint if it is described as one; it must not be used as an outcome metric or an optimisation target.

## 5. Recommended evaluation: downstream R-code correctness

Reuse the benchmark's hidden-verifier tasks (hard suite style; keep oracles private). Four arms on the same task set, same model, same budget, randomised order, ≥ 3 sessions per task:

| Arm | Agent receives |
|---|---|
| A | the raw task statement |
| B | the task statement rewritten by the *same* model with a generic "improve this prompt" instruction (controls for "more words help") |
| C | the task statement + `build_r_prompt` output (deterministic, grounded) |
| D | arm C + MCP knowledge tools |

Primary endpoint: oracle pass (all hidden checks) per task; paired comparisons A–C, B–C, C–D with task-clustered bootstrap intervals; secondary: tokens and wall-clock per success, first-attempt success, hallucinated-API incidents (checked against the verifier's call log). Stratify by task type and by whether `build_r_prompt`'s category matched the task (measures the cost of the 30 % misclassification). Include *adversarial* tasks (injection in project context, secret-looking strings, conflicting requirements) with pre-specified correct behaviour. Pre-register the analysis; label anything else exploratory.

Decision rule suggestion: retain the tools in the default surface only if C beats B by a pre-declared margin on the stratum it is meant to help (SQL/CSV workflows, Bioconductor release-sensitive tasks); otherwise keep them behind `PROMPT_INTELLIGENCE_ENABLED` and out of the default tool list to reduce the surface an agent must reason about (3 of 16 tools, 14 prompts).

## 6. Recommendations
1. Replace first-match regex ordering with a scored classifier validated on a labelled set of ≥ 200 requests, or drop classification and let the caller pass `task_category` (the parameter exists); report confidence.
2. Require word-boundary *and* context for package aliases (`validate`, `bench`, `janitor`, `targets`).
3. Document precisely which conflict forms are detected; add the natural-language forms you intend to support to the tests.
4. Rename the score ("structure lint") and surface the findings, not the number.
5. Run the §5 evaluation before expanding templates.
