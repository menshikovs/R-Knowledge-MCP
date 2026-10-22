# R10: Local reproducible Quarto report

Create report.qmd (no solution.R required). Title 'Sales audit', HTML with embedded resources, echo disabled, errors fatal, no frozen/cache execution. Read local data/sales.csv with columns group (character) and amount (numeric). Exclude missing/nonfinite amounts; group missing group as 'Unknown'. Under heading 'Group totals', render a table containing group, total and n; sort groups. Include a table for empty data with the same headers. Rendering must work with replacement local fixtures, no absolute paths, network, package installs, random values or wall-clock dates. Choose presentation freely. Command: quarto render report.qmd --to html --output report.html.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: knitr, rmarkdown, xml2.
Example input is in data/sales.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
