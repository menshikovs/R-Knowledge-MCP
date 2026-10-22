# R02: Grouped sales

Implement `summarize_sales(data)` using dplyr. Columns: team (character or factor), amount (numeric), active (logical). Keep active TRUE rows with nonblank/nonmissing team and finite amount; trim team names. Include negative amounts. Return an ungrouped data.frame/tibble with team (character), total (double), n (integer), sorted by team. Retain groups whose sum is zero. Empty input must return typed empty columns.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: dplyr.
Example input is in data/sales.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
