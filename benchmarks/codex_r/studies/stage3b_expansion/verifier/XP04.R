# Hidden checks for XP04 (repository identity of installed packages; runs in the Bioconductor image).
# Oracle: classification rules applied to read.dcf() of the installed DESCRIPTION files.

xp04_oracle <- function(pkgs) {
  rows <- lapply(pkgs, function(p) {
    d <- xp_desc(p)
    if (is.null(d)) return(list(package = p, version = NA_character_, origin = "not_installed", bioc_release = NA_character_))
    repo <- d[["Repository"]]
    if (!is.null(repo) && is.na(repo)) repo <- NULL
    origin <- if (identical(d[["Priority"]], "base")) "base"
    else if ((!is.null(repo) && grepl("^Bioconductor", repo)) || (is.null(repo) && !is.null(d[["biocViews"]]))) "bioconductor"
    else if (!is.null(repo) && repo %in% c("CRAN", "RSPM")) "cran"
    else "unknown"
    rel <- NA_character_
    if (origin == "bioconductor" && !is.null(repo) && grepl("^Bioconductor\\s+\\S", repo)) {
      rel <- trimws(sub("^Bioconductor\\s+", "", repo))
    }
    list(package = p, version = d[["Version"]], origin = origin, bioc_release = rel)
  })
  out <- data.frame(package = vapply(rows, `[[`, "", "package"), version = vapply(rows, `[[`, "", "version"),
                    origin = vapply(rows, `[[`, "", "origin"), bioc_release = vapply(rows, `[[`, "", "bioc_release"),
                    stringsAsFactors = FALSE)
  out
}

xp04_set <- c("DESeq2", "dplyr", "stats", "docopt", "MASS", "S4Vectors", "notARealPackageName", "Biobase", "BiocVersion",
              "littler", "survival", "dplyr", "SummarizedExperiment", "methods")

local({
  o <- xp04_oracle(xp04_set)
  stopifnot(identical(o$origin[o$package == "DESeq2"], "bioconductor"), identical(o$origin[o$package == "docopt"], "cran"),
            identical(o$origin[o$package == "MASS"], "cran"), identical(o$origin[o$package == "stats"], "base"),
            identical(o$origin[o$package == "notARealPackageName"], "not_installed"),
            !anyNA(o$bioc_release[o$origin == "bioconductor"]), all(is.na(o$bioc_release[o$origin != "bioconductor"])))
  stopifnot(identical(o$bioc_release[o$package == "DESeq2"], "3.22"), !("unknown" %in% o$origin))
  stopifnot(xp_desc("docopt")[["Repository"]] == "RSPM", xp_desc("MASS")[["Priority"]] == "recommended")
})

xp04_call <- function(p) call_wrapped("package_origin", p)

xp04_same <- function(got, want) {
  testthat::expect_true(is.data.frame(got))
  testthat::expect_identical(names(got), c("package", "version", "origin", "bioc_release"))
  testthat::expect_identical(nrow(got), nrow(want))
  for (nm in names(want)) {
    testthat::expect_true(is.character(got[[nm]]), info = nm)
    testthat::expect_identical(unname(got[[nm]]), unname(want[[nm]]), info = nm)
  }
}

check("origin_table_matches_the_oracle", {
  xp04_same(as.data.frame(value_of(xp04_call(xp04_set))), xp04_oracle(xp04_set))
})

check("rows_follow_the_input_order_including_duplicates", {
  got <- as.data.frame(value_of(xp04_call(xp04_set)))
  testthat::expect_identical(got$package, xp04_set)
  testthat::expect_identical(sum(got$package == "dplyr"), 2L)
})

check("rspm_snapshots_count_as_cran", {
  got <- as.data.frame(value_of(xp04_call(c("docopt", "littler"))))
  testthat::expect_identical(got$origin, c("cran", "cran"))
})

check("recommended_packages_are_not_base", {
  got <- as.data.frame(value_of(xp04_call(c("MASS", "survival", "Matrix", "nlme"))))
  testthat::expect_identical(got$origin, rep("cran", 4L))
})

check("base_packages_are_base_whatever_their_repository_field", {
  got <- as.data.frame(value_of(xp04_call(c("stats", "utils", "methods", "tools"))))
  testthat::expect_identical(got$origin, rep("base", 4L))
  testthat::expect_true(all(is.na(got$bioc_release)))
})

check("bioconductor_packages_carry_their_release", {
  got <- as.data.frame(value_of(xp04_call(c("DESeq2", "Biobase", "BiocVersion", "IRanges"))))
  testthat::expect_identical(got$origin, rep("bioconductor", 4L))
  testthat::expect_identical(got$bioc_release, rep("3.22", 4L))
})

check("packages_that_are_not_installed_have_missing_version_and_release", {
  got <- as.data.frame(value_of(xp04_call(c("notARealPackageName", "alsoNotReal"))))
  testthat::expect_identical(got$origin, rep("not_installed", 2L))
  testthat::expect_true(all(is.na(got$version)) && all(is.na(got$bioc_release)))
})

check("installed_version_text_is_reported_exactly", {
  got <- as.data.frame(value_of(xp04_call(c("MASS", "DESeq2"))))
  testthat::expect_identical(got$version, c(xp_desc("MASS")[["Version"]], xp_desc("DESeq2")[["Version"]]))
})

check("result_is_a_plain_data_frame_with_default_row_names", {
  got <- value_of(xp04_call(xp04_set))
  testthat::expect_false(inherits(got, "tbl_df"))
  testthat::expect_identical(rownames(got), as.character(seq_len(nrow(got))))
  testthat::expect_false(any(vapply(got, is.factor, logical(1))))
})

check("invalid_arguments_are_errors", {
  works <- xp04_call("dplyr")
  expect_stops(xp04_call(character()), works = works)
  expect_stops(xp04_call(c("dplyr", NA)), works = works)
  expect_stops(xp04_call(1:3), works = works)
  expect_stops(xp04_call(NULL), works = works)
})

check("runs_without_warnings", {
  res <- xp04_call(xp04_set)
  value_of(res)
  expect_no_warnings(res)
})
