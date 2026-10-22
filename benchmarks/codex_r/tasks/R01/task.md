# R01: Base R validation

Implement `clean_records(data)` in solution.R. Input has character `id` and numeric `value`. Trim ids, discard missing/blank ids and nonfinite/missing values, keep the first valid record per trimmed id, and sort by id. Return an ungrouped data.frame with exactly `id` (character) and `value` (double), including typed empty outputs. Reject missing columns and wrong input types. Do not mutate input.

Use R 4.5.2 and the supplied runtime lock. This is a base R control task.
Example input is in data/records.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
