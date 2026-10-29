# Hidden checks for XP02 (direct reverse dependencies among installed packages).
# Oracle: scan every installed DESCRIPTION with read.dcf() (lib.R, xp_*).

xp02_oracle <- function(pkg, types = xp_hard) {
  all <- xp_installed_packages()
  hit <- vapply(all, function(p) pkg %in% xp_direct(p, types), logical(1))
  setdiff(all[hit], pkg)
}

local({
  stopifnot("clipr" %in% xp_installed_packages(), "cli" %in% xp_installed_packages())
  stopifnot(!("clipr" %in% xp02_oracle("cli")), "readr" %in% xp02_oracle("cli"), "readr" %in% xp02_oracle("clipr"))
  stopifnot(length(xp02_oracle("rlang")) > 20, length(xp02_oracle("stats")) > 20, length(xp02_oracle("R6")) > 3)
  stopifnot(length(xp02_oracle("testthat", "Suggests")) > 0L, !identical(xp02_oracle("testthat", "Suggests"), xp02_oracle("testthat")))
})

xp02_call <- function(pkg, ...) call_wrapped("reverse_dependencies", pkg, ...)

check("default_fields_match_the_oracle_for_several_packages", {
  for (p in c("rlang", "cli", "clipr", "R6", "vctrs", "cpp11", "stats")) {
    testthat::expect_identical(value_of(xp02_call(p)), xp02_oracle(p), info = p)
  }
})

check("whole_name_matching_does_not_confuse_prefixes", {
  got <- value_of(xp02_call("cli"))
  testthat::expect_false("clipr" %in% got)
  testthat::expect_true("readr" %in% got)
  testthat::expect_identical(got, xp02_oracle("cli"))
})

check("linkingto_is_a_default_field", {
  got <- value_of(xp02_call("cpp11"))
  testthat::expect_true(all(c("readr", "tidyr") %in% got))
})

check("only_direct_declarations_count", {
  got <- value_of(xp02_call("cpp11"))
  testthat::expect_false("ggplot2" %in% got)
})

check("other_field_sets_are_honoured", {
  testthat::expect_identical(value_of(xp02_call("testthat", "Suggests")), xp02_oracle("testthat", "Suggests"))
  testthat::expect_identical(value_of(xp02_call("rlang", c("Depends", "Imports"))), xp02_oracle("rlang", c("Depends", "Imports")))
  testthat::expect_identical(value_of(xp02_call("cpp11", "Imports")), xp02_oracle("cpp11", "Imports"))
})

check("packages_that_ship_with_r_are_searched_too", {
  got <- value_of(xp02_call("stats"))
  testthat::expect_true("stats4" %in% got || "splines" %in% got || "tools" %in% got || "ggplot2" %in% got)
  testthat::expect_identical(got, xp02_oracle("stats"))
})

check("package_itself_is_never_listed_and_result_is_sorted_unique_unnamed", {
  got <- value_of(xp02_call("rlang"))
  testthat::expect_false("rlang" %in% got)
  testthat::expect_identical(got, sort(unique(got), method = "radix"))
  testthat::expect_null(names(got))
})

check("no_reverse_dependencies_gives_an_empty_character_vector", {
  all <- xp_installed_packages()
  none <- all[vapply(all, function(p) length(xp02_oracle(p)) == 0L, logical(1))]
  testthat::expect_true(length(none) > 0L)
  got <- value_of(xp02_call(none[[1]]))
  testthat::expect_identical(got, character(0))
})

check("invalid_arguments_are_errors", {
  works <- xp02_call("cli")
  expect_stops(xp02_call("notARealPackageName"), works = works)
  expect_stops(xp02_call(c("cli", "R6")), works = works)
  expect_stops(xp02_call("cli", "Import"), works = works)
  expect_stops(xp02_call("cli", character()), works = works)
  expect_stops(xp02_call(NA_character_), works = works)
})

check("runs_without_warnings", {
  res <- xp02_call("rlang")
  value_of(res)
  expect_no_warnings(res)
})
