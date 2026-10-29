# Hidden checks for XP05 (numeric version requirements against installed versions).
# Oracle: component-wise integer comparison written here; installed versions come from read.dcf().

xp05_comps <- function(v) as.integer(strsplit(gsub("-", ".", v), ".", fixed = TRUE)[[1]])
xp05_cmp <- function(a, b) {
  pa <- xp05_comps(a)
  pb <- xp05_comps(b)
  n <- min(length(pa), length(pb))
  for (i in seq_len(n)) if (pa[i] != pb[i]) return(if (pa[i] > pb[i]) 1L else -1L)
  if (length(pa) == length(pb)) 0L else if (length(pa) > length(pb)) 1L else -1L
}
xp05_oracle <- function(req) {
  inst <- vapply(req$package, function(p) { d <- xp_desc(p); if (is.null(d)) NA_character_ else d[["Version"]] }, "")
  status <- vapply(seq_len(nrow(req)), function(i) {
    if (is.na(inst[[i]])) return("not_installed")
    c <- xp05_cmp(inst[[i]], req$version[[i]])
    ok <- switch(req$op[[i]], ">=" = c >= 0L, ">" = c > 0L, "<=" = c <= 0L, "<" = c < 0L, "==" = c == 0L, "!=" = c != 0L)
    if (ok) "satisfied" else "unsatisfied"
  }, "")
  data.frame(package = req$package, op = req$op, required = req$version, installed = unname(inst), status = status,
             stringsAsFactors = FALSE)
}

xp05_a <- data.frame(
  package = c("dplyr", "dplyr", "MASS", "MASS", "ggplot2", "ggplot2", "R6", "notARealPackage", "cli", "rlang", "readr", "tidyr"),
  op = c(">=", ">=", ">=", "<", "==", "!=", ">", ">=", "<=", "<", ">=", "=="),
  version = c("1.1.0", "1.10.0", "7.3-9", "7.3-100", "4.0.3", "4.0.3", "2.5.1", "1.0", "3.6.5", "1.3.0.1", "2.2", "1.3.2"),
  stringsAsFactors = FALSE
)
xp05_b <- data.frame(package = c("survival", "survival", "survival", "Matrix"), op = c("==", "==", ">", "<"),
                     version = c("3.8-3", "3.8.3", "3.8", "1.7"), stringsAsFactors = FALSE)

local({
  o <- xp05_oracle(xp05_a)
  stopifnot(o$status[2] == "unsatisfied", o$status[3] == "satisfied", o$status[8] == "not_installed")
  stopifnot(xp05_cmp("1.10.0", "1.9.0") > 0L, xp05_cmp("7.3-65", "7.3-9") > 0L)
  b <- xp05_oracle(xp05_b)
  stopifnot(b$status[1] == "satisfied", b$status[2] == "satisfied", b$status[3] == "satisfied", b$status[4] == "unsatisfied")
  stopifnot(xp05_oracle(xp05_a)$status[c(2, 3)][1] != xp05_oracle(xp05_a)$status[c(2, 3)][2])
})

xp05_call <- function(req) call_wrapped("check_requirements", req)

xp05_same <- function(got, want) {
  testthat::expect_true(is.data.frame(got))
  testthat::expect_identical(names(got), c("package", "op", "required", "installed", "status"))
  testthat::expect_identical(nrow(got), nrow(want))
  for (nm in names(want)) {
    testthat::expect_true(is.character(got[[nm]]), info = nm)
    testthat::expect_identical(unname(got[[nm]]), unname(want[[nm]]), info = nm)
  }
}

check("statuses_match_the_oracle", {
  xp05_same(as.data.frame(value_of(xp05_call(xp05_a))), xp05_oracle(xp05_a))
})

check("versions_are_compared_numerically_not_textually", {
  got <- as.data.frame(value_of(xp05_call(xp05_a)))
  testthat::expect_identical(got$status[2], "unsatisfied")
  testthat::expect_identical(got$status[3], "satisfied")
  testthat::expect_identical(got$status[4], "satisfied")
})

check("hyphen_and_dot_separators_are_equivalent", {
  got <- as.data.frame(value_of(xp05_call(xp05_b)))
  testthat::expect_identical(got$status, xp05_oracle(xp05_b)$status)
  testthat::expect_identical(got$status[1:2], c("satisfied", "satisfied"))
})

check("packages_that_are_not_installed_are_reported_not_rejected", {
  got <- as.data.frame(value_of(xp05_call(xp05_a)))
  testthat::expect_identical(got$status[8], "not_installed")
  testthat::expect_true(is.na(got$installed[8]))
})

check("rows_keep_the_input_order_and_duplicates", {
  got <- as.data.frame(value_of(xp05_call(xp05_a)))
  testthat::expect_identical(got$package, xp05_a$package)
  testthat::expect_identical(got$op, xp05_a$op)
  testthat::expect_identical(got$required, xp05_a$version)
})

check("zero_row_tables_and_extra_columns_are_accepted", {
  empty <- data.frame(package = character(), op = character(), version = character())
  got <- as.data.frame(value_of(xp05_call(empty)))
  testthat::expect_identical(names(got), c("package", "op", "required", "installed", "status"))
  testthat::expect_identical(nrow(got), 0L)
  extra <- cbind(xp05_b, note = "x", stringsAsFactors = FALSE)
  xp05_same(as.data.frame(value_of(xp05_call(extra))), xp05_oracle(xp05_b))
})

check("result_is_a_plain_data_frame_with_character_columns", {
  got <- value_of(xp05_call(xp05_a))
  testthat::expect_false(inherits(got, "tbl_df"))
  testthat::expect_false(any(vapply(got, is.factor, logical(1))))
})

check("invalid_tables_operators_and_versions_are_errors", {
  works <- xp05_call(xp05_b)
  bad_op <- transform(xp05_b, op = c("=>", ">=", ">", "<"))
  bad_ver <- transform(xp05_b, version = c("abc", "1", "1", "1"))
  bad_ver2 <- transform(xp05_b, version = c("1..2", "1", "1", "1"))
  na_ver <- transform(xp05_b, version = c(NA, "1", "1", "1"))
  expect_stops(xp05_call(bad_op), works = works)
  expect_stops(xp05_call(bad_ver), works = works)
  expect_stops(xp05_call(bad_ver2), works = works)
  expect_stops(xp05_call(na_ver), works = works)
  expect_stops(xp05_call(xp05_b[c("package", "op")]), works = works)
  expect_stops(xp05_call("dplyr >= 1.1.0"), works = works)
})

check("input_is_not_modified_and_no_warnings", {
  d <- xp05_a
  res <- xp05_call(d)
  value_of(res)
  expect_no_warnings(res)
  testthat::expect_identical(res$args_after[[1]], d)
})
