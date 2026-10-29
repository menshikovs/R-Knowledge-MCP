# Hidden checks for XP03 (minimum R version over the hard-dependency closure).
# Oracle: closure by BFS over read.dcf() (lib.R) and numeric component comparison of R (>= x).

xp03_req <- function(pkg) {
  d <- xp_desc(pkg)
  x <- d[["Depends"]]
  if (is.null(x) || is.na(x)) return(character())
  parts <- trimws(strsplit(gsub("\\s+", " ", x), ",")[[1]])
  m <- regmatches(parts, regexec("^R\\s*\\(>=\\s*([0-9][0-9.-]*)\\s*\\)$", parts))
  vapply(Filter(length, m), function(z) z[[2]], "")
}

xp03_cmp <- function(a, b) {
  pa <- as.integer(strsplit(gsub("-", ".", a), ".", fixed = TRUE)[[1]])
  pb <- as.integer(strsplit(gsub("-", ".", b), ".", fixed = TRUE)[[1]])
  n <- max(length(pa), length(pb))
  pa <- c(pa, rep(0L, n - length(pa)))
  pb <- c(pb, rep(0L, n - length(pb)))
  for (i in seq_len(n)) if (pa[i] != pb[i]) return(if (pa[i] > pb[i]) 1L else -1L)
  0L
}

xp03_norm <- function(v) {
  p <- strsplit(gsub("-", ".", v), ".", fixed = TRUE)[[1]]
  p <- as.character(as.integer(p))
  while (length(p) < 3L) p <- c(p, "0")
  paste(p, collapse = ".")
}

xp03_oracle <- function(pkg) {
  reqs <- unlist(lapply(c(pkg, xp_closure(pkg)), function(p) if (is.null(xp_desc(p))) character() else xp03_req(p)))
  if (!length(reqs)) return(NA_character_)
  best <- reqs[[1]]
  for (r in reqs[-1]) if (xp03_cmp(r, best) > 0L) best <- r
  xp03_norm(best)
}

local({
  stopifnot(xp03_oracle("survival") != xp03_norm(xp03_req("survival")[[1]]),
            xp03_cmp("4.10", "4.9") > 0L, xp03_cmp("3.5.0", "3.5") == 0L, xp03_norm("4.1") == "4.1.0",
            xp03_norm("3.5-1") == "3.5.1")
  stopifnot(!is.na(xp03_oracle("ggplot2")), !is.na(xp03_oracle("R6")))
})

xp03_call <- function(pkg) call_wrapped("minimum_r_version", pkg)

check("matches_the_oracle_for_several_packages", {
  for (p in c("ggplot2", "tidyr", "R6", "cli", "dplyr", "readr", "purrr", "shiny")) {
    testthat::expect_identical(value_of(xp03_call(p)), xp03_oracle(p), info = p)
  }
})

check("the_requirement_of_a_dependency_can_exceed_the_packages_own", {
  got <- value_of(xp03_call("survival"))
  own <- xp03_norm(xp03_req("survival")[[1]])
  testthat::expect_identical(got, xp03_oracle("survival"))
  testthat::expect_gt(xp03_cmp(got, own), 0L)
})

check("three_component_normalised_string_result", {
  got <- value_of(xp03_call("ggplot2"))
  testthat::expect_true(is.character(got) && length(got) == 1L)
  testthat::expect_match(got, "^[0-9]+\\.[0-9]+\\.[0-9]+")
  testthat::expect_null(names(got))
})

check("base_packages_are_not_followed", {
  all <- xp_installed_packages()
  base <- all[vapply(all, xp_is_base, logical(1))]
  testthat::expect_true(length(base) >= 10L)
  got <- value_of(xp03_call("tools"))
  testthat::expect_identical(got, xp03_oracle("tools"))
})

check("a_package_with_no_requirement_anywhere_gives_na", {
  all <- xp_installed_packages()
  none <- all[vapply(all, function(p) is.na(xp03_oracle(p)), logical(1))]
  testthat::expect_true(length(none) > 0L)
  got <- value_of(xp03_call(none[[1]]))
  testthat::expect_true(is.character(got) && length(got) == 1L && is.na(got))
})

check("numeric_not_textual_comparison", {
  # The oracle's own comparator is exercised on the strings that break lexical ordering.
  testthat::expect_gt(xp03_cmp("4.10.0", "4.9.1"), 0L)
  got <- value_of(xp03_call("Matrix"))
  testthat::expect_identical(got, xp03_oracle("Matrix"))
})

check("invalid_arguments_are_errors", {
  works <- xp03_call("R6")
  expect_stops(xp03_call("notARealPackageName"), works = works)
  expect_stops(xp03_call(c("R6", "cli")), works = works)
  expect_stops(xp03_call(NA_character_), works = works)
  expect_stops(xp03_call(42), works = works)
})

check("runs_without_warnings", {
  res <- xp03_call("tidyr")
  value_of(res)
  expect_no_warnings(res)
})
