# Prompt Output Evaluation

This evaluation measures deterministic prompt structure and size. It does not
measure downstream coding-agent correctness or task success.

## Method

Run `python scripts/evaluate_prompt_output.py --output <path>` from the
repository root. The evaluator uses a fixed synthetic `OfflineKnowledge`
provider and makes no network requests. Synthetic package versions end in
`-fixture`; they are test values, not CRAN or Bioconductor claims. It produces
one record for each of 20 named scenarios at each of `concise`, `standard` and
`comprehensive` detail levels. Each record includes characters, UTF-8 bytes,
an estimated token count (`ceil(bytes / 4)`), repeated nonempty lines, included
sections, selected templates, retained constraints, package and function
verification references, assumptions and warnings.

`docs/prompt_output_baseline.json` was generated from the Task 3 implementation
using the same evaluator and fixture. `docs/prompt_output_after.json` records
the current implementation. Neither dataset was hand-edited.

## Size results

Mean prompt characters across the five simple tasks:

| Detail level | Baseline | Current | Change |
| --- | ---: | ---: | ---: |
| Concise | 4,670 | 1,998 | -57.2% |
| Standard | 4,736 | 4,517 | -4.6% |
| Comprehensive | 5,110 | 4,891 | -4.3% |

Current concise output is 57.8% shorter on average than the original
implementation's standard output for these five simple cases. The cases also
retain a strict size order: concise < standard < comprehensive.

| Simple scenario | Original standard | Current concise | Reduction |
| --- | ---: | ---: | ---: |
| ggplot2 scatter plot | 3,186 | 652 | 79.5% |
| dplyr row filter | 3,710 | 986 | 73.4% |
| readr CSV import | 5,446 | 2,355 | 56.8% |
| grouped dplyr summary | 5,261 | 2,461 | 53.2% |
| SQLite query through DBI | 6,078 | 3,534 | 41.9% |

The concise output remains longer for SQL and data-import tasks because it
retains structured input, grounded package facts and applicable safeguards.
It does not target a universal maximum size. The five complex workflow concise
prompts range from 4,936 to 7,906 characters because their stage and dependency
contracts remain explicit.

## Causes and changes

The category instruction was inserted into both functional requirements and
implementation guidance, while the standard renderer also printed it under
technical requirements. The single-task renderer included the same extensive
generic sections for trivial requests, and it repeated the original request
after already stating it as the objective.

The category instruction now renders once. Single-task concise output selects
only task-relevant guidance, requirements, caller context, package facts,
material unknowns, relevant safety boundaries and provenance. A small concise
guidance map shortens the verbose CSV import, cleaning and validation advice
while retaining its key checks. Composed concise output uses the existing plan
and keeps stage identities, topological order, dependency edges, inputs,
outputs, constraints, conflicts and package provenance. No planner or template
registry was added. Standard composed prompts now scope SQL safeguards and
database test advice to workflows that include database work; comprehensive
composed prompts add an extended verification checklist.

## Preserved invariants and coverage

Regression tests at the public `PromptIntelligence.build_r_prompt` boundary
cover all three detail levels, verified and missing function documentation,
CRAN and Bioconductor version/source context, explicit user constraints,
structured input fields, Russian requests, deterministic rendering,
multi-template deduplication, explicit stage order, reported conflicts and SQL
parameterization plus authorization/backup/rollback safeguards. Complex
workflow tests check the returned stage identities and dependency order. The
existing MCP error tests continue to check the structured tool result and
`isError` behavior from Task 3.

Tests use simulated package metadata. The evaluator does not benchmark live
provider behavior, tokenize prompts with a model tokenizer, or test whether a
coding agent completes tasks more successfully. Shorter output alone is not
evidence of better downstream performance; that experiment remains outside
this task.
