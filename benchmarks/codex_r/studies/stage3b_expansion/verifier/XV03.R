# Hidden checks for XV03 (class() of a matrix has length 2 in R >= 4.0; tibbles are data frames).
# Oracle: a declarative table of constructions and kinds, written independently of the
# classification code a candidate would use.

xv03_cases <- function() {
  list(
    list(quote(NULL), "NULL"),
    list(quote(mean), "function"),
    list(quote(sum), "function"),
    list(quote(`+`), "function"),
    list(quote(function(a, b = 2) a + b), "function"),
    list(quote(tibble::tibble(a = 1:3, b = letters[1:3])), "tibble"),
    list(quote(tibble::tibble()), "tibble"),
    list(quote(data.frame(a = 1:3)), "data.frame"),
    list(quote(data.frame()), "data.frame"),
    list(quote(matrix(1:6, 2)), "matrix"),
    list(quote(matrix(c("a", "b"), 1)), "matrix"),
    list(quote(matrix(numeric(0), 0, 3)), "matrix"),
    list(quote(matrix(TRUE, 3, 0)), "matrix"),
    list(quote(array(1:8, c(2, 2, 2))), "array"),
    list(quote(array(1:3, 3)), "array"),
    list(quote(array(0, c(2, 1, 1, 2))), "array"),
    list(quote(factor(c("u", "v", "u"))), "factor"),
    list(quote(factor(character())), "factor"),
    list(quote(ordered(c("lo", "hi"), levels = c("lo", "hi"))), "factor"),
    list(quote(list(1, "a")), "list"),
    list(quote(list()), "list"),
    list(quote(c(1.5, 2)), "vector"),
    list(quote(1:3), "vector"),
    list(quote("text"), "vector"),
    list(quote(NA), "vector"),
    list(quote(character()), "vector"),
    list(quote(as.Date("2026-01-01")), "vector"),
    list(quote(as.POSIXct("2026-01-01 10:00:00", tz = "UTC")), "vector"),
    list(quote(c(a = 1, b = 2)), "vector"),
    list(quote(1i), "vector"),
    list(quote(new.env()), "other"),
    list(quote(y ~ x), "other")
  )
}

local({
  cs <- xv03_cases()
  kinds <- vapply(cs, function(z) z[[2]], "")
  stopifnot(length(cs) >= 30, all(c("NULL", "function", "tibble", "data.frame", "matrix", "array", "factor",
                                    "list", "vector", "other") %in% kinds))
  # The oracle table itself must agree with the defining properties of each object.
  for (z in cs) {
    obj <- eval(z[[1]])
    k <- z[[2]]
    if (k == "matrix") stopifnot(length(dim(obj)) == 2L, !is.data.frame(obj))
    if (k == "array") stopifnot(length(dim(obj)) != 2L, !is.null(dim(obj)))
    if (k == "tibble") stopifnot(inherits(obj, "tbl_df"))
    if (k == "data.frame") stopifnot(is.data.frame(obj), !inherits(obj, "tbl_df"))
  }
})

xv03_run <- function(expr) {
  # The object is constructed inside the candidate session so any class is preserved.
  call_wrapped("object_kind", eval(expr))
}

xv03_kind_check <- function(kind) {
  cs <- Filter(function(z) z[[2]] == kind, xv03_cases())
  for (z in cs) {
    res <- xv03_run(z[[1]])
    got <- value_of(res)
    testthat::expect_identical(got, kind, info = paste(deparse(z[[1]]), collapse = ""))
    if (length(res$warnings)) stop("warning raised for ", paste(deparse(z[[1]]), collapse = ""))
  }
}

check("null_and_functions", { xv03_kind_check("NULL"); xv03_kind_check("function") })
check("tibbles_are_not_plain_data_frames", xv03_kind_check("tibble"))
check("data_frames_including_empty_ones", xv03_kind_check("data.frame"))
check("matrices_including_zero_extent_and_character_matrices", xv03_kind_check("matrix"))
check("arrays_of_one_or_three_or_more_dimensions", xv03_kind_check("array"))
check("factors_including_ordered_and_empty", xv03_kind_check("factor"))
check("plain_lists", xv03_kind_check("list"))
check("atomic_vectors_including_classed_dates_and_named_vectors", xv03_kind_check("vector"))
check("environments_symbols_calls_and_formulas_are_other", xv03_kind_check("other"))

check("result_is_always_a_single_string", {
  for (z in xv03_cases()) {
    got <- value_of(xv03_run(z[[1]]))
    testthat::expect_true(is.character(got) && length(got) == 1L && !is.na(got))
  }
})

check("no_input_raises_an_error_or_a_warning", {
  for (z in xv03_cases()) {
    res <- xv03_run(z[[1]])
    testthat::expect_true(isTRUE(res$ok), info = paste(deparse(z[[1]]), collapse = ""))
    testthat::expect_length(res$warnings, 0L)
  }
})
