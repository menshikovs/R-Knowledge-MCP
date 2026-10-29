#### control: reference
# Trusted reference: moduleServer with bindCache(cache = "session") |> bindEvent(input$run) and testServer replay.
xm03_validate_records <- function(records) {
  if (!is.data.frame(records) || nrow(records) < 1L) stop("records must be a non-empty data.frame")
  req <- c("record_id", "cohort", "score", "weight")
  if (!all(req %in% names(records))) stop("missing required columns in records")
  if (anyNA(records[, req]) || anyDuplicated(records$record_id)) stop("missing values or duplicate record_id")
  if (!is.character(records$cohort) || !is.numeric(records$score) || !is.numeric(records$weight) || any(records$weight <= 0)) {
    stop("invalid column types or non-positive weights")
  }
}

cohort_module_server <- function(id, records) {
  suppressPackageStartupMessages(library(shiny))
  xm03_validate_records(records)
  moduleServer(id, function(input, output, session) {
    clicks <- reactiveVal(0L)
    cache_misses <- reactiveVal(0L)
    observeEvent(input$run, {
      clicks(clicks() + 1L)
    })
    summary_row <- reactive({
      cache_misses(cache_misses() + 1L)
      sub <- records[records$cohort == input$cohort & records$score >= input$min_score, , drop = FALSE]
      n_rec <- nrow(sub)
      wm <- if (n_rec == 0L) NA_real_ else sum(sub$score * sub$weight) / sum(sub$weight)
      data.frame(
        cohort = as.character(input$cohort),
        min_score = as.numeric(input$min_score),
        n_records = as.integer(n_rec),
        weighted_mean = as.numeric(wm),
        stringsAsFactors = FALSE
      )
    }) |>
      bindCache(input$cohort, input$min_score, cache = "session") |>
      bindEvent(input$run)

    output$status <- renderText({
      s <- summary_row()
      sprintf("%s: n=%d", s$cohort, s$n_records)
    })
    list(summary = summary_row, clicks = clicks, cache_misses = cache_misses)
  })
}

replay_cohort_requests <- function(records, requests) {
  suppressPackageStartupMessages(library(shiny))
  xm03_validate_records(records)
  if (!is.data.frame(requests) || nrow(requests) < 1L || !all(c("cohort", "min_score") %in% names(requests))) {
    stop("requests must be a non-empty data.frame with cohort and min_score")
  }
  if (anyNA(requests[, c("cohort", "min_score")]) || !is.character(requests$cohort) || !is.numeric(requests$min_score)) {
    stop("invalid requests columns")
  }
  if (!all(requests$cohort %in% records$cohort)) stop("unknown cohort in requests")

  holder <- new.env(parent = emptyenv())
  testServer(cohort_module_server, args = list(records = records), {
    rows <- vector("list", nrow(requests))
    for (i in seq_len(nrow(requests))) {
      session$setInputs(cohort = requests$cohort[i], min_score = requests$min_score[i], run = i)
      s <- session$returned$summary()
      rows[[i]] <- data.frame(
        step = as.integer(i),
        cohort = as.character(s$cohort),
        min_score = as.numeric(s$min_score),
        n_records = as.integer(s$n_records),
        weighted_mean = as.numeric(s$weighted_mean),
        clicks = as.integer(session$returned$clicks()),
        cache_misses = as.integer(session$returned$cache_misses()),
        status_text = as.character(output$status),
        stringsAsFactors = FALSE
      )
    }
    holder$out <- do.call(rbind, rows)
  })
  rownames(holder$out) <- NULL
  holder$out
}

