#### control: reference
# Trusted reference: expand.grid for the combinations, then exec()-style named-argument calls.
evaluate_grid <- function(params, f) {
  if (!is.list(params) || !length(params) || is.null(names(params)) || anyNA(names(params)) ||
      any(names(params) == "") || anyDuplicated(names(params)) || !all(vapply(params, function(z) is.atomic(z) && length(z) > 0, logical(1)))) {
    stop("params must be a named list of non-empty atomic vectors")
  }
  if (!is.function(f)) stop("f must be a function")
  grid <- expand.grid(params, stringsAsFactors = FALSE, KEEP.OUT.ATTRS = FALSE)
  res <- vapply(seq_len(nrow(grid)), function(i) {
    r <- do.call(f, lapply(grid, function(col) col[[i]]))
    if (!is.numeric(r) || length(r) != 1L) stop("f must return a single number")
    as.numeric(r)
  }, numeric(1))
  grid$result <- res
  grid
}

#### control: alternate_purrr_pmap
# Alternate valid solution: purrr::pmap_dbl over the expanded grid (named columns are matched by name).
evaluate_grid <- function(params, f) {
  stopifnot(is.list(params), length(params) > 0, !is.null(names(params)), all(names(params) != ""),
            !anyDuplicated(names(params)), all(vapply(params, function(z) is.atomic(z) && length(z) > 0, logical(1))),
            is.function(f))
  grid <- tidyr::expand_grid(!!!rev(params))
  grid <- grid[names(params)]
  res <- purrr::pmap_dbl(grid, function(...) {
    r <- f(...)
    if (!is.numeric(r) || length(r) != 1L) stop("not a single number")
    r
  })
  out <- as.data.frame(grid)
  out$result <- res
  out
}

#### control: wrong_legacy_purrr_unchanged
# The legacy code as delivered: deprecated purrr functions warn.
evaluate_grid <- function(params, f) {
  grid <- purrr::cross(params)
  results <- purrr::invoke_map(f, grid)
  data.frame(do.call(rbind, lapply(grid, unlist)), result = unlist(results))
}

#### control: wrong_last_parameter_varies_fastest
# Plausible wrong strategy: nested loops with the last parameter varying fastest.
evaluate_grid <- function(params, f) {
  if (!is.list(params) || !length(params) || is.null(names(params)) || !is.function(f)) stop("bad")
  g <- expand.grid(rev(params), stringsAsFactors = FALSE, KEEP.OUT.ATTRS = FALSE)
  g <- g[rev(names(g))]
  g$result <- vapply(seq_len(nrow(g)), function(i) as.numeric(do.call(f, lapply(g[names(params)], function(c) c[[i]]))), numeric(1))
  g
}

#### control: wrong_factors_from_expand_grid
# Plausible wrong strategy: expand.grid() default turns character parameters into factors.
evaluate_grid <- function(params, f) {
  if (!is.list(params) || !length(params) || is.null(names(params)) || !is.function(f)) stop("bad")
  g <- expand.grid(params)
  g$result <- vapply(seq_len(nrow(g)), function(i) as.numeric(do.call(f, lapply(as.list(g[names(params)]), function(c) as.vector(c)[[i]]))), numeric(1))
  g
}

#### control: wrong_positional_arguments
# Plausible wrong strategy: arguments are passed by position, ignoring the formals' order.
evaluate_grid <- function(params, f) {
  if (!is.list(params) || !length(params) || is.null(names(params)) || !is.function(f)) stop("bad")
  g <- expand.grid(params, stringsAsFactors = FALSE, KEEP.OUT.ATTRS = FALSE)
  g$result <- vapply(seq_len(nrow(g)), function(i) as.numeric(do.call(f, unname(lapply(params_row <- as.list(g[i, , drop = FALSE]), identity)))), numeric(1))
  g
}

#### control: wrong_no_input_validation
# Boundary case turned wrong: nothing is validated, an invalid f returning a vector is accepted.
evaluate_grid <- function(params, f) {
  g <- expand.grid(params, stringsAsFactors = FALSE, KEEP.OUT.ATTRS = FALSE)
  g$result <- sapply(seq_len(nrow(g)), function(i) do.call(f, lapply(g[names(params)], function(c) c[[i]])))
  g
}

#### control: edge_returns_tibble
# Boundary case: right values but a tibble instead of a plain data frame (expected: not fully correct).
# expect: fail
evaluate_grid <- function(params, f) {
  if (!is.list(params) || !length(params) || is.null(names(params)) || !is.function(f)) stop("bad")
  g <- expand.grid(params, stringsAsFactors = FALSE, KEEP.OUT.ATTRS = FALSE)
  g$result <- vapply(seq_len(nrow(g)), function(i) as.numeric(do.call(f, lapply(g[names(params)], function(c) c[[i]]))), numeric(1))
  tibble::as_tibble(g)
}

#### control: malformed_returns_vector
# Malformed submission: only the results.
# expect: fail
evaluate_grid <- function(params, f) {
  g <- expand.grid(params, stringsAsFactors = FALSE)
  vapply(seq_len(nrow(g)), function(i) do.call(f, as.list(g[i, ])), numeric(1))
}

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
evaluate_grid <- function(params, f) stop("todo")
