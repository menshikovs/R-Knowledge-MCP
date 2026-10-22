# R11: Pinned Bioconductor interval summary

Implement `summarize_ranges(data)` using IRanges 2.44.0 in Bioconductor 3.22 / R 4.5.2. Columns: chr (character), start/end (integer, 1-based inclusive). Reject missing/blank chr, missing endpoints, starts < 1, reversed or noninteger endpoints. Within each chromosome merge overlapping AND adjacent intervals. Return chr (character), bases (integer total covered width), segments (integer merged range count), sorted by chr. Return typed empty output for empty input. Use synthetic data only; do not download genomes.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: IRanges.
Example input is in data/ranges.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
