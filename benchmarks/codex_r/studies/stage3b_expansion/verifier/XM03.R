# Hidden checks for XM03 (Shiny moduleServer workflow with session-scoped bindCache/bindEvent
# pipeline, reactiveVal audit counters and headless testServer replay).
#
# Independent oracle: plain-R deterministic trace simulator that computes weighted cohort summaries
# and tracks unique (cohort, min_score) keys seen so far without using shiny or cachem.

suppressPackageStartupMessages(library(shiny))

xm03_make_records <- function(seed) {
  with_seed(seed, {
    cohorts <- rep(c("alpha", "beta", "gamma"), c(15L, 14L, 13L))
    n <- length(cohorts)
    data.frame(
      record_id = sprintf("R%03d", seq_len(n)),
      cohort = cohorts,
      score = round(stats::runif(n, 15, 90), 3),
      weight = round(stats::runif(n, 0.4, 4.0), 3),
      stringsAsFactors = FALSE
    )[sample.int(n), , drop = FALSE]
  })
}

xm03_oracle_row <- function(records, cohort, min_score) {
  sub <- records[records$cohort == cohort & records$score >= min_score, , drop = FALSE]
  n_rec <- nrow(sub)
  w_mean <- if (n_rec == 0L) NA_real_ else sum(sub$score * sub$weight) / sum(sub$weight)
  data.frame(
    cohort = as.character(cohort),
    min_score = as.numeric(min_score),
    n_records = as.integer(n_rec),
    weighted_mean = as.numeric(w_mean),
    stringsAsFactors = FALSE
  )
}

xm03_oracle_replay <- function(records, requests) {
  seen <- character(0)
  misses <- 0L
  rows <- lapply(seq_len(nrow(requests)), function(i) {
    coh <- as.character(requests$cohort[i])
    ms <- as.numeric(requests$min_score[i])
    key <- paste0(coh, "\r", format(ms, digits = 16))
    if (!(key %in% seen)) {
      seen <<- c(seen, key)
      misses <<- misses + 1L
    }
    r <- xm03_oracle_row(records, coh, ms)
    data.frame(
      step = as.integer(i),
      cohort = r$cohort,
      min_score = r$min_score,
      n_records = r$n_records,
      weighted_mean = r$weighted_mean,
      clicks = as.integer(i),
      cache_misses = as.integer(misses),
      status_text = sprintf("%s: n=%d", r$cohort, r$n_records),
      stringsAsFactors = FALSE
    )
  })
  out <- do.call(rbind, rows)
  rownames(out) <- NULL
  out
}

xm03_records <- xm03_make_records(951L)
xm03_requests <- data.frame(
  cohort = c("alpha", "beta", "alpha", "alpha", "gamma", "beta", "gamma"),
  min_score = c(40, 50, 40, 65, 99, 50, 99),
  stringsAsFactors = FALSE
)
xm03_want <- xm03_oracle_replay(xm03_records, xm03_requests)

local({
  # Steps 1, 2, 4, 5 are new (cohort, min_score) pairs; steps 3, 6, 7 are cache hits
  stopifnot(identical(xm03_want$clicks, 1:7))
  stopifnot(identical(xm03_want$cache_misses, c(1L, 2L, 2L, 3L, 4L, 4L, 4L)))
  stopifnot(xm03_want$n_records[5] == 0L, is.na(xm03_want$weighted_mean[5]))
  stopifnot(all(xm03_want$n_records[c(1, 2, 4)] > 0L))
})

xm03_same_trace <- function(got, want) {
  testthat::expect_true(is.data.frame(got))
  testthat::expect_false(inherits(got, "tbl_df"))
  cols <- c("step", "cohort", "min_score", "n_records", "weighted_mean", "clicks", "cache_misses", "status_text")
  testthat::expect_identical(names(got), cols)
  testthat::expect_identical(nrow(got), nrow(want))
  testthat::expect_identical(rownames(got), as.character(seq_len(nrow(want))))
  for (nm in c("step", "n_records", "clicks", "cache_misses")) {
    testthat::expect_identical(as.integer(got[[nm]]), want[[nm]], info = nm)
  }
  for (nm in c("cohort", "status_text")) {
    testthat::expect_identical(as.character(got[[nm]]), want[[nm]], info = nm)
  }
  expect_close(got$min_score, want$min_score, tol = 1e-8, info = "min_score")
  na_want <- is.na(want$weighted_mean)
  testthat::expect_identical(is.na(got$weighted_mean), na_want)
  expect_close(got$weighted_mean[!na_want], want$weighted_mean[!na_want], tol = 1e-6, info = "weighted_mean")
}

check("replay_cohort_requests_matches_expected_summaries_hits_and_misses", {
  got <- value_of(call_wrapped("replay_cohort_requests", xm03_records, xm03_requests))
  xm03_same_trace(got, xm03_want)
})

