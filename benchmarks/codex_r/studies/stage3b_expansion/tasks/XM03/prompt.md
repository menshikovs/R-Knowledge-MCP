# XM03: Shiny module workflow with session-scoped caching, event binding and headless testServer replay

A clinical-analytics Shiny module computes weighted cohort summaries on demand when the user clicks
an action button (`input$run`), while caching previously computed `(cohort, min_score)` queries
within the current user session so repeated queries do not recompute. A sample dataset is in
`data/cohorts.csv` (`record_id`, `cohort`, `score`, `weight`).

Use only the packages installed in the supplied environment (`shiny`, `cachem`); do not install
anything. Write `solution.R` defining two functions:

1. `cohort_module_server(id, records)`
2. `replay_cohort_requests(records, requests)`

## Input validation

Both functions must validate `records` before running:
- `records` is a data frame containing `record_id`, `cohort` (character), `score` (numeric), and
  `weight` (numeric), with at least one row and no missing values (`NA`) in any of those columns.
- `record_id` has no duplicates, and every `weight` is strictly positive (`weight > 0`).
- In `replay_cohort_requests(records, requests)`, `requests` must be a data frame with columns
  `cohort` (character) and `min_score` (numeric), at least one row, no missing values, and every
  `requests$cohort` value must appear in `records$cohort`.
If any check fails, stop with an error.

## Function 1: `cohort_module_server(id, records)`

Validate `records`, then call `shiny::moduleServer(id, function(input, output, session) { ... })`:

1. **Audit counters (`reactiveVal`):**
   - `clicks`: integer `reactiveVal(0L)`, incremented by `1L` each time `input$run` fires
     (`observeEvent(input$run, ...)`).
   - `cache_misses`: integer `reactiveVal(0L)`, incremented by `1L` **inside** the cached reactive
     body so it increases only when a cache miss actually runs the computation.
2. **Cached, event-bound summary reactive (`summary_row`):**
   - Filter `records` to rows with `cohort == input$cohort` and `score >= input$min_score`.
   - Compute a 1-row plain `data.frame` with exact columns:
     `cohort` (character), `min_score` (numeric), `n_records` (integer), and `weighted_mean`
     (numeric: `sum(score * weight) / sum(weight)` over matching rows, or `NA_real_` when
     `n_records == 0L`).
   - Pipe the `reactive({...})` through `shiny::bindCache(input$cohort, input$min_score, cache = "session")`
     and then `shiny::bindEvent(input$run)` (in the order required by Shiny) so that:
     - changing `input$cohort` or `input$min_score` alone does not trigger evaluation until
       `input$run` changes,
     - both `input$cohort` and `input$min_score` form the cache key, and
     - cache entries live in the **session** cache (`cache = "session"`), never the shared
       application cache (`cache = "app"`).
3. **Rendered status output:**
   - Assign `output$status <- shiny::renderText(sprintf("%s: n=%d", summary_row()$cohort, summary_row()$n_records))`.
4. **Module return value:**
   - Return `list(summary = summary_row, clicks = clicks, cache_misses = cache_misses)`.

## Function 2: `replay_cohort_requests(records, requests)`

Validate `records` and `requests`, then run a single headless `shiny::testServer()` session over
`cohort_module_server` (`args = list(records = records)`). For each row `i = 1, ..., nrow(requests)`
in order:

1. Trigger step `i` via `session$setInputs(cohort = requests$cohort[i], min_score = requests$min_score[i], run = i)`.
2. Read the current `summary()` row, `clicks()`, `cache_misses()`, and `output$status`.

Return a plain `data.frame` with one row per step (`1, ..., nrow(requests)`) and exact columns:
`step` (integer), `cohort` (character), `min_score` (numeric), `n_records` (integer),
`weighted_mean` (numeric), `clicks` (integer), `cache_misses` (integer), `status_text` (character).
Row names are `1, 2, ...`. Do not modify `records` or `requests`.

