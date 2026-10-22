# R12: CSV to validated reporting workflow

Implement `build_report(csv_path, output_dir)` in solution.R. Explicitly import id/group as character and x/y as double. Trim id/group; discard blank/missing ids or groups, nonfinite x/y, and y <= 0; keep the first valid row for each id. Return list(data=<clean data sorted by id>, summary=<group character,n integer,mean_y double sorted by group>, plot=<ggplot scatter x/y coloured by group>, report=<path to generated report.qmd>). Write summary.csv, plot.rds and report.qmd into output_dir (create it). The report must render offline to HTML and read its sibling summary.csv and plot.rds via relative paths. Handle empty valid input with typed outputs; error for missing required columns. No arbitrary file access or package installation.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: readr, dplyr, ggplot2, knitr.
Example input is in data/workflow.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