#### control: alternate_explicit_session_cache_object
# Alternate valid solution: passes cache = session$cache explicitly to bindCache and uses weighted.mean().
cohort_module_server <- function(id, records) {
  suppressPackageStartupMessages(library(shiny))
  stopifnot(is.data.frame(records), nrow(records) >= 1L,
            all(c("record_id", "cohort", "score", "weight") %in% names(records)),
            !anyNA(records[, c("record_id", "cohort", "score", "weight")]),
            !anyDuplicated(records$record_id), is.character(records$cohort),
            is.numeric(records$score), is.numeric(records$weight), all(records$weight > 0))
  moduleServer(id, function(input, output, session) {
    clicks <- reactiveVal(0L)
    cache_misses <- reactiveVal(0L)
    observeEvent(input$run, clicks(clicks() + 1L))
    summary_row <- bindEvent(
      bindCache(
        reactive({
          cache_misses(cache_misses() + 1L)
          keep <- which(records$cohort == input$cohort & records$score >= input$min_score)
          n_rec <- length(keep)
          wm <- if (n_rec == 0L) NA_real_ else stats::weighted.mean(records$score[keep], records$weight[keep])
          data.frame(cohort = as.character(input$cohort), min_score = as.numeric(input$min_score),
                     n_records = as.integer(n_rec), weighted_mean = as.numeric(wm), stringsAsFactors = FALSE)
        }),
        input$cohort, input$min_score,
        cache = session$cache
      ),
      input$run
    )
    output$status <- renderText(paste0(summary_row()$cohort, ": n=", summary_row()$n_records))
    list(summary = summary_row, clicks = clicks, cache_misses = cache_misses)
  })
}

replay_cohort_requests <- function(records, requests) {
  suppressPackageStartupMessages(library(shiny))
  stopifnot(is.data.frame(records), nrow(records) >= 1L,
            all(c("record_id", "cohort", "score", "weight") %in% names(records)),
            !anyNA(records[, c("record_id", "cohort", "score", "weight")]),
            !anyDuplicated(records$record_id), is.character(records$cohort),
            is.numeric(records$score), is.numeric(records$weight), all(records$weight > 0),
            is.data.frame(requests), nrow(requests) >= 1L,
            all(c("cohort", "min_score") %in% names(requests)),
            !anyNA(requests[, c("cohort", "min_score")]),
            is.character(requests$cohort), is.numeric(requests$min_score),
            all(requests$cohort %in% records$cohort))
  env <- new.env(parent = emptyenv())
  testServer(cohort_module_server, args = list(records = records), {
    env$res <- do.call(rbind, lapply(seq_len(nrow(requests)), function(i) {
      session$setInputs(cohort = requests$cohort[i], min_score = requests$min_score[i], run = i)
      sr <- session$returned$summary()
      data.frame(step = i, cohort = sr$cohort, min_score = sr$min_score, n_records = sr$n_records,
                 weighted_mean = sr$weighted_mean, clicks = session$returned$clicks(),
                 cache_misses = session$returned$cache_misses(), status_text = as.character(output$status),
                 stringsAsFactors = FALSE)
    }))
  })
  rownames(env$res) <- NULL
  env$res
}

#### control: wrong_app_scoped_cache
# Plausible wrong strategy: leaves bindCache() at its default cache = "app" instead of scoping to the session.
cohort_module_server <- function(id, records) {
  suppressPackageStartupMessages(library(shiny))
  stopifnot(is.data.frame(records), nrow(records) >= 1L,
            all(c("record_id", "cohort", "score", "weight") %in% names(records)),
            !anyNA(records[, c("record_id", "cohort", "score", "weight")]),
            !anyDuplicated(records$record_id), is.character(records$cohort),
            is.numeric(records$score), is.numeric(records$weight), all(records$weight > 0))
  moduleServer(id, function(input, output, session) {
    clicks <- reactiveVal(0L)
    cache_misses <- reactiveVal(0L)
    observeEvent(input$run, clicks(clicks() + 1L))
    summary_row <- reactive({
      cache_misses(cache_misses() + 1L)
      sub <- records[records$cohort == input$cohort & records$score >= input$min_score, , drop = FALSE]
      n_rec <- nrow(sub)
      wm <- if (n_rec == 0L) NA_real_ else sum(sub$score * sub$weight) / sum(sub$weight)
      data.frame(cohort = as.character(input$cohort), min_score = as.numeric(input$min_score),
                 n_records = as.integer(n_rec), weighted_mean = as.numeric(wm), stringsAsFactors = FALSE)
    }) |>
      bindCache(input$cohort, input$min_score) |>
      bindEvent(input$run)
    output$status <- renderText(sprintf("%s: n=%d", summary_row()$cohort, summary_row()$n_records))
    list(summary = summary_row, clicks = clicks, cache_misses = cache_misses)
  })
}