xm03_probe_module <- function(records, mode) {
  fn <- function(records, mode) {
    mod <- get("cohort_module_server", envir = globalenv(), mode = "function")
    box <- new.env(parent = emptyenv())
    if (identical(mode, "event_and_status")) {
      shiny::testServer(mod, args = list(records = records), {
        session$setInputs(cohort = "alpha", min_score = 40, run = 1L)
        box$s1 <- session$returned$summary()
        box$c1 <- session$returned$clicks()
        box$m1 <- session$returned$cache_misses()
        box$o1 <- output$status
        session$setInputs(cohort = "beta", min_score = 70)
        box$s_wait <- session$returned$summary()
        box$c_wait <- session$returned$clicks()
        box$m_wait <- session$returned$cache_misses()
        session$setInputs(run = 2L)
        box$s2 <- session$returned$summary()
        box$c2 <- session$returned$clicks()
        box$m2 <- session$returned$cache_misses()
        box$o2 <- output$status
      })
    } else if (identical(mode, "cache_scope")) {
      shiny::testServer(mod, args = list(records = records), {
        session$setInputs(cohort = "alpha", min_score = 40, run = 1L)
        session$returned$summary()
        box$sess_keys <- length(session$cache$keys())
        box$app_keys <- length(session$appcache$keys())
      })
    } else if (identical(mode, "cache_key")) {
      shiny::testServer(mod, args = list(records = records), {
        session$setInputs(cohort = "alpha", min_score = 30, run = 1L)
        box$r1 <- session$returned$summary()
        session$setInputs(cohort = "alpha", min_score = 75, run = 2L)
        box$r2 <- session$returned$summary()
        box$m_after_diff_score <- session$returned$cache_misses()
        session$setInputs(cohort = "alpha", min_score = 30, run = 3L)
        box$r3 <- session$returned$summary()
        box$m_after_repeat <- session$returned$cache_misses()
        box$clicks_total <- session$returned$clicks()
      })
    }
    as.list(box)
  }
  environment(fn) <- globalenv()
  value_of(call_candidate(fn, records, mode))
}

check("module_server_only_evaluates_on_run_and_updates_status_output", {
  box <- xm03_probe_module(xm03_records, "event_and_status")
  want1 <- xm03_oracle_row(xm03_records, "alpha", 40)
  want2 <- xm03_oracle_row(xm03_records, "beta", 70)
  expect_close(box$s1$weighted_mean, want1$weighted_mean, tol = 1e-6)
  testthat::expect_identical(box$s_wait$cohort, "alpha")
  testthat::expect_identical(as.integer(c(box$c1, box$m1, box$c_wait, box$m_wait, box$c2, box$m2)), c(1L, 1L, 1L, 1L, 2L, 2L))
  testthat::expect_identical(as.character(box$o1), sprintf("alpha: n=%d", want1$n_records))
  testthat::expect_identical(as.character(box$o2), sprintf("beta: n=%d", want2$n_records))
})

check("cache_is_scoped_to_session_not_application", {
  box <- xm03_probe_module(xm03_records, "cache_scope")
  testthat::expect_true(box$sess_keys >= 1L)
  testthat::expect_identical(box$app_keys, 0L)
})

check("cache_key_includes_both_cohort_and_min_score", {
  box <- xm03_probe_module(xm03_records, "cache_key")
  testthat::expect_true(box$r1$n_records > box$r2$n_records)
  testthat::expect_identical(as.integer(box$m_after_diff_score), 2L)
  testthat::expect_identical(as.integer(box$m_after_repeat), 2L)
  testthat::expect_identical(as.integer(box$clicks_total), 3L)
  expect_close(box$r3$weighted_mean, box$r1$weighted_mean, tol = 1e-8)
})

check("empty_matching_subset_returns_zero_records_and_na_weighted_mean", {
  req_empty <- data.frame(cohort = c("gamma", "gamma"), min_score = c(999, 999), stringsAsFactors = FALSE)
  got <- value_of(call_wrapped("replay_cohort_requests", xm03_records, req_empty))
  testthat::expect_identical(as.integer(got$n_records), c(0L, 0L))
  testthat::expect_true(all(is.na(got$weighted_mean)))
  testthat::expect_identical(as.integer(got$clicks), c(1L, 2L))
  testthat::expect_identical(as.integer(got$cache_misses), c(1L, 1L))
  testthat::expect_identical(as.character(got$status_text), c("gamma: n=0", "gamma: n=0"))
})

check("invalid_records_stop_with_an_error_in_both_functions", {
  works <- call_wrapped("replay_cohort_requests", xm03_records, xm03_requests[1:2, , drop = FALSE])
  dup <- xm03_records
  dup$record_id[2] <- dup$record_id[1]
  expect_stops(call_wrapped("cohort_module_server", "m", dup), works = works)
  expect_stops(call_wrapped("replay_cohort_requests", dup, xm03_requests), works = works)

  bad_w <- xm03_records
  bad_w$weight[1] <- 0
  expect_stops(call_wrapped("cohort_module_server", "m", bad_w), works = works)
  expect_stops(call_wrapped("replay_cohort_requests", bad_w, xm03_requests), works = works)

  na_rec <- xm03_records
  na_rec$score[3] <- NA_real_
  expect_stops(call_wrapped("replay_cohort_requests", na_rec, xm03_requests), works = works)
})

check("invalid_requests_stop_with_an_error", {
  works <- call_wrapped("replay_cohort_requests", xm03_records, xm03_requests[1:2, , drop = FALSE])
  bad_coh <- data.frame(cohort = "nonexistent", min_score = 20, stringsAsFactors = FALSE)
  expect_stops(call_wrapped("replay_cohort_requests", xm03_records, bad_coh), works = works)
  empty_req <- xm03_requests[0, , drop = FALSE]
  expect_stops(call_wrapped("replay_cohort_requests", xm03_records, empty_req), works = works)
  na_req <- xm03_requests[1:2, , drop = FALSE]
  na_req$min_score[1] <- NA_real_
  expect_stops(call_wrapped("replay_cohort_requests", xm03_records, na_req), works = works)
})

check("inputs_are_not_modified_and_no_warnings", {
  rec <- xm03_records
  req <- xm03_requests
  res <- call_wrapped("replay_cohort_requests", rec, req)
  value_of(res)
  expect_no_warnings(res)
  testthat::expect_identical(res$args_after[[1]], rec)
  testthat::expect_identical(res$args_after[[2]], req)
})

