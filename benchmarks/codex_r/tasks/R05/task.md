# R05: Irregular visits

Implement `pivot_visits(data)` with tidyr. Input columns: id (character), score_w1 and score_w2 (numeric), flag_w1 and flag_w2 (logical). Return id (character), week (integer 1 or 2), score (double), flag (logical), sorted by id/week. Preserve missing measurements and every id/week combination. Reject duplicate or missing ids. Handle typed zero-row input.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: tidyr.
Example input is in data/visits.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
