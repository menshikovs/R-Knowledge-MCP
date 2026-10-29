#### control: reference
# Trusted reference: readr with I() for literal data, every column read as text, explicit conversion.
parse_events <- function(text) {
  raw <- readr::read_csv(I(text), col_types = readr::cols(.default = readr::col_character()),
                         na = c("", "NA"), progress = FALSE, show_col_types = FALSE)
  ts <- as.POSIXct(strptime(raw$ts, "%Y-%m-%d %H:%M:%S", tz = "UTC"), tz = "UTC")
  amount <- suppressWarnings(as.numeric(raw$amount))
  list(
    data = data.frame(ts = ts, user = raw$user, amount = amount, status = raw$status,
                      stringsAsFactors = FALSE),
    n_problems = as.integer(sum(!is.na(raw$ts) & is.na(ts)) + sum(!is.na(raw$amount) & is.na(amount)))
  )
}

#### control: alternate_base_r_read_csv
# Alternate valid solution: base R only.
parse_events <- function(text) {
  raw <- utils::read.csv(text = text, colClasses = "character", na.strings = c("", "NA"),
                         stringsAsFactors = FALSE)
  ts <- as.POSIXct(raw$ts, format = "%Y-%m-%d %H:%M:%S", tz = "UTC")
  amount <- suppressWarnings(as.numeric(raw$amount))
  list(
    data = data.frame(ts = ts, user = raw$user, amount = amount, status = raw$status),
    n_problems = sum(!is.na(raw$ts) & is.na(ts)) + sum(!is.na(raw$amount) & is.na(amount))
  )
}

#### control: wrong_literal_data_without_I
# Plausible wrong strategy from older tutorials: read_csv(text) with literal data and guessed types.
parse_events <- function(text) {
  d <- readr::read_csv(text, show_col_types = FALSE, progress = FALSE)
  list(data = as.data.frame(d[c("ts", "user", "amount", "status")]), n_problems = nrow(readr::problems(d)))
}

#### control: wrong_guessed_user_type
# Plausible wrong strategy: I() is used, but column types are guessed so ids lose leading zeros.
parse_events <- function(text) {
  d <- readr::read_csv(I(text), show_col_types = FALSE, progress = FALSE, na = c("", "NA"))
  d <- as.data.frame(d)
  list(data = d[c("ts", "user", "amount", "status")], n_problems = 0L)
}

#### control: wrong_problem_count_includes_missing
# Plausible wrong strategy: every NA after parsing is counted as a problem.
parse_events <- function(text) {
  raw <- utils::read.csv(text = text, colClasses = "character", na.strings = c("", "NA"))
  ts <- as.POSIXct(raw$ts, format = "%Y-%m-%d %H:%M:%S", tz = "UTC")
  amount <- suppressWarnings(as.numeric(raw$amount))
  list(data = data.frame(ts = ts, user = raw$user, amount = amount, status = raw$status),
       n_problems = sum(is.na(ts)) + sum(is.na(amount)))
}

#### control: wrong_local_timezone
# Plausible wrong strategy: timestamps parsed in the session's local time zone.
parse_events <- function(text) {
  raw <- utils::read.csv(text = text, colClasses = "character", na.strings = c("", "NA"))
  ts <- as.POSIXct(raw$ts, format = "%Y-%m-%d %H:%M:%S", tz = "America/New_York")
  amount <- suppressWarnings(as.numeric(raw$amount))
  list(data = data.frame(ts = ts, user = raw$user, amount = amount, status = raw$status),
       n_problems = sum(!is.na(raw$ts) & is.na(ts)) + sum(!is.na(raw$amount) & is.na(amount)))
}

#### control: edge_header_only_drops_types
# Boundary case: right on non-empty input, but a header-only text loses the column types (expected: fail).
# expect: fail
parse_events <- function(text) {
  raw <- utils::read.csv(text = text, colClasses = "character", na.strings = c("", "NA"))
  ts <- as.POSIXct(raw$ts, format = "%Y-%m-%d %H:%M:%S", tz = "UTC")
  amount <- suppressWarnings(as.numeric(raw$amount))
  out <- list(data = data.frame(ts = ts, user = raw$user, amount = amount, status = raw$status),
              n_problems = sum(!is.na(raw$ts) & is.na(ts)) + sum(!is.na(raw$amount) & is.na(amount)))
  if (nrow(out$data) == 0L) out$data <- data.frame()
  out
}

#### control: malformed_returns_data_frame_only
# Malformed submission: returns the data frame instead of the list.
# expect: fail
parse_events <- function(text) utils::read.csv(text = text)

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
parse_events <- function(text) NULL