replay_cohort_requests <- function(records, requests) {
  suppressPackageStartupMessages(library(shiny))
  stopifnot(is.data.frame(requests), nrow(requests) >= 1L,
            all(c("cohort", "min_score") %in% names(requests)),
            !anyNA(requests[, c("cohort", "min_score")]),
            is.character(requests$cohort), is.numeric(requests$min_score),
            all(requests$cohort %in% records$cohort))
  env <- new.env(parent = emptyenv())
  testServer(cohort_module_server, args = list(records = records), {
    env$res <- do.call(rbind, lapply(seq_len(nrow(requests)), function(i) {
      session$setInputs(cohort = requests$cohort[i], min_score = requests$min_score[i], run = i)
      sr <- session$returned$summary()
      data.frame(step = i, cohort = sr$cohort, min_score = sr$min_score, n_records = sr$n_records,
                 weighted_mean = sr$weighted_mean, clicks = session$returned$clicks(),
                 cache_misses = session$returned$cache_misses(), status_text = as.character(output$status),
                 stringsAsFactors = FALSE)
    }))
  })
  rownames(env$res) <- NULL
  env$res
}

#### control: wrong_incomplete_cache_key
# Plausible wrong strategy: caches only on input$cohort and forgets input$min_score in bindCache().
cohort_module_server <- function(id, records) {
  suppressPackageStartupMessages(library(shiny))
  stopifnot(is.data.frame(records), nrow(records) >= 1L,
            all(c("record_id", "cohort", "score", "weight") %in% names(records)),
            !anyNA(records[, c("record_id", "cohort", "score", "weight")]),
            !anyDuplicated(records$record_id), is.character(records$cohort),
            is.numeric(records$score), is.numeric(records$weight), all(records$weight > 0))
  moduleServer(id, function(input, output, session) {
    clicks <- reactiveVal(0L)
    cache_misses <- reactiveVal(0L)
    observeEvent(input$run, clicks(clicks() + 1L))
    summary_row <- reactive({
      cache_misses(cache_misses() + 1L)
      sub <- records[records$cohort == input$cohort & records$score >= input$min_score, , drop = FALSE]
      n_rec <- nrow(sub)
      wm <- if (n_rec == 0L) NA_real_ else sum(sub$score * sub$weight) / sum(sub$weight)
      data.frame(cohort = as.character(input$cohort), min_score = as.numeric(input$min_score),
                 n_records = as.integer(n_rec), weighted_mean = as.numeric(wm), stringsAsFactors = FALSE)
    }) |>
      bindCache(input$cohort, cache = "session") |>
      bindEvent(input$run)
    output$status <- renderText(sprintf("%s: n=%d", summary_row()$cohort, summary_row()$n_records))
    list(summary = summary_row, clicks = clicks, cache_misses = cache_misses)
  })
}

replay_cohort_requests <- function(records, requests) {
  suppressPackageStartupMessages(library(shiny))
  stopifnot(is.data.frame(requests), nrow(requests) >= 1L,
            all(c("cohort", "min_score") %in% names(requests)),
            !anyNA(requests[, c("cohort", "min_score")]),
            is.character(requests$cohort), is.numeric(requests$min_score),
            all(requests$cohort %in% records$cohort))
  env <- new.env(parent = emptyenv())
  testServer(cohort_module_server, args = list(records = records), {
    env$res <- do.call(rbind, lapply(seq_len(nrow(requests)), function(i) {
      session$setInputs(cohort = requests$cohort[i], min_score = requests$min_score[i], run = i)
      sr <- session$returned$summary()
      data.frame(step = i, cohort = sr$cohort, min_score = sr$min_score, n_records = sr$n_records,
                 weighted_mean = sr$weighted_mean, clicks = session$returned$clicks(),
                 cache_misses = session$returned$cache_misses(), status_text = as.character(output$status),
                 stringsAsFactors = FALSE)
    }))
  })
  rownames(env$res) <- NULL
  env$res
}

