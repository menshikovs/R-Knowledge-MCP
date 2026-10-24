# Technology stack recommendations

`recommend_technology_stack` is a read-only, deterministic planning tool for R-related
projects. It returns a provisional architecture profile, candidate R packages grouped
by role, direct dependency fields, alternatives, deployment and security considerations,
an implementation sequence, and questions that still need project-owner decisions.

## Example

```json
{
  "objective": "Build an internal dashboard for reviewing validated analysis results",
  "project_type": "dashboard",
  "requirements": [
    "Keep user supplied Russian text unchanged: сохранить исходные формулировки",
    "Do not expose credentials in source files"
  ],
  "existing_stack": ["R", "PostgreSQL"],
  "deployment_target": "docker",
  "preferences": {
    "prefer": ["bslib"],
    "exclude": []
  }
}
```

`project_type` accepts `analytics`, `api`, `dashboard`, `package`, `etl`, `ml`, or
`other`. `deployment_target` accepts `local`, `docker`, `cloud`, or `on_premises`.
`preferences` contains optional `prefer` and `exclude` string lists. The tool preserves
objective, requirements, existing-stack entries, and preferences verbatim in
`user_inputs_preserved`; non-English text is not translated.
Inputs that match common credential patterns are rejected before metadata lookups.

## Evidence and limits

- Architecture profiles are deterministic heuristics matched to the project type.
  They are provisional recommendations, not compatibility or success guarantees.
- R package candidates are taken from the existing workflow template registry. A
  candidate is labeled recommended only when current CRAN package metadata is available
  and its title or description contains role-relevant evidence. Excluded packages are
  not looked up. A metadata mismatch is surfaced for user review rather than treated as
  a recommendation.
- API and ML profiles have no matching package workflow template. They search current
  CRAN package names/titles using a fixed role query, then require the package DESCRIPTION
  to match that role before recommending a result. Search results alone are not enough.
- Package versions and source URLs come from the configured repository provider at
  `checked_at`. These are repository records, not installed versions.
- `Depends`, `Imports`, `LinkingTo`, and `Suggests` are direct verbatim repository
  fields. They are not expanded into a transitive dependency graph.
- No R version is inferred. Bioconductor compatibility, local environment state,
  deployment compatibility, and actual behavior are not established by this tool.
- No complementary non-R product is named unless the user already supplied it. For an
  API profile, framework selection remains provisional and the tool asks the user to
  confirm the request contract and choose among any metadata-matched candidates.
- The tool does not install packages, inspect files, run code, deploy services, or call
  an LLM API. Package metadata requests use the same read-only providers as the other
  repository tools.

## Output contract

The structured result includes `recommended_architecture`, `stack`, `package_checks`,
`dependencies`, `compatibility`, `alternatives_and_tradeoffs`,
`security_maintenance_deployment`, `suggested_implementation_sequence`, `sources`,
`user_inputs_preserved`, and `unknowns_requiring_user_decisions`. The top-level
`verification_status` remains `partial` because project-specific compatibility and
deployment behavior require further evidence.
