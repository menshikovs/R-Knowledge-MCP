# R03: Malformed typed CSV

Implement `import_measurements(path)` with readr, using explicit id=integer, reading=double and group=character column types and missing markers '' and 'NA'. Return list(data=<tibble>, problems=<readr::problems(data)>). Keep row order and malformed cells as typed NA; do not drop records or silently guess types. Malformed numeric cells must appear in problems. A missing file must raise an error. CSV has a header and comma delimiter.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: readr.
Example input is in data/measurements.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
