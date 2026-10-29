# Hidden checks for XP01 (transitive dependency closure from installed DESCRIPTION files).
# Oracle: breadth-first search over read.dcf() of the installed DESCRIPTION files (lib.R, xp_*).

local({
  stopifnot(length(xp_closure("ggplot2")) > 10, !("stats" %in% xp_closure("ggplot2")),
            length(xp_closure("R6")) == 0L, "Matrix" %in% xp_closure("survival"),
            "cpp11" %in% xp_closure("readr"), !("tzdb" %in% xp_closure("R6")))
  stopifnot(length(setdiff(xp_closure("tidyr", "Imports"), xp_closure("tidyr"))) == 0L,
            length(xp_closure("tidyr")) > length(xp_closure("tidyr", "Depends")))
})

xp01_call <- function(pkg, ...) call_wrapped("dependency_closure", pkg, ...)

check("default_closure_matches_the_oracle_for_several_packages", {
  for (p in c("ggplot2", "tidyr", "dplyr", "readr", "survival", "shiny")) {
    testthat::expect_identical(value_of(xp01_call(p)), xp_closure(p), info = p)
  }
})

check("a_package_without_dependencies_gives_an_empty_character_vector", {
  got <- value_of(xp01_call("R6"))
  testthat::expect_identical(got, character(0))
})

check("base_packages_r_and_the_package_itself_are_excluded", {
  got <- value_of(xp01_call("ggplot2"))
  testthat::expect_false(any(c("R", "stats", "utils", "grDevices", "graphics", "methods", "grid", "ggplot2") %in% got))
})

check("linkingto_is_followed_by_default", {
  got <- value_of(xp01_call("readr"))
  testthat::expect_true(all(c("cpp11", "tzdb") %in% got))
})

check("other_field_sets_change_the_closure", {
  testthat::expect_identical(value_of(xp01_call("tidyr", "Imports")), xp_closure("tidyr", "Imports"))
  testthat::expect_identical(value_of(xp01_call("readr", c("Depends", "Imports"))), xp_closure("readr", c("Depends", "Imports")))
  testthat::expect_identical(value_of(xp01_call("tidyr", "LinkingTo")), xp_closure("tidyr", "LinkingTo"))
})

check("result_is_sorted_in_c_locale_without_duplicates", {
  got <- value_of(xp01_call("ggplot2"))
  testthat::expect_identical(got, sort(unique(got), method = "radix"))
  testthat::expect_true(is.character(got))
  testthat::expect_null(names(got))
})

check("invalid_arguments_are_errors", {
  works <- xp01_call("R6")
  expect_stops(xp01_call("notARealPackageName"), works = works)
  expect_stops(xp01_call(c("R6", "cli")), works = works)
  expect_stops(xp01_call(NA_character_), works = works)
  expect_stops(xp01_call("R6", "Imports2"), works = works)
  expect_stops(xp01_call("R6", "Suggests"), works = works)
  expect_stops(xp01_call("R6", character()), works = works)
})

check("runs_without_warnings_and_does_not_use_the_network", {
  res <- xp01_call("dplyr")
  value_of(res)
  expect_no_warnings(res)
})