#### control: wrong_no_bind_event_eager_reactive
# Plausible wrong strategy: uses bindCache() without bindEvent(input$run), so changing inputs updates eagerly.
cohort_module_server <- function(id, records) {
  suppressPackageStartupMessages(library(shiny))
  stopifnot(is.data.frame(records), nrow(records) >= 1L,
            all(c("record_id", "cohort", "score", "weight") %in% names(records)),
            !anyNA(records[, c("record_id", "cohort", "score", "weight")]),
            !anyDuplicated(records$record_id), is.character(records$cohort),
            is.numeric(records$score), is.numeric(records$weight), all(records$weight > 0))
  moduleServer(id, function(input, output, session) {
    clicks <- reactiveVal(0L)
    cache_misses <- reactiveVal(0L)
    observeEvent(input$run, clicks(clicks() + 1L))
    summary_row <- reactive({
      cache_misses(cache_misses() + 1L)
      sub <- records[records$cohort == input$cohort & records$score >= input$min_score, , drop = FALSE]
      n_rec <- nrow(sub)
      wm <- if (n_rec == 0L) NA_real_ else sum(sub$score * sub$weight) / sum(sub$weight)
      data.frame(cohort = as.character(input$cohort), min_score = as.numeric(input$min_score),
                 n_records = as.integer(n_rec), weighted_mean = as.numeric(wm), stringsAsFactors = FALSE)
    }) |>
      bindCache(input$cohort, input$min_score, cache = "session")
    output$status <- renderText(sprintf("%s: n=%d", summary_row()$cohort, summary_row()$n_records))
    list(summary = summary_row, clicks = clicks, cache_misses = cache_misses)
  })
}

replay_cohort_requests <- function(records, requests) {
  suppressPackageStartupMessages(library(shiny))
  stopifnot(is.data.frame(requests), nrow(requests) >= 1L,
            all(c("cohort", "min_score") %in% names(requests)),
            !anyNA(requests[, c("cohort", "min_score")]),
            is.character(requests$cohort), is.numeric(requests$min_score),
            all(requests$cohort %in% records$cohort))
  env <- new.env(parent = emptyenv())
  testServer(cohort_module_server, args = list(records = records), {
    env$res <- do.call(rbind, lapply(seq_len(nrow(requests)), function(i) {
      session$setInputs(cohort = requests$cohort[i], min_score = requests$min_score[i], run = i)
      sr <- session$returned$summary()
      data.frame(step = i, cohort = sr$cohort, min_score = sr$min_score, n_records = sr$n_records,
                 weighted_mean = sr$weighted_mean, clicks = session$returned$clicks(),
                 cache_misses = session$returned$cache_misses(), status_text = as.character(output$status),
                 stringsAsFactors = FALSE)
    }))
  })
  rownames(env$res) <- NULL
  env$res
}

#### control: edge_no_input_validation
# Boundary case: skips validation of records and requests.
# expect: fail
cohort_module_server <- function(id, records) {
  suppressPackageStartupMessages(library(shiny))
  moduleServer(id, function(input, output, session) {
    clicks <- reactiveVal(0L)
    cache_misses <- reactiveVal(0L)
    observeEvent(input$run, clicks(clicks() + 1L))
    summary_row <- reactive({
      cache_misses(cache_misses() + 1L)
      sub <- records[records$cohort == input$cohort & records$score >= input$min_score, , drop = FALSE]
      n_rec <- nrow(sub)
      wm <- if (n_rec == 0L) NA_real_ else sum(sub$score * sub$weight) / sum(sub$weight)
      data.frame(cohort = as.character(input$cohort), min_score = as.numeric(input$min_score),
                 n_records = as.integer(n_rec), weighted_mean = as.numeric(wm), stringsAsFactors = FALSE)
    }) |>
      bindCache(input$cohort, input$min_score, cache = "session") |>
      bindEvent(input$run)
    output$status <- renderText(sprintf("%s: n=%d", summary_row()$cohort, summary_row()$n_records))
    list(summary = summary_row, clicks = clicks, cache_misses = cache_misses)
  })
}

replay_cohort_requests <- function(records, requests) {
  suppressPackageStartupMessages(library(shiny))
  env <- new.env(parent = emptyenv())
  testServer(cohort_module_server, args = list(records = records), {
    env$res <- do.call(rbind, lapply(seq_len(nrow(requests)), function(i) {
      session$setInputs(cohort = requests$cohort[i], min_score = requests$min_score[i], run = i)
      sr <- session$returned$summary()
      data.frame(step = i, cohort = sr$cohort, min_score = sr$min_score, n_records = sr$n_records,
                 weighted_mean = sr$weighted_mean, clicks = session$returned$clicks(),
                 cache_misses = session$returned$cache_misses(), status_text = as.character(output$status),
                 stringsAsFactors = FALSE)
    }))
  })
  rownames(env$res) <- NULL
  env$res
}

#### control: malformed_missing_replay_function
# Malformed submission: defines cohort_module_server as a stub and omits replay_cohort_requests logic.
# expect: fail
cohort_module_server <- function(id, records) NULL
replay_cohort_requests <- function(records, requests) list()

