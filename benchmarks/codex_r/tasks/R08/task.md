# R08: Shiny reactive filtering

Implement `make_filter_server(data)`, a factory returning a Shiny server function with arguments `(input, output, session)`. data is a reactive data.frame with group (character) and value (numeric). The returned server defines reactive expressions named `filtered` and `total`. filtered retains finite values >= input$minimum (default 0), nonmissing groups, and optionally input$group (default 'all'); preserve row order. total is a double sum of filtered$value, zero when empty. Changes to inputs AND the data reactive must invalidate outputs. No global shared reactive state.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: shiny.
Example input is in data/values.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
