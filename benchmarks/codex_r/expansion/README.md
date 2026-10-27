# R benchmark expansion registry v1

This directory imports the user-supplied public task specifications into a
versioned catalog. The catalog is separate from the R01–R12 pilot and hard-v1
manifests, so it does not change historical task selection, `--tasks all`, scoring,
or experiment fingerprints.

## Source inventory

The catalog contains 148 specifications from six allow-listed public documents:

| Family | Specs | Canonical ID prefix |
| --- | ---: | --- |
| Base R beginner | 20 | `BEGINNER-` |
| ggplot2 | 41 | `GGP-` |
| R ecosystem discovery and API | 37 | `ECO-` |
| R ecosystem add-on | 25 | `ADDON-` |
| ANOVA | 15 | `ANOVA-` |
| Hard benchmark blueprint | 10 | `HARD-` |

Each entry preserves its original ID, title, public source document and SHA-256,
candidate-facing task text, implementation status, validation status, and blockers.
The registry also records the existing pilot's frozen R, Bioconductor, and ggplot2
versions and flags exact source/runtime conflicts.
The generated `registry-v1.json` contains no private solution or evaluator text.
`source-mapping-v1.json` provides a task-by-task mapping; `audit-v1.json` holds
counts without treating specifications as runnable tasks.

## Implemented slice

The Python registry builder validates the supplied source manifest and public
document hashes, checks suite counts and unique namespaced IDs, and parses each
public task into a prompt record. The exporter writes one `TASK.md` from the
allow-listed public text into a new directory outside the repository. It never
exports fixtures, metadata, answer keys, solutions, or verifier code. The current
export is prompt-only; it does not imply that a task can be run or scored. For the
hard blueprint, the exporter removes each `Hidden verification` section and keeps
only the task heading, package/category context, and agent-visible contract.

Regenerate the machine-readable files with:

```sh
python -m benchmarks.codex_r.expansion.registry build
```

Export one public prompt to a new isolated directory outside this repository with:

```sh
python -m benchmarks.codex_r.expansion.registry export ADDON-C09 /tmp/addon-c09
```

## Counts and validation status

- 148 source specifications imported.
- 3 source specs (`HARD-H01`, `HARD-H04`, `HARD-H10`) map to existing hard-v1 tasks.
- 145 source specs remain specification-only; no expansion-owned R fixtures,
  artifact adapters, hidden verifiers, or offline R validation gates exist for them.
- 0 new R tasks were implemented or validated in this change.
- The existing hard-v1 README records an offline validation pass for H01/H04/H10
  on 2026-10-24. That record was not replayed here. H04 is a documented semantic
  substitution from data.table to the pinned dplyr rolling-join API.
- The repository contains 12 separate legacy R01–R12 tasks. The machine crosswalk
  records nearby themes for manual review, but does not claim those are duplicates.
  The gross count is 160 (148 source specs plus 12 legacy tasks); exact deduplicated
  count has not been verified. If every entry is distinct, at least 80 more unique
  tasks are needed to reach 240. Existing H01/H04/H10 are included within the 148,
  not added on top.

The source bundle's ANOVA document says its fixtures and verifiers have not been
implemented. It targets R 4.6/Bioconductor 3.23 in places, while the existing pilot
manifests pin R 4.5.2/Bioconductor 3.22. The existing lockfile pins ggplot2 4.0.3;
the version-specific ecosystem tasks and add-on C02 require ggplot2 4.0.0. Several
ecosystem tasks also require packages absent from the hard-v1 runtime. These tasks
need a separate reviewed environment and versioned source snapshots.

The repository's `AGENTS.md` says never to execute R, package scripts, or metadata.
For that reason this change validates only the Python catalog and prompt-export
slice. It does not claim that any R solution example, statistical oracle, plot, or
package API has been run.

See [BACKLOG.md](BACKLOG.md) for the resumable implementation sequence.
