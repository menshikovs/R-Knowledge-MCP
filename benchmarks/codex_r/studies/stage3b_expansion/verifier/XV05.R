# Hidden checks for XV05 (CSV text parsing under readr 2.2: literal data needs I(); no guessing).
# Oracle: base-R read.csv with every column read as text, then explicit conversion.

xv05_oracle <- function(text) {
  raw <- utils::read.csv(text = text, colClasses = "character", na.strings = c("", "NA"),
                         header = TRUE, stringsAsFactors = FALSE, check.names = FALSE,
                         strip.white = FALSE)
  ts <- as.POSIXct(strptime(raw$ts, "%Y-%m-%d %H:%M:%S", tz = "UTC"), tz = "UTC")
  amount <- suppressWarnings(as.numeric(raw$amount))
  bad_ts <- sum(!is.na(raw$ts) & is.na(ts))
  bad_amount <- sum(!is.na(raw$amount) & is.na(amount))
  list(data = data.frame(ts = ts, user = raw$user, amount = amount, status = raw$status,
                         stringsAsFactors = FALSE),
       n_problems = as.integer(bad_ts + bad_amount))
}

xv05_text <- function(lines) paste0(paste(lines, collapse = "\n"), "\n")

xv05_t1 <- xv05_text(c(
  "ts,user,amount,status",
  "2026-03-01 08:15:00,007,12.50,ok",
  '2026-03-01 08:20:31,"O\'Brien, A",3,ok',
  "2026-03-01 09:02:10,042,n/a,failed",
  "2026-03-02 10:00:00,,7.25,",
  "2026-02-30 10:00:00,123,1e2,ok",
  ",0001,NA,NA",
  '2026-03-04 23:59:59,9,"1,234.5",ok'
))
xv05_t2 <- xv05_text(c(
  "ts,user,amount,status",
  "2026-06-01 00:00:00,12,5,a",
  "2026-06-01 12:30:00,13,6.5,b",
  "yesterday,14,7,c"
))
xv05_t3 <- xv05_text("ts,user,amount,status")
xv05_t4 <- paste(c("ts,user,amount,status", "2026-01-05 01:02:03,0a1,0.5,ok"), collapse = "\n")

local({
  o <- xv05_oracle(xv05_t1)
  stopifnot(o$n_problems == 3L, nrow(o$data) == 7L, o$data$user[1] == "007", is.na(o$data$user[4]))
  stopifnot(xv05_oracle(xv05_t2)$n_problems == 1L, nrow(xv05_oracle(xv05_t3)$data) == 0L)
})

xv05_call <- function(text) call_wrapped("parse_events", text, .prelude = lifecycle_prelude)
xv05_same_time <- function(a, b) {
  testthat::expect_identical(is.na(a), is.na(b))
  testthat::expect_equal(as.numeric(a[!is.na(a)]), as.numeric(b[!is.na(b)]), tolerance = 1e-9)
}

check("returned_list_has_exactly_data_and_n_problems", {
  got <- value_of(xv05_call(xv05_t1))
  testthat::expect_identical(sort(names(got)), c("data", "n_problems"))
  testthat::expect_true(is.data.frame(got$data))
  testthat::expect_identical(names(got$data), c("ts", "user", "amount", "status"))
})

check("timestamps_are_utc_posixct_and_invalid_ones_are_missing", {
  for (t in list(xv05_t1, xv05_t2, xv05_t4)) {
    got <- value_of(xv05_call(t))$data
    want <- xv05_oracle(t)$data
    testthat::expect_s3_class(got$ts, "POSIXct")
    testthat::expect_identical(attr(got$ts, "tzone"), "UTC")
    xv05_same_time(got$ts, want$ts)
  }
})

check("user_ids_stay_character_with_leading_zeros", {
  got <- value_of(xv05_call(xv05_t1))$data
  testthat::expect_true(is.character(got$user))
  testthat::expect_identical(got$user, xv05_oracle(xv05_t1)$data$user)
  testthat::expect_identical(value_of(xv05_call(xv05_t4))$data$user, "0a1")
})

check("amounts_are_doubles_and_non_numbers_are_missing", {
  for (t in list(xv05_t1, xv05_t2)) {
    got <- value_of(xv05_call(t))$data
    want <- xv05_oracle(t)$data
    testthat::expect_true(is.double(got$amount))
    testthat::expect_identical(is.na(got$amount), is.na(want$amount))
    expect_close(got$amount[!is.na(got$amount)], want$amount[!is.na(want$amount)])
  }
})

check("problem_count_counts_only_present_but_unparseable_values", {
  testthat::expect_identical(value_of(xv05_call(xv05_t1))$n_problems, 3L)
  testthat::expect_identical(value_of(xv05_call(xv05_t2))$n_problems, 1L)
  testthat::expect_identical(value_of(xv05_call(xv05_t4))$n_problems, 0L)
  testthat::expect_true(is.integer(value_of(xv05_call(xv05_t1))$n_problems))
})

check("empty_and_NA_fields_are_missing_values_not_problems", {
  got <- value_of(xv05_call(xv05_t1))$data
  testthat::expect_true(is.na(got$user[4]))
  testthat::expect_true(is.na(got$status[4]))
  testthat::expect_true(is.na(got$amount[6]))
  testthat::expect_true(is.na(got$ts[6]))
})

check("quoted_fields_with_commas_are_kept_whole", {
  got <- value_of(xv05_call(xv05_t1))$data
  testthat::expect_identical(got$user[2], "O'Brien, A")
  testthat::expect_true(is.na(got$amount[7]))
})

check("rows_keep_file_order_and_status_is_character", {
  got <- value_of(xv05_call(xv05_t1))$data
  testthat::expect_identical(nrow(got), 7L)
  testthat::expect_identical(got$status, xv05_oracle(xv05_t1)$data$status)
  testthat::expect_true(is.character(got$status))
})

check("header_only_text_gives_a_typed_zero_row_data_frame", {
  got <- value_of(xv05_call(xv05_t3))
  testthat::expect_identical(nrow(got$data), 0L)
  testthat::expect_identical(names(got$data), c("ts", "user", "amount", "status"))
  testthat::expect_s3_class(got$data$ts, "POSIXct")
  testthat::expect_true(is.character(got$data$user))
  testthat::expect_true(is.double(got$data$amount))
  testthat::expect_identical(got$n_problems, 0L)
})

check("text_without_trailing_newline_is_parsed", {
  got <- value_of(xv05_call(xv05_t4))$data
  testthat::expect_identical(nrow(got), 1L)
  expect_close(got$amount, 0.5)
})

check("runs_without_warnings_or_messages_about_literal_data", {
  res <- xv05_call(xv05_t1)
  value_of(res)
  expect_no_warnings(res)
})

check("input_text_is_not_modified", {
  res <- call_wrapped("parse_events", xv05_t1, .digest = NULL)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], xv05_t1)
})
