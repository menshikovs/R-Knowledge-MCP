# Expansion backlog

Status codes in `registry-v1.json` describe implementation state, not whether a
prompt is scientifically sound. `spec_only` means the public specification is
imported but has no expansion-owned runnable task package. A historical validation
record is not a current re-run.

## Completed in this change

1. Read the 11 Markdown source documents and checked the 148-task source manifest.
2. Imported the six candidate-facing source documents into a namespaced registry;
   preserved the source IDs and hashes.
3. Added a public-only prompt exporter and offline Python tests for counts, source
   boundaries, mappings, and export contents.
4. Mapped the hard-v1 H01/H04/H10 source specs to the actual local task manifests;
   documented H04's package substitution and the date/limits of the recorded gate.
5. Indexed R01–R12 with thematic source candidates and left duplicate decisions
   explicitly unverified.
6. Kept the legacy R01–R12 suite and existing hard-v1 suite unmodified.

## P0 — Runtime and artifact contract

- Design an expansion-owned suite schema that supports `solution.R`,
  `analysis.json`, `report.md`, and task-specific outputs without changing the
  hard-v1 one-file contract.
- Select a separately pinned R image and lockfile. Resolve the R 4.5.2/4.6 and
  Bioconductor 3.22/3.23 split explicitly; freeze exact package versions before
  importing any proposed answer code.
- Define offline candidate/scorer separation, deterministic fixtures, bounded
  outputs, and a verifier protocol before marking any task `implemented`.

## P1 — Validated vertical slice

- Implement one base-R beginner task with a deterministic fixture, independent
  verifier, empty/bad-output controls, and a runner adapter.
- Implement one ggplot task with a pinned ggplot2 version, deterministic data,
  plot-build assertions, rendering/export expectations, and wrong-plot controls.
- Implement the ANOVA pilot candidates A03, A05, A12, A13, and A14 only after
  fixture designs, estimands, independent numeric oracles, and package availability
  are frozen. A05/A12 need explicit hypotheses and contrasts; A13 must distinguish
  the longitudinal model from sums-of-squares labels.
- For every task, require a trusted reference and at least two known-wrong
  strategies to pass through the verifier gate before task status changes.

## P2 — Package and discovery tasks

- Resolve packages absent from the current hard-v1 runtime, including data.table,
  mirai, cranlogs, tximeta, Plotly, Shiny, and any selected GIS/logging toolkit.
- Freeze official versioned documentation/source snapshots for API and discovery
  tasks. Record retrieval URL and timestamp; do not rely on current unpinned pages
  for a historical task.
- Implement robust verifiers for documentation claims, source provenance, package
  versions, and answer calibration. Keep evaluator/reference documents outside
  candidate workspaces.

## P3 — Source families and 240-task target

- Convert all 145 pending specifications into task packages only where fixtures,
  runtime dependencies, independent oracles, and hidden verifiers can be reviewed.
- Deduplicate semantically equivalent tasks against R01–R12 and among source
  families; retain source mappings when variants are intentionally distinct.
- Complete the semantic deduplication review before setting the exact remaining
  count. The current gross arithmetic is 160 entries; 80 is the minimum new unique
  task count only if all 148 source specs and 12 legacy tasks are distinct. Require
  every counted task to have a declared artifact contract and validation state; do
  not count document headings as runnable tasks.
- Update launcher/CLI only after the new suite contract is stable, with regression
  coverage proving legacy task selection and `--tasks all` remain unchanged.

## Blockers that need a policy decision in code/review

- The repo instruction forbids running R, while R-task offline validation requires
  an R runtime. No R task can be marked newly validated under that constraint.
- Some source tasks ask for future/newer runtimes than the existing frozen images.
  Do not silently map those specs onto R 4.5.2 or Bioconductor 3.22.
- Private source answer keys must remain outside every candidate export and scorer
  input available to an evaluated model.
